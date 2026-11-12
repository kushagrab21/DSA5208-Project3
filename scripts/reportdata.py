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
NAMES = {"vanda": "Vanda", "atlas": "Atlas"}


class MixedBuild(Exception):
    """A speedup or efficiency series whose runs come from more than one binary."""


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
        gfiles = run_record.expand([d], graph=True) if os.path.isdir(d) else []
        self.files = files + gfiles
        self.rows = run_record.figure_rows(files, validated=validated(results)) if files else []
        # the graph solver's rows (p3graph, qualified by validate_graph.py on this cluster), same rules
        self.rows += run_record.graph_figure_rows(gfiles, validated=validated(results)) if gfiles else []
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

    def max_cores(self, group):
        cs = [self.plan["cells"][c] for c in self.group_cells(group)]
        return max([c["ranks"] * c["threads"] for c in cs] or [0])

    def check_same_build(self, cids, label):
        """Every speedup/efficiency uses a 1-core baseline from the same cluster AND build: refuse a mixed series."""
        shas = sorted(set(r["binary_sha256"] for c in cids for r in self.cell_rows.get(c, [])))
        if len(shas) > 1:
            raise MixedBuild("%s on %s mixes binaries %s: rerun the series with one binary" %
                             (label, self.cluster, ", ".join(s[:12] for s in shas)))

    def filled_view(self):
        """The same data with every group reduced to its FILLED cells, for drawing what exists while the rest of a
        group waits (a partial figure says so). The cells' rows are shared, the plan is a copy; never use a view for a
        value that names a core count it does not contain."""
        import copy
        v = copy.copy(self)
        v.plan = copy.deepcopy(self.plan)
        for g in v.plan["groups"].values():
            g["cells"] = [c for c in g["cells"] if c in self.cell_rows]
        v.full = self
        return v

    def used_rows(self, cids):
        return [r for c in cids for r in self.cell_rows.get(c, [])]

    def sources(self, cids):
        """Files and their sha256 for the rows behind a figure or table."""
        used = self.used_rows(cids)
        files = sorted(set(r["_file"] for r in used))
        return [{"path": os.path.relpath(p, REPO) if p.startswith(REPO) else p, "sha256": sha256(p),
                 "rows_used": sum(1 for r in used if r["_file"] == p)} for p in files]


_CACHE = {}


def data(results, name):
    key = (os.path.abspath(results), name)
    if key not in _CACHE:
        _CACHE[key] = ClusterData(results, name)
    return _CACHE[key]


def choose(results, groups):
    """The cluster whose runs a figure/table/section uses, per group of cells: the first of CPU_PLANS (Vanda first)
    that has every planned run of these groups; otherwise the one with the most of them filled (Vanda on a tie).
    One section never mixes clusters, so no speedup curve does either."""
    cands = [data(results, n) for n in CPU_PLANS]
    for d in cands:
        if all(g in d.plan["groups"] for g in groups) and d.complete(*groups):
            return d
    score = lambda d: (sum(d.group_status(g)[0] for g in groups if g in d.plan["groups"]), d is cands[0])  # noqa
    return max(cands, key=score)


def cpu_data(results):
    """Kept for callers that want one CPU cluster: the choice for strong and weak scaling."""
    return choose(results, ["strong", "weak"])


def gpu_data(results):
    return data(results, GPU_PLAN)
