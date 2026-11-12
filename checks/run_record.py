#!/usr/bin/env python3
"""Run-record check: validates the CSV rows the solver writes, and is the ONLY way figure scripts load data.

  python3 checks/run_record.py [CSV or directory ...]       validate rows (default: results/), print a summary
  python3 checks/run_record.py --for-figures [CSV ...]       as above, and REFUSE unless every row may reach a
                                                             report figure (cluster atlas|vanda, PBS job id, a binary
                                                             qualified by validate.py on that cluster, no breakdown)
  python3 checks/run_record.py --selftest                    qualify this check on fixtures (see below)
  python3 checks/run_record.py --graph [--for-figures] [...]  the same for the graph solver's rows (*.graph.csv)

Figure scripts call figure_rows(paths). Development plots must call figure_rows(paths, allow_local=True), which
marks every returned row, and must label the figure as local development data.
Standard library only, Python >= 3.6.
"""
import argparse
import glob
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3common as C  # noqa: E402

INT_COLS = ["nodes", "ranks", "threads", "gpus", "dim", "n", "unknowns", "nonzeros", "local_max", "local_min",
            "iters_req", "iters", "repeat", "msgs_per_exch", "doubles_per_exch_max", "allreduces", "exchanges"]
FLOAT_COLS = ["t_total", "t_halo", "t_reduce", "t_compute", "t_other", "t_halo_max", "t_reduce_max",
              "t_compute_max", "t_setup", "rel_res", "true_rel_res", "err_max", "err_l2"]
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def expand(paths, graph=False):
    """CSV files under paths. graph=False: the Poisson records (p3run-1); graph=True: only the graph solver's records
    (p3graph-1, files named *.graph.csv). Each loader then refuses a file whose header is not its schema."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "**", "*.csv"), recursive=True))
        else:
            out.append(p)
    # validated_binaries.csv and the per-cluster jobs.csv (PBS job start/end) are not run records
    out = [p for p in out if os.path.basename(p) not in (os.path.basename(C.VALIDATED), "jobs.csv", "sync.csv")
           and "/.staging/" not in p]
    return [p for p in out if p.endswith(C.GRAPH_SUFFIX) == graph]


def check_row(r):
    """Returns a list of problems with one row (empty if the row is well formed)."""
    bad = []
    if r.get("schema") != C.RECORD_SCHEMA:
        bad.append("schema %r" % r.get("schema"))
        return bad
    v = {}
    for k in INT_COLS:
        try:
            v[k] = int(r[k])
        except (ValueError, TypeError, KeyError):
            bad.append("%s not an integer: %r" % (k, r.get(k)))
    for k in FLOAT_COLS:
        try:
            v[k] = float(r[k])
        except (ValueError, TypeError, KeyError):
            bad.append("%s not a number: %r" % (k, r.get(k)))
    if bad:
        return bad
    if r["cluster"] not in C.CLUSTERS + ("local",):
        bad.append("cluster %r" % r["cluster"])
    if r["cluster"] in C.CLUSTERS and r["pbs_jobid"] in ("", "none"):
        bad.append("cluster row without a PBS job id")
    if v["dim"] not in (2, 3):
        bad.append("dim %d" % v["dim"])
    else:
        N = v["n"] ** v["dim"]
        nnz = N + 2 * v["dim"] * (v["n"] - 1) * v["n"] ** (v["dim"] - 1)
        if v["unknowns"] != N:
            bad.append("unknowns %d != n^dim %d" % (v["unknowns"], N))
        if v["nonzeros"] != nnz:
            bad.append("nonzeros %d != %d" % (v["nonzeros"], nnz))
        if not (v["local_min"] * v["ranks"] <= N <= v["local_max"] * v["ranks"]):
            bad.append("local sizes inconsistent with unknowns")
    for k in ("nodes", "ranks", "threads", "repeat"):
        if k in v and v[k] < 1:
            bad.append("%s < 1" % k)
    if r["cg"] not in ("classic", "pipelined"):
        bad.append("cg %r" % r["cg"])
    if r["halo"] not in ("blocking", "overlap"):
        bad.append("halo %r" % r["halo"])
    if r["mode"] not in ("fixed", "tol"):
        bad.append("mode %r" % r["mode"])
    if r["mode"] == "fixed" and v["iters"] > v["iters_req"]:
        bad.append("more iterations than requested")
    if v["t_total"] <= 0:
        bad.append("t_total <= 0")
    parts = v["t_halo"] + v["t_reduce"] + v["t_compute"]
    if min(v["t_halo"], v["t_reduce"], v["t_compute"]) < 0 or parts > v["t_total"] * (1 + 1e-6) + 1e-6:
        bad.append("time components do not fit inside t_total")
    if not SHA_RE.match(r.get("binary_sha256", "")):
        bad.append("binary_sha256 missing")
    return bad


def load_rows(paths):
    """Reads and checks every row; raises Refused on the first malformed file."""
    rows = []
    for p in expand(paths):
        with open(p, newline="") as f:
            header = f.readline().strip().split(",")
        if header != C.RECORD_COLUMNS:
            raise C.Refused("%s: header is not the p3run-1 record schema" % p)
        for i, r in enumerate(C.read_csv(p), start=2):
            bad = check_row(r)
            if bad:
                raise C.Refused("%s line %d: %s" % (p, i, "; ".join(bad)))
            r["_file"] = p
            rows.append(r)
    return rows


def figure_rows(paths, allow_local=False, validated=None):
    """The rows a figure may use. Refuses (raises Refused) instead of silently dropping rows.

    allow_local=True is for development plots only: rows are returned with _dev=True and the plot must say so.
    validated: list of QUALIFIED entries (default: results/validated_binaries.csv).
    """
    rows = load_rows(paths)
    if not rows:
        raise C.Refused("no run records in %s" % ", ".join(paths))
    entries = C.validated_entries() if validated is None else validated
    ok = set((e["binary_sha256"], e["cluster"]) for e in entries)
    local = [r for r in rows if r["cluster"] not in C.CLUSTERS]
    if local and not allow_local:
        raise C.Refused("%d of %d rows are not from Atlas or Vanda (cluster=%s); report figures use cluster rows "
                        "only" % (len(local), len(rows), ",".join(sorted(set(r["cluster"] for r in local)))))
    unval = [r for r in rows if (r["binary_sha256"], r["cluster"]) not in ok]
    if unval:
        raise C.Refused("%d rows come from a binary that validate.py has not qualified on that cluster (e.g. %s on "
                        "%s)" % (len(unval), unval[0]["binary_sha256"][:12], unval[0]["cluster"]))
    broken = [r for r in rows if r["breakdown"] == "1" or "bug=0" not in r["build"]]
    if broken:
        raise C.Refused("%d rows ended in a CG breakdown or come from a planted-bug build" % len(broken))
    for r in rows:
        r["_dev"] = r["cluster"] not in C.CLUSTERS
    return rows


# ------------------------------------------------------------------------------------------------------------------
# Graph records (bin/p3graph, schema p3graph-1)
# ------------------------------------------------------------------------------------------------------------------
G_INT = ["nodes", "ranks", "threads", "vertices", "edges", "nonzeros", "max_degree", "K", "s", "seed", "rhs",
         "iters_req", "iters", "iters_min", "iters_max", "repeat", "rows_max", "rows_min", "nnz_max", "nnz_min",
         "ghosts_max", "ghosts_sum", "edge_cut", "neighbors_max", "doubles_per_exch_max", "allreduces", "exchanges",
         "eval_vertices"]
G_FLOAT = ["keep", "avg_degree", "a", "theta", "t_total", "t_solve", "t_iter", "t_halo", "t_reduce", "t_compute",
           "t_other", "t_halo_max", "t_reduce_max", "t_compute_max", "t_setup", "t_read", "nnz_imbalance",
           "cut_fraction", "rel_res", "true_rel_res", "accuracy", "unreached", "majority", "random"]
DATASETS = ("email-Eu-core", "com-amazon", "com-dblp", "com-youtube", "com-lj", "com-orkut", "tiny")


def check_graph_row(r):
    bad = []
    if r.get("schema") != C.GRAPH_SCHEMA:
        return ["schema %r" % r.get("schema")]
    v = {}
    for k in G_INT:
        try:
            v[k] = int(r[k])
        except (ValueError, TypeError, KeyError):
            bad.append("%s not an integer: %r" % (k, r.get(k)))
    for k in G_FLOAT:
        try:
            v[k] = float(r[k])
        except (ValueError, TypeError, KeyError):
            bad.append("%s not a number: %r" % (k, r.get(k)))
    if bad:
        return bad
    if r["cluster"] not in C.CLUSTERS + ("local",):
        bad.append("cluster %r" % r["cluster"])
    if r["cluster"] in C.CLUSTERS and r["pbs_jobid"] in ("", "none"):
        bad.append("cluster row without a PBS job id")
    if r["dataset"] not in DATASETS:
        bad.append("dataset %r" % r["dataset"])
    if r["order"] not in ("natural", "bfs") or r["part"] not in ("rows", "nnz"):
        bad.append("order/part %r/%r" % (r["order"], r["part"]))
    if r["exchange"] not in ("alltoallv", "neighbor", "overlap") or r["cg"] not in ("classic", "pipelined"):
        bad.append("exchange/cg %r/%r" % (r["exchange"], r["cg"]))
    if r["mode"] not in ("fixed", "tol"):
        bad.append("mode %r" % r["mode"])
    if v["nonzeros"] != 2 * v["edges"] + v["vertices"]:
        bad.append("nonzeros != 2 edges + vertices")
    if not (v["rows_min"] * v["ranks"] <= v["vertices"] <= v["rows_max"] * v["ranks"]):
        bad.append("rows per rank inconsistent with vertices")
    if v["edge_cut"] > v["edges"] or (v["ranks"] == 1 and v["edge_cut"] != 0):
        bad.append("edge cut inconsistent")
    if not (0 < v["keep"] <= 1) or v["a"] <= 0:
        bad.append("keep or a out of range")
    if v["rhs"] < 1 or v["rhs"] > v["K"] or v["iters"] < v["iters_min"]:
        bad.append("rhs/iterations inconsistent")
    if v["rhs"] == v["K"] and not (0 <= v["accuracy"] <= 1 and 0 <= v["unreached"] <= 1):
        bad.append("accuracy or unreached outside [0, 1]")
    if v["t_total"] <= 0:
        bad.append("t_total <= 0")
    parts = v["t_halo"] + v["t_reduce"] + v["t_compute"]
    if min(v["t_halo"], v["t_reduce"], v["t_compute"]) < 0 or parts > v["t_total"] * (1 + 1e-6) + 1e-6:
        bad.append("time components do not fit inside t_total")
    if not SHA_RE.match(r.get("binary_sha256", "")) or not SHA_RE.match(r.get("seeds_sha", "")):
        bad.append("binary_sha256 or seeds_sha missing")
    if "graph=1" not in r.get("build", ""):
        bad.append("not a p3graph build")
    return bad


def load_graph_rows(paths):
    rows = []
    for p in expand(paths, graph=True):
        with open(p, newline="") as f:
            header = f.readline().strip().split(",")
        if header != C.GRAPH_COLUMNS:
            raise C.Refused("%s: header is not the %s record schema" % (p, C.GRAPH_SCHEMA))
        for i, r in enumerate(C.read_csv(p), start=2):
            bad = check_graph_row(r)
            if bad:
                raise C.Refused("%s line %d: %s" % (p, i, "; ".join(bad)))
            r["_file"] = p
            rows.append(r)
    return rows


GRAPH_CASES = ("G1", "G2")


def graph_figure_rows(paths, allow_local=False, validated=None):
    """Graph rows a figure may use: cluster atlas|vanda with a PBS job id, from a p3graph binary qualified ON THAT
    CLUSTER by validate_graph.py (cases G1 and G2, planted bug refused), no CG breakdown, no planted-bug build."""
    rows = load_graph_rows(paths)
    if not rows:
        raise C.Refused("no graph run records in %s" % ", ".join(paths))
    entries = C.validated_entries() if validated is None else validated
    ok = set((e["binary_sha256"], e["cluster"]) for e in entries
             if set(GRAPH_CASES) <= set(e.get("cases", "").split(";")))
    local = [r for r in rows if r["cluster"] not in C.CLUSTERS]
    if local and not allow_local:
        raise C.Refused("%d of %d graph rows are not from Atlas or Vanda; report figures use cluster rows only" %
                        (len(local), len(rows)))
    unval = [r for r in rows if r["cluster"] in C.CLUSTERS and (r["binary_sha256"], r["cluster"]) not in ok]
    if unval:
        raise C.Refused("%d graph rows come from a binary that validate_graph.py has not qualified on that cluster "
                        "(e.g. %s on %s)" % (len(unval), unval[0]["binary_sha256"][:12], unval[0]["cluster"]))
    broken = [r for r in rows if r["breakdown"] == "1" or "bug=0" not in r["build"]]
    if broken:
        raise C.Refused("%d graph rows ended in a CG breakdown or come from a planted-bug build" % len(broken))
    for r in rows:
        r["_dev"] = r["cluster"] not in C.CLUSTERS
    return rows


def poisson_sees_none(d):
    if expand([d]):
        raise C.Refused("the Poisson loader picked up %s" % expand([d]))


def graph_selftest(results):
    src = expand([os.path.join(C.RESULTS, "local")], graph=True)
    if not src:
        print("SELFTEST graph: no local graph rows to build fixtures from (run: python3 checks/run_plan.py run --plan local --job local-graph)")
        return False
    base = C.read_csv(src[0])[0]
    with tempfile.TemporaryDirectory() as td:
        def put(name, row):
            p = os.path.join(td, name + C.GRAPH_SUFFIX)
            C.append_csv(p, C.GRAPH_COLUMNS, row)
            return p
        loc = put("local", base)
        dbl = dict(base)
        dbl.update({"cluster": "vanda", "pbs_jobid": "TESTDOUBLE.0", "host": "test-double"})
        cl = put("vanda", dbl)
        val = [{"binary_sha256": dbl["binary_sha256"], "cluster": "vanda", "verdict": "QUALIFIED", "cases": "G1;G2"}]
        pois = [{"binary_sha256": dbl["binary_sha256"], "cluster": "vanda", "verdict": "QUALIFIED",
                 "cases": "V1;V2;V3;V4;V5"}]
        bug = dict(dbl)
        bug["build"] = bug["build"].replace("bug=0", "bug=1")
        bp = put("bug", bug)
        tests = [("graph: local row offered to a report figure", lambda: graph_figure_rows([loc], validated=val),
                  False),
                 ("graph: cluster row from a G1;G2-qualified binary (TEST DOUBLE)",
                  lambda: graph_figure_rows([cl], validated=val), True),
                 ("graph: same row, binary qualified only by the Poisson cases",
                  lambda: graph_figure_rows([cl], validated=pois), False),
                 ("graph: row from the planted-bug build", lambda: graph_figure_rows([bp], validated=val), False),
                 ("graph rows are invisible to the Poisson loader", lambda: poisson_sees_none(td), True)]
        for name, fn, want in tests:
            try:
                fn()
                got = True
                msg = "PASS"
            except C.Refused as e:
                got = False
                msg = "REFUSED: %s" % e
            results.append((name, "PASS" if want else "REFUSED", msg, got == want))
    return True


def summary(rows):
    by = {}
    for r in rows:
        key = (r["cluster"], r["pbs_jobid"])
        by.setdefault(key, []).append(r)
    lines = []
    for (cl, job), rs in sorted(by.items()):
        shas = sorted(set(r["binary_sha256"][:12] for r in rs))
        lines.append("  cluster=%-6s job=%-24s rows=%-4d cells=%-3d binaries=%s" %
                     (cl, job, len(rs), len(set(r["cell"] for r in rs)), ",".join(shas)))
    return lines


def selftest():
    """Qualifies the check: a local row offered for a figure must be refused; a cluster-shaped row from a
    qualified binary must pass. The pass example here is a TEST DOUBLE built from a local row (cluster, job id
    and validated list rewritten); the real pass example is the first Atlas/Vanda record."""
    src = expand([os.path.join(C.RESULTS, "local")])
    if not src:
        print("SELFTEST: no local rows to build fixtures from (run: python3 checks/run_plan.py run --plan local --job local-smoke)")
        return 1
    base = C.read_csv(src[0])[0]
    results = []
    with tempfile.TemporaryDirectory() as td:
        loc = os.path.join(td, "local.csv")
        C.append_csv(loc, C.RECORD_COLUMNS, base)
        try:
            figure_rows([loc])
            results.append(("local row offered to a report figure", "REFUSED", "PASSED", False))
        except C.Refused as e:
            results.append(("local row offered to a report figure", "REFUSED", "REFUSED: %s" % e, True))
        dbl = dict(base)
        dbl.update({"cluster": "vanda", "pbs_jobid": "TESTDOUBLE.0", "host": "test-double"})
        cl = os.path.join(td, "vanda.csv")
        C.append_csv(cl, C.RECORD_COLUMNS, dbl)
        val = [{"binary_sha256": dbl["binary_sha256"], "cluster": "vanda", "verdict": "QUALIFIED"}]
        try:
            figure_rows([cl], validated=val)
            results.append(("cluster row from a qualified binary (TEST DOUBLE)", "PASS", "PASS", True))
        except C.Refused as e:
            results.append(("cluster row from a qualified binary (TEST DOUBLE)", "PASS", "REFUSED: %s" % e, False))
        try:
            figure_rows([cl], validated=[])
            results.append(("cluster row from an unqualified binary", "REFUSED", "PASSED", False))
        except C.Refused as e:
            results.append(("cluster row from an unqualified binary", "REFUSED", "REFUSED: %s" % e, True))
        nojob = dict(dbl)
        nojob["pbs_jobid"] = "none"
        nj = os.path.join(td, "nojob.csv")
        C.append_csv(nj, C.RECORD_COLUMNS, nojob)
        try:
            figure_rows([nj], validated=val)
            results.append(("cluster label without a PBS job id", "REFUSED", "PASSED", False))
        except C.Refused as e:
            results.append(("cluster label without a PBS job id", "REFUSED", "REFUSED: %s" % e, True))
    graph_selftest(results)
    ok = all(r[3] for r in results)
    for name, want, got, good in results:
        print("  %-52s expected %-8s got %s  %s" % (name, want, got, "ok" if good else "WRONG"))
    print("SELFTEST: %s  (pass example is a test double; the real one is the first Atlas/Vanda row)" %
          ("QUALIFIED on fixtures" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--for-figures", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--graph", action="store_true", help="the graph solver's rows (*.graph.csv)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.graph:
        paths = a.paths or [d for d in glob.glob(os.path.join(C.RESULTS, "*")) if os.path.isdir(d)
                            and os.path.basename(d) != "validation"]
        try:
            rows = graph_figure_rows(paths) if a.for_figures else load_graph_rows(paths)
        except C.Refused as e:
            print("GRAPH RUN RECORD: REFUSED: %s" % e)
            return 1
        print("GRAPH RUN RECORD: %d rows well formed%s" % (len(rows), "; all usable in report figures"
                                                           if a.for_figures else ""))
        for line in summary(rows):
            print(line)
        return 0
    paths = a.paths or [d for d in glob.glob(os.path.join(C.RESULTS, "*")) if os.path.isdir(d)
                        and os.path.basename(d) != "validation"]
    try:
        rows = figure_rows(paths) if a.for_figures else load_rows(paths)
    except C.Refused as e:
        print("RUN RECORD: REFUSED: %s" % e)
        return 1
    print("RUN RECORD: %d rows well formed%s" % (len(rows), "; all usable in report figures" if a.for_figures
                                                   else ""))
    for line in summary(rows):
        print(line)
    n_cluster = sum(1 for r in rows if r["cluster"] in C.CLUSTERS)
    print("  rows from atlas/vanda: %d; local (development only): %d" % (n_cluster, len(rows) - n_cluster))
    return 0


if __name__ == "__main__":
    sys.exit(main())
