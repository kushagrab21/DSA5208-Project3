"""Cluster run records -> plan cells, for the report's figures, tables and values.

Rows are loaded ONLY through checks/run_record.figure_rows (cluster atlas|vanda, PBS job id, a binary qualified on
that cluster, no breakdown); a local row anywhere in the cluster folders makes the load refuse, not skip.
A cell is filled when one PBS job holds all its repeats; if several jobs do (a recorded rerun), the latest is used.
"""
import csv
import glob
import hashlib
import json
import os
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
import run_record  # noqa: E402
from run_plan import matches  # noqa: E402

CPU_PLANS = ("vanda", "atlas")  # report preference order for the CPU sections
GPU_PLAN = "vanda"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def load_plan(name):
    with open(os.path.join(REPO, "config", "run_plan.%s.json" % name)) as f:
        return json.load(f)


def validated(results):
    p = os.path.join(results, "validated_binaries.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("verdict") == "QUALIFIED"]


class ClusterData:
    """Rows of one cluster plan, mapped to its cells."""

    def __init__(self, results, plan_name):
        self.results = results
        self.plan = load_plan(plan_name)
        self.cluster = self.plan["cluster"]
        d = os.path.join(results, self.cluster)
        files = run_record.expand([d]) if os.path.isdir(d) else []
        self.files = files
        self.rows = run_record.figure_rows(files, validated=validated(results)) if files else []
        self.cell_rows = {}
        by = {}
        for r in self.rows:
            c = self.plan["cells"].get(r["cell"])
            if c is None or not matches(c, r):
                continue
            by.setdefault(r["cell"], {}).setdefault(r["pbs_jobid"], []).append(r)
        for cid, jobs in by.items():
            need = self.plan["cells"][cid].get("repeats", 1)
            full = [rs for rs in jobs.values() if len(set(x["repeat"] for x in rs)) >= need]
            if full:
                self.cell_rows[cid] = max(full, key=lambda rs: max(x["utc"] for x in rs))

    # -- status ---------------------------------------------------------------------------------------------------
    def group_cells(self, group):
        return self.plan["groups"].get(group, {}).get("cells", [])

    def group_status(self, group):
        cells = self.group_cells(group)
        return sum(1 for c in cells if c in self.cell_rows), len(cells)

    def complete(self, *groups):
        return all(self.group_status(g)[0] == self.group_status(g)[1] > 0 for g in groups)

    def waiting(self, *groups):
        out = []
        for g in groups:
            f, n = self.group_status(g)
            if n == 0:
                out.append("%s: not in the %s plan" % (g, self.plan["plan"]))
            elif f < n:
                out.append("%s %s: %d of %d planned runs recorded" % (self.cluster, g, f, n))
        return out

    # -- values ---------------------------------------------------------------------------------------------------
    def cells(self, group, **kw):
        out = []
        for cid in self.group_cells(group):
            c = self.plan["cells"][cid]
            if all(c.get(k) == v for k, v in kw.items()):
                out.append((cid, c))
        return out

    def med(self, cid, col="t_total"):
        rs = self.cell_rows.get(cid)
        if not rs:
            return None
        return statistics.median(float(r[col]) for r in rs)

    def row0(self, cid):
        rs = self.cell_rows.get(cid)
        return rs[0] if rs else None

    def used_rows(self, cids):
        return [r for c in cids for r in self.cell_rows.get(c, [])]

    def sources(self, cids):
        """Files and their sha256 for the rows behind a figure or table."""
        used = self.used_rows(cids)
        files = sorted(set(r["_file"] for r in used))
        return [{"path": os.path.relpath(p, REPO) if p.startswith(REPO) else p, "sha256": sha256(p),
                 "rows_used": sum(1 for r in used if r["_file"] == p)} for p in files]


def cpu_data(results):
    """The CPU plan the report uses: the first of CPU_PLANS that has any rows, else the primary (empty)."""
    first = None
    for name in CPU_PLANS:
        d = ClusterData(results, name)
        if first is None:
            first = d
        if d.rows:
            return d
    return first


def gpu_data(results):
    return ClusterData(results, GPU_PLAN)
