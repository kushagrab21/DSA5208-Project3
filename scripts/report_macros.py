#!/usr/bin/env python3
"""Generates every number, table and slot state the report uses. Nothing in the report body is typed by hand.

  python3 scripts/report_macros.py [--results results] [--figures figures] [--out report/generated]

Writes, into --out:
  values.tex   \\setval{key}{value} for every \\val{key}; a value that needs cluster runs not yet recorded is
               \\pending{key} (rendered as a visible "waiting for cluster data" mark)
  slots.tex    \\setslot{name}{1|0}{message} for every figure slot (1 = the image exists and its metadata says filled)
  tab_*.tex    table bodies; a table whose runs are missing is one row saying what it is waiting for
  status.json  every value/table/figure with filled yes/no, the E rows it serves and what it is waiting for;
               checks/requirements_check.py reads it
  literate.tex listings replacements for the non-ASCII characters in the files listed in the code appendix
Sources: config/run_plan.*.json (design values), results/validation/<cluster>/*.json (validation; Vanda or Atlas
preferred over local), cluster run records through scripts/reportdata.py (Atlas/Vanda only), figures/*.meta.json,
results/<cluster>/env/*.json (machine), checks/validate.py constants.
"""
import argparse
import datetime
import glob
import collections
import json
import math
import os
import re
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "checks"))
import reportdata as RD  # noqa: E402

# Facts read off the source code (src/cg.cpp, src/main.cpp), used in the text; change them with the code.
VECTORS = {"classic": 5, "pipelined": 8}          # x b r p q  /  x b r p w s z n
REDUCTIONS = {"classic": 2, "pipelined": 1}       # global reductions per iteration
# Memory streams per grid point and iteration, counted from the loops in src/kernels.cpp and src/cg_impl.hpp: every
# vector a loop reads or writes counts once, and a vector the loop writes without reading it counts twice (the cache
# loads the line before it writes it). Their sum times 8 bytes must equal the plan's memory model (checked below).
STREAMS = {"classic": (("stencil", 3),    # stencil_box: read p, write q (+ the line load of q)
                       ("xr", 6),         # cg_update_xr: read x, p, r, q; write x, r
                       ("p", 3)),         # cg_update_p: read r, p; write p
           "pipelined": (("stencil", 3),  # stencil_box: read w, write n (+ the line load of n)
                         ("upd", 13))}    # pcg_update: read n, z, w, s, r, p, x; write z, s, p, x, r, w
# floating-point operations per grid point and iteration of classic CG, from the same loops:
# stencil 2D 5 (+2 for the dot product), 3D 7 (+2); cg_update_xr 6; cg_update_p 2
FLOPS_CLASSIC = {2: 7 + 6 + 2, 3: 9 + 6 + 2}
# graph operator (src/graph/dcsr.hpp): per row an int64 row pointer and a double degree, per off-diagonal entry an
# int32 column index (every off-diagonal value is -1 and is not stored)
GRAPH_BYTES_ROW, GRAPH_BYTES_NNZ = 16, 4
# public specifications (not measurements), cited in the report:
#   Intel Xeon Platinum 8452Y, intel.com product page (SKU 231761): 36 cores, 67.5 MB cache, 8 memory channels,
#   DDR5 up to 4800 MT/s at one DIMM per channel; peak = channels x 8 bytes x transfer rate
#   NVIDIA A40 datasheet (images.nvidia.com/content/Solutions/data-center/a40/nvidia-a40-datasheet.pdf):
#   48 GB GDDR6, 696 GB/s
SPEC = {"cpu.channels": 8, "cpu.memtype": "DDR5", "cpu.mts": 4800, "cpu.cache_mb": 67.5, "gpu.name": "A40", "gpu.mem_gb": 48,
        "gpu.bw_gbs": 696}
# validate.py, case V5: the pipelined run's true residual must be at most this many times the tolerance
V5_TRUE_FACTOR = 10
# runs at least this long (minutes) are the evidence for the timing noise of the long runs solved only once
LONG_RUN_MIN = 5
# the spread between repeats above which a configuration is counted as noisy (per cent)
REP_THRESHOLD_PCT = 5
# the report's words for the two halo exchanges (the records say "blocking" and "overlap")
HALO_WORD = {"blocking": "blocking", "overlap": "non-blocking"}
APPENDIX_FILES = ["src/par.hpp", "src/grid.hpp", "src/grid.cpp", "src/kernels.hpp", "src/kernels.cpp",
                  "src/halo.hpp", "src/halo.cpp", "src/cg.hpp", "src/cg.cpp", "src/record.hpp", "src/record.cpp",
                  "src/main.cpp", "src/cg_impl.hpp", "src/graph/csrfile.hpp", "src/graph/dcsr.hpp",
                  "src/graph/dcsr.cpp", "src/graph/label.hpp", "src/graph/label.cpp", "src/graph/graph_main.cpp",
                  "src/graph/convert.cpp", "CMakeLists.txt", "scripts/build.sh", "scripts/fetch_snap.sh",
                  "scripts/convert_snap.sh", "cluster/vanda/env.sh", "checks/validate.py", "checks/validate_graph.py",
                  "README.md"]

V, STATUS = {}, {"values": {}, "tables": {}, "figures": {}}


# ---------------------------------------------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------------------------------------------
def grp(n):
    return "{:,}".format(int(n)).replace(",", "{,}")


def fx(x, d=2):
    return "{:,.{d}f}".format(x, d=d).replace(",", "{,}")


def sci(x, d=1):
    if x == 0:
        return "$0$"
    e = int(math.floor(math.log10(abs(x))))
    m = x / 10 ** e
    if round(m, d) >= 10:
        m, e = m / 10, e + 1
    if e == 0:  # 1.1, not 1.1 x 10^0
        return "$%.*f$" % (d, m)
    return "$%.*f\\times10^{%d}$" % (d, m, e)


def sig(x, s=3):
    """s significant figures, plain notation for 1e-3 <= x < 1e5."""
    if x == 0:
        return "0"
    if not 1e-3 <= abs(x) < 1e5:
        return sci(x, s - 1)
    d = max(0, s - 1 - int(math.floor(math.log10(abs(x)))))
    return fx(x, d)


def put(key, val, reqs=(), filled=True, waiting=""):
    V[key] = str(val) if filled else "\\pending{%s}" % key
    STATUS["values"][key] = {"filled": bool(filled), "reqs": list(reqs), "waiting_for": waiting}


def pend(key, reqs, waiting):
    put(key, "", reqs, False, waiting)


def listing(xs, last="and"):
    xs = [str(x) for x in xs]
    return ", ".join(xs[:-1]) + " %s %s" % (last, xs[-1]) if len(xs) > 1 else xs[0]


def table(out, name, header, rows, spec, reqs, filled=True, waiting="", partial=False):
    """partial=True: the recorded rows, then one row saying what is still waiting; the table counts as waiting."""
    path = os.path.join(out, "tab_%s.tex" % name)
    with open(path, "w") as f:
        f.write("%% generated by scripts/report_macros.py; do not edit\n")
        f.write("\\begin{tabular}{%s}\n\\toprule\n" % spec)
        f.write(" & ".join(header) + " \\\\\n\\midrule\n")
        if filled or partial:
            for r in rows:
                f.write((" & ".join(str(x) for x in r) if isinstance(r, (list, tuple)) else r) + " \\\\\n")
        if partial:
            filled = False
            f.write("\\multicolumn{%d}{c}{\\pendingrow{%s}} \\\\\n" % (len(header), waiting.replace("_", "\\_")))
        elif not filled:
            f.write("\\multicolumn{%d}{c}{\\pendingrow{%s}} \\\\\n" % (len(header), waiting.replace("_", "\\_")))
        f.write("\\bottomrule\n\\end{tabular}\n")
    STATUS["tables"][name] = {"filled": bool(filled), "reqs": list(reqs), "waiting_for": waiting}


# ---------------------------------------------------------------------------------------------------------------
# geometry (MPI_Dims_create emulation, for the communication-volume table)
# ---------------------------------------------------------------------------------------------------------------
def dims_create(P, d):
    best = None

    def rec(rem, k, acc):
        nonlocal best
        if k == 1:
            cand = sorted(acc + [rem], reverse=True)
            key = (max(cand) - min(cand), cand)
            if best is None or key < best:
                best = key
            return
        for f in range(1, rem + 1):
            if rem % f == 0:
                rec(rem // f, k - 1, acc + [f])
    rec(P, d, [])
    return best[1]


def geometry(n, d, P, split):
    """Largest local box, halo values per exchange, messages per exchange for one interior rank."""
    pd = dims_create(P, split) + [1] * (d - split)
    loc = [-(-n // p) for p in pd]
    vol = 1
    for x in loc:
        vol *= x
    halo, msgs = 0, 0
    for a in range(d):
        if pd[a] > 1:
            face = vol // loc[a]
            halo += 2 * face
            msgs += 2
    return pd, vol, halo, msgs


# ---------------------------------------------------------------------------------------------------------------
def nodes_phrase(n):
    return "one node" if n == 1 else "%s nodes" % n


def design_values(out, results):
    """Design values. Those that describe the scaling runs follow the cluster chosen for them (Vanda when its runs
    are complete, else Atlas), so the text always describes the runs it reports."""
    Dsw = RD.choose(results, ["strong", "weak"])
    Dlay = RD.choose(results, ["layout"])
    P = Dsw.plan
    A = RD.load_plan("atlas")
    put("iters", P["fixed_iters"])
    put("repeats", P["repeats"])
    # spread between the repeats of a run: (largest - smallest) / median, over every recorded cell with all repeats
    spreads, longs, serial1s = [], [], []
    for cid, rs in Dsw.cell_rows.items():
        c = P["cells"].get(cid, {})
        ts = [float(r["t_solve" if "dataset" in c else "t_total"]) for r in rs]
        if len(ts) >= 3:
            m = statistics.median(ts)
            spreads.append((max(ts) - min(ts)) / m)
            if m >= 60 * LONG_RUN_MIN:
                longs.append((max(ts) - min(ts)) / m)
            if c.get("ranks", 0) * c.get("threads", 1) == 1 and m >= 1.0:  # one-core runs of a second or more
                serial1s.append((max(ts) - min(ts)) / m)
    put("rep.thr", "%d\\,\\%%" % REP_THRESHOLD_PCT)
    if spreads:
        put("rep.cells", len(spreads))
        put("rep.median", fx(100 * statistics.median(spreads), 1) + "\\,\\%")
        put("rep.nthr", sum(1 for x in spreads if x > REP_THRESHOLD_PCT / 100.0))
    else:
        for k in ("rep.cells", "rep.median", "rep.nthr"):
            pend(k, [], "timed runs")
    if serial1s:
        put("rep.serial.max1s", fx(100 * max(serial1s), 0) + "\\,\\%")
    else:
        pend("rep.serial.max1s", [], "one-core runs")
    put("rep.long.min", LONG_RUN_MIN)
    if longs:
        put("rep.long.n", len(longs))
        put("rep.long.max", fx(100 * max(longs), 1) + "\\,\\%")
    else:
        pend("rep.long.n", [], "runs of more than %d minutes with all repeats" % LONG_RUN_MIN)
        pend("rep.long.max", [], "runs of more than %d minutes with all repeats" % LONG_RUN_MIN)
    put("cpn", P["cores_per_node"])
    counts = sorted(set(c["ranks"] for c in (P["cells"][x] for x in P["groups"]["strong"]["cells"])))
    put("rankcounts", listing(counts))
    put("topcores", counts[-1])
    put("topnodes", counts[-1] // P["cores_per_node"])
    tn = -(-counts[-1] // P["cores_per_node"])
    # the whole nodes the recorded strong and weak runs used (the plan's count until rows exist); a shared-node run
    # is described separately (spread.sent)
    fv = Dsw.filled_view()
    whole = [c for g in ("strong", "weak") for cid, c in fv.cells(g) if not c.get("placement")]
    cpn0 = P["cores_per_node"]
    if whole and max(c["ranks"] for c in whole) >= counts[-1]:
        put("scale.where", "They use up to %s whole nodes of %d cores, %d cores in all." % (tn, cpn0, counts[-1]))
    elif whole:
        wn, wp = max(c["nodes"] for c in whole), max(c["ranks"] for c in whole)
        put("scale.where", "The experiments were designed for up to %d cores on %d whole nodes of %d cores, and on "
            "whole nodes the recorded runs reach %d cores on %s." % (counts[-1], tn, cpn0, wp, nodes_phrase(wn)))
    else:
        put("scale.where", "The experiments were designed for up to %d cores on %d whole nodes of %d cores." %
            (counts[-1], tn, cpn0))
    rec = sorted(set(c["ranks"] for cid, c in fv.cells("strong", dim=3, cg="classic", halo="blocking")))
    put("st.counts", listing(rec) if rec else listing(counts))
    L = Dlay.plan
    lnodes = sorted(set(L["cells"][x]["nodes"] for x in L["groups"]["layout"]["cells"]))
    lrec = sorted(set(c["nodes"] for cid, c in Dlay.filled_view().cells("layout")))
    if lrec:
        lnodes = lrec
    put("lay.cpn", L["cores_per_node"])
    put("lay.nodes", " and on ".join(nodes_phrase(n) for n in lnodes))
    put("lay.topnodes", lnodes[-1])
    put("lay.topnodes.phrase", nodes_phrase(lnodes[-1]))
    put("atlas.cpn", A["cores_per_node"])
    acounts = sorted(set(c["ranks"] for c in (A["cells"][x] for x in A["groups"]["strong"]["cells"])))
    put("atlas.topcores", acounts[-1])
    put("atlas.topnodes", -(-acounts[-1] // A["cores_per_node"]))
    import make_plan as MP
    for d in (2, 3):
        n = MP.STRONG[d]
        N = n ** d
        put("strong.n%d" % d, grp(n))
        put("strong.N%d" % d, grp(N))
        put("strong.Nsci%d" % d, sci(N, 1))
        put("strong.nnz%d" % d, grp(N + 2 * d * (n - 1) * n ** (d - 1)))
        put("weak.n%d" % d, grp(MP.WEAK_BASE[d]))
        put("weak.per%d" % d, grp(MP.WEAK_BASE[d] ** d))
        put("weak.top.n%d" % d, grp(MP.weak_n(d, counts[-1])))
        put("weak.top.N%d" % d, sci(MP.weak_n(d, counts[-1]) ** d, 1))
        put("serial.list%d" % d, listing(MP.SERIAL[d]))
        put("serialtol.list%d" % d, listing(MP.SERIAL_TOL[d]))
        put("strong.mem%d" % d, fx(VECTORS["pipelined"] * N * 8 / 1e9, 1))
    put("serial.Nmin", sci(min(min(n ** d for n in MP.SERIAL[d]) for d in (2, 3)), 1))
    put("serial.Nmax", sci(max(max(n ** d for n in MP.SERIAL[d]) for d in (2, 3)), 1))
    put("serialtol.tol", sci(MP.TOL, 0))
    put("slab.thick", fx(MP.STRONG[3] / float(counts[-1]), 1))
    put("slab.max", -(-MP.STRONG[3] // counts[-1]))
    put("scale.beyond", ", and beyond that the ranks of different nodes communicate over the network"
        if counts[-1] > P["cores_per_node"] else "")
    put("plan.vanda.cells", len(RD.load_plan("vanda")["cells"]))
    put("bytes.classic", P["model"]["bytes_per_point_iter"]["classic"])
    put("bytes.pipelined", P["model"]["bytes_per_point_iter"]["pipelined"])
    put("vec.classic", VECTORS["classic"])
    put("vec.pipelined", VECTORS["pipelined"])
    put("vec.extra", VECTORS["pipelined"] - VECTORS["classic"])
    put("plan.cells", len(P["cells"]))
    put("plan.jobs", len(P["jobs"]))
    lays = sorted(set((L["cells"][x]["ranks"] // L["cells"][x]["nodes"], L["cells"][x]["threads"])
                      for x in L["groups"]["layout"]["cells"]))
    put("plan.layouts", listing(["%d$\\times$%d" % l for l in lays]))
    vP = sorted(set(P["cells"][x]["ranks"] for x in P["groups"]["variants"]["cells"]))
    put("plan.variantsP", listing(vP))

    # communication volume per rank and iteration (from the geometry, no measurement)
    rows = []
    for d in (2, 3):
        n = MP.STRONG[d]
        for split, Pn in sorted(set(((1, counts[-1]), (d, P["cores_per_node"]), (d, counts[-1])))):
            pd, vol, halo, msgs = geometry(n, d, Pn, split)
            rows.append(["%dD" % d, "%dD" % split, grp(Pn), "$" + "\\times".join(str(x) for x in pd) + "$",
                         grp(vol), str(msgs), grp(halo), fx(100.0 * halo / vol, 2) + "\\,\\%"])
            if d == 3 and split == 1:
                put("geo.3d.slab.halo", grp(halo))
                put("geo.3d.slab.ratio", fx(100.0 * halo / vol, 1) + "\\,\\%")
            if d == 3 and split == 3 and Pn == counts[-1]:
                put("geo.3d.cube.halo", grp(halo))
                put("geo.3d.cube.ratio", fx(100.0 * halo / vol, 1) + "\\,\\%")
    table(out, "geometry", ["grid", "split", "ranks", "process grid", "points per rank", "messages",
                            "halo values", "halo / points"], rows, "llrlrrrr", ["E5", "E8"])

    # overview of the experiments (the cluster the report uses; what varies, the problem, the cores)
    V = RD.load_plan("vanda")
    import graph_plan as GP

    # the recorded configurations of each experiment once any exist (either placement), the design before that
    Vd = RD.data(results, "vanda")

    def recorded(g):
        cids = V["groups"].get(g, {}).get("cells", [])
        rec = [x for x in cids if x in Vd.cell_rows]
        return rec if rec else [x for x in cids if not V["cells"][x].get("placement")]

    def cores_of(g):
        cores = sorted(set(V["cells"][x]["ranks"] * V["cells"][x]["threads"] for x in recorded(g)))
        if not cores:
            return "--"
        return listing(cores, "and") if len(cores) <= 2 else "%s--%s" % (cores[0], cores[-1])

    def count(g):
        return grp(len(recorded(g)))

    def repeats_of(g):
        reps = collections.Counter(V["cells"][x].get("repeats", 1) for x in recorded(g))
        if not reps:
            return "--"
        main = reps.most_common(1)[0][0]
        rest = sorted((r, n) for r, n in reps.items() if r != main)
        return str(main) + "".join(" (%d for %d)" % (r, n) for r, n in rest)
    nm = lambda ds: listing([GP.DATASETS[d]["display"] for d in ds])  # noqa: E731
    exps = [
        ("serial, fixed iterations", "grid size", "2D $n=%s$--$%s$, 3D $n=%s$--$%s$" % (
            MP.SERIAL[2][0], MP.SERIAL[2][-1], MP.SERIAL[3][0], MP.SERIAL[3][-1]), "serial"),
        ("serial, to a tolerance", "grid size", "2D $n=%s$--$%s$, 3D $n=%s$--$%s$" % (
            MP.SERIAL_TOL[2][0], MP.SERIAL_TOL[2][-1], MP.SERIAL_TOL[3][0], MP.SERIAL_TOL[3][-1]), "serial-tol"),
        ("strong scaling", "cores, CG variant", "2D $n=%s$, 3D $n=%s$" % (MP.STRONG[2], MP.STRONG[3]), "strong"),
        ("weak scaling", "cores and grid together", "about %s unknowns per rank" % sci(MP.WEAK_BASE[2] ** 2, 1),
         "weak"),
        ("methods compared", "decomposition, halo exchange, CG variant", "strong-scaling grids", "variants"),
        ("ranks $\\times$ threads", "ranks and threads per node", "strong-scaling grids", "layout"),
        ("GPU", "number of GPUs", "strong-scaling grids", "gpu"),
        ("graph, serial", "graph, vertex order", nm(GP.ORDER), "graph-serial"),
        ("graph, strong scaling", "cores, CG variant", nm(GP.STRONG_DATASETS), "graph-strong"),
        ("graph, methods compared", "partition, ghost exchange, CG variant, ranks $\\times$ threads",
         nm(GP.STRONG_DATASETS), "graph-variants"),
        ("graph, labelling", "shift $a$, seeds $s$, edges kept", nm(GP.ORDER), "graph-sweep")]
    rows = []
    for name, varies, problem, g in exps:
        cores = cores_of(g) if g != "gpu" else "1 and 2 GPUs"
        rows.append([name, varies, problem, cores, count(g), repeats_of(g)])
    table(out, "plan", ["experiment", "what varies", "problem", "cores", "configurations", "solves"], rows,
          "lp{0.25\\linewidth}p{0.25\\linewidth}lrl", ["E2", "E3", "E4", "E6", "E7"])
    put("plan.atlas.cells", len(A["cells"]))


def validation_values(out):
    """From the latest qualification JSON, preferring a cluster's over the local one."""
    best = None
    for cl in ("vanda", "atlas", "local"):
        js = sorted(glob.glob(os.path.join(REPO, "results", "validation", cl, "*.json")))
        # the Poisson qualification only (validate_graph.py writes <stamp>-graph.json next to it)
        js = [j for j in js if not j.endswith("-graph.json") and json.load(open(j)).get("qualified")]
        if js:
            best = (cl, js[-1])
            break
    reqs = ["E9"]
    if best is None:
        for k in ("val.where",):
            pend(k, reqs, "a qualification run of checks/validate.py")
        return
    cl, path = best
    S = json.load(open(path))
    STATUS["validation_source"] = os.path.relpath(path, REPO)
    where = {"local": "a development laptop (Apple M5, Open MPI)", "vanda": "a Vanda compute node",
             "atlas": "an Atlas compute node"}[cl]
    put("val.where", where, reqs)
    put("val.cluster", cl, reqs)
    put("val.stamp", S["stamp"], reqs)
    put("val.sha", S["correct"]["sha256"][:12], reqs)
    put("val.ncases", len(S["cases"]), reqs)
    put("val.runs", S["correct"]["runs"], reqs)
    T = S["tolerances"]
    put("val.order.lo", fx(T["order_band"][0], 1), reqs)
    put("val.order.hi", fx(T["order_band"][1], 1), reqs)
    put("val.ordertol", sci(T["order_solve_tol"], 0), reqs)
    put("val.agree.iters", T["agree_iters"], reqs)
    put("val.agree.tol", sci(T["agree_tol"], 0), reqs)
    put("val.pipetol", sci(T["pipe_tol"], 0), reqs)
    put("val.pipe.truetol", sci(V5_TRUE_FACTOR * T["pipe_tol"], 0), reqs)
    det = S["correct"]["details"]
    # order cases
    rows = []
    for cid in ("V1", "V2"):
        items = det[cid]["items"]
        solves = [i for i in items if i["kind"] == "solve"]
        orders = [i for i in items if i["kind"] == "order"]
        for k, sv in enumerate(solves):
            o = fx(orders[k - 1]["order"], 3) if k > 0 else "--"
            rows.append(["%dD" % sv["dim"], grp(sv["n"]), "1/%d" % (sv["n"] + 1), grp(sv["iters"]),
                         sci(sv["err_max"], 2), o])
        put("val.order.%s" % cid, listing([fx(o["order"], 3) for o in orders]), reqs)
    table(out, "valorder", ["grid", "$n$", "$h$", "iterations", "max error", "observed order"], rows, "lrrrrr", reqs)
    # agreement
    rows, worst = [], {}
    for cid in ("V3", "V4"):
        for i in det[cid]["items"]:
            rows.append(["%dD" % i["dim"], grp(i["n"]), str(i["ranks"]), str(i["threads"]), "%dD" % i["decomp"],
                         HALO_WORD.get(i["halo"], i["halo"]), sci(i["diff"], 1)])
            worst[i["dim"]] = max(worst.get(i["dim"], 0), i["diff"])
    for d in (2, 3):
        put("val.agree.max%d" % d, sci(worst[d], 1), reqs)
    put("val.agree.max", sci(max(worst.values()), 1), reqs)
    put("val.agree.margin", grp(10 ** int(math.floor(math.log10(T["agree_tol"] / max(worst.values()))))), reqs)
    table(out, "valagree", ["grid", "$n$", "ranks", "threads", "decomposition", "halo exchange", "difference"], rows,
          "lrrrlll", reqs)
    # pipelined
    rows, diffs, bounds = [], [], []
    for i in det["V5"]["items"]:
        rows.append(["%dD" % i["dim"], grp(i["n"]), str(i["ranks"]), HALO_WORD.get(i["halo"], i["halo"]),
                     grp(i["iters_classic"]),
                     grp(i["iters_pipelined"]), sci(i["rho_s"], 1), sci(i["rho_p"], 1), sci(i["diff"], 1),
                     sci(i["bound"], 1)])
        diffs.append(i["diff"])
        bounds.append(i["bound"])
        put("val.cond.%d" % i["dim"], grp(round(i["cond"])), reqs)
    gap = max(abs(i["iters_pipelined"] - i["iters_classic"]) for i in det["V5"]["items"])
    put("val.pipe.iters", "the same number of iterations as classic CG" if gap == 0 else
        "at most %d iteration%s more or fewer than classic CG" % (gap, "" if gap == 1 else "s"), reqs)
    put("val.pipe.maxdiff", sci(max(diffs), 1), reqs)
    put("val.pipe.minbound", sci(min(bounds), 1), reqs)
    table(out, "valpipe", ["grid", "$n$", "ranks", "halo exchange", "it.\\ classic", "it.\\ pipel.", "$\\rho_s$",
                           "$\\rho_p$", "difference", "bound"], rows, "lrrlrrrrrr", reqs)
    # planted bugs
    rows, bd = [], []
    names = {"1": "one received face is dropped", "2": "the wrong plane is sent on one face"}
    for b in S["bugs"]:
        m = re.search(r"bug=(\d)", b["build"])
        k = m.group(1) if m else "?"
        diffs = [i["diff"] for c in ("V3", "V4") for i in b["details"].get(c, {}).get("items", [])]
        bd += diffs
        verdict = []
        for cid in ("V1", "V2", "V3", "V4", "V5"):
            verdict.append("passes" if b["details"].get(cid, {}).get("ok") else "\\textbf{fails}")
        rows.append([names.get(k, k)] + verdict)
    put("val.bug.min", fx(min(bd), 2) if bd else "--", reqs)
    put("val.bug.max", fx(max(bd), 2) if bd else "--", reqs)
    put("val.bug.n", len(S["bugs"]), reqs)
    table(out, "valbugs", ["broken halo exchange", "V1", "V2", "V3", "V4", "V5"], rows, "lccccc", reqs)
    # accuracy floor (information, not a case)
    I = S.get("info") or {}
    if I.get("classic") and I.get("pipelined"):
        put("val.floor.tol", sci(I["tol"], 0), reqs)
        put("val.floor.maxit", grp(I["maxit"]), reqs)
        put("val.floor.n", I["n"], reqs)
        put("val.floor.ranks", I["ranks"], reqs)
        for cg in ("classic", "pipelined"):
            R = I[cg]
            if R["converged"]:
                verdict = ("reached it in %s iterations, with a true residual of %s" %
                           (grp(R["iters"]), sci(R["true_rel_res"], 1)))
            else:
                verdict = ("did not reach it in %s iterations: its recursive residual stopped falling at %s while its "
                           "true residual stayed at %s" % (grp(R["iters"]), sci(R["rel_res"], 1),
                                                           sci(R["true_rel_res"], 1)))
            put("val.floor.%s.verdict" % cg, verdict, reqs)
            put("val.floor.%s.iters" % cg, grp(I[cg]["iters"]), reqs)
            put("val.floor.%s.rec" % cg, sci(I[cg]["rel_res"], 1), reqs)
            put("val.floor.%s.true" % cg, sci(I[cg]["true_rel_res"], 1), reqs)
    # case table
    # what each test checks, in the report's words (the validation output carries the program's own wording)
    text = {"V1": "2D, one process: the solver converges, and its error against the exact solution falls as $h^2$",
            "V2": "3D, one process: as V1",
            "V3": "2D, several processes (1D and 2D decompositions, uneven blocks, blocking and non-blocking halo "
                  "exchange, two threads per rank): the iterate equals the one-process iterate to rounding",
            "V4": "3D, several processes: as V3, with 1D, 2D and 3D decompositions",
            "V5": "pipelined CG on one and four processes reaches the same converged answer as classic CG, 2D and 3D"}
    rows = [[c["id"], text.get(c["id"], c["purpose"])] for c in S["cases"]]
    table(out, "cases", ["test", "what it checks"], rows, "lp{0.82\\linewidth}", reqs)


def cluster_values(out, results, figures):
    Dser = RD.choose(results, ["serial"])
    Dtol = RD.choose(results, ["serial-tol"])
    Dsw = RD.choose(results, ["strong", "weak"])
    Dvar = RD.choose(results, ["variants"])
    Dlay = RD.choose(results, ["layout"])
    G = RD.gpu_data(results)
    NM = RD.NAMES
    # which cluster each part of the report uses (a choice that exists before any run; filled either way)
    for key, d in (("serial", Dser), ("serialtol", Dtol), ("strong", Dsw), ("variants", Dvar), ("layout", Dlay)):
        put("cl.%s" % key, NM[d.cluster])
    put("cl.name", NM[Dsw.cluster])
    put("cl.gpu", NM[G.cluster])
    chosen = [Dser, Dtol, Dsw, Dvar, Dlay, G]
    used = []
    for d in chosen:
        if d.rows and d.cluster not in used:
            used.append(d.cluster)
    put("cl.used", " and ".join(NM[c] for c in used) if used else NM[Dsw.cluster])
    put("env.serialnote", " The serial sweep ran in Atlas's serial queue, on one core of a node that other jobs may "
        "have shared, so its times can include some competition for memory bandwidth." if Dser.cluster == "atlas"
        else "", ["E2", "E10"])
    D = Dsw
    name = NM[Dsw.cluster]

    def wait(*groups):
        w = D.waiting(*groups)
        return "; ".join(w) if w else ""

    # ---- the machine: processor, sockets, memory, compilers (from the batch jobs' environment records)
    reqs = ["E10"]
    jobs = set()
    envs = []
    for c in used:
        d = RD.data(results, c)
        jobs |= set((c, r["pbs_jobid"]) for r in d.rows)
        envs += [json.load(open(e)) for e in sorted(glob.glob(os.path.join(results, c, "env", "*.json")))
                 if not os.path.basename(e).startswith("discover")]
    cpu_envs = [e for e in envs if "nvc++" not in (e.get("cxx") or "")]
    gpu_envs = [e for e in envs if "nvc++" in (e.get("cxx") or "")]
    why = "%s job environment records" % name

    def one(es, f):
        vals = sorted(set(f(e) for e in es if f(e)))
        return vals[0] if len(vals) == 1 else None

    def ver(text, word):  # "g++ (GCC) 14.3.0" -> "14.3.0"; "mpirun (Open MPI) 5.0.8" -> "5.0.8"
        m = re.search(r"%s\S*\s+([0-9][0-9A-Za-z.\-]*)" % re.escape(word), text or "")
        return m.group(1) if m else None
    # (processor, sockets and cores per socket are node.cpu, node.sockets and node.cps, set below)
    facts = {
        "env.mem": one(cpu_envs, lambda e: e.get("mem_total_gb") and fx(e["mem_total_gb"], 0)),
        "env.cxx": one(cpu_envs, lambda e: ver(e.get("cxx"), "(GCC)")),
        "env.mpi": one(cpu_envs, lambda e: ver(e.get("mpirun"), "MPI)")),
        "env.gpu.cxx": one(gpu_envs, lambda e: ver(e.get("cxx"), "nvc++")),
        "env.gpu.mpi": one(gpu_envs, lambda e: ver(e.get("mpirun"), "MPI)")),
        # the GPU nodes' common name prefix (e.g. GN-A40-027, GN-A40-032 -> GN-A40), which names the GPU model
        "env.gpu.node": one(gpu_envs, lambda e: e.get("host") and e["host"].rsplit("-", 1)[0])}
    sock = one(cpu_envs, lambda e: e.get("sockets"))
    mem = one(cpu_envs, lambda e: e.get("mem_total_gb"))
    facts["env.mempersock"] = fx(mem / sock, 0) if mem and sock else None
    gl = RD.load_plan("vanda").get("limits", {}).get("gpu", {})
    facts["env.gpus"] = gl.get("max_gpus")
    for k, v in facts.items():
        if v is None or v == "":
            pend(k, reqs, why)
        else:
            put(k, v, reqs)
    if jobs:
        put("env.jobs", len(jobs), reqs)
    else:
        pend("env.jobs", reqs, why)

    # ---- validation of the binaries that produced the cluster rows
    shas = sorted(set(r["binary_sha256"] for d in chosen for r in d.rows))
    if shas:
        put("val.cl.sha", ", ".join(s[:12] for s in shas), ["E9"])
    else:
        pend("val.cl.sha", ["E9"], "the %s validation job (vanda-validate) and timed runs" % name)

    # ---- serial (E2): from the cluster with the complete serial sweep
    D = Dser
    reqs = ["E2"]
    if D.complete("serial"):
        rows, fits = [], {}
        for d in (2, 3):
            pts = []
            for cid, c in sorted(D.cells("serial", dim=d), key=lambda t: t[1]["n"]):
                r = D.row0(cid)
                N, nnz, t = int(r["unknowns"]), int(r["nonzeros"]), D.med(cid)
                pts.append((N, nnz, t))
                it = float(r["iters"])
                rows.append(["%dD" % d, grp(c["n"]), grp(N), grp(nnz), sig(t, 3), fx(1e9 * t / (it * N), 2),
                             fx(1e9 * t / (it * nnz), 2)])
            xs = [math.log(p[0]) for p in pts]
            ys = [math.log(p[2]) for p in pts]
            fits[d] = slope(xs, ys)
            big = pts[-1]
            put("ser.ns%d" % d, fx(1e9 * big[2] / (D.plan["fixed_iters"] * big[0]), 2), reqs)
            put("ser.nsnnz%d" % d, fx(1e9 * big[2] / (D.plan["fixed_iters"] * big[1]), 2), reqs)
            put("ser.slope%d" % d, fx(fits[d], 2), reqs)
            put("ser.nsizes%d" % d, len(pts), reqs)
            for cid, c in D.cells("serial", dim=d):
                # the four vectors one iteration of classic CG touches (x, r, p, q), in MB
                put("ser.ws.%d.n%d" % (d, c["n"]), fx(4 * 8 * int(D.row0(cid)["unknowns"]) / 1e6, 1), reqs)
        table(out, "serial", ["grid", "$n$", "unknowns $N$", "nonzeros", "time (s)", "ns per unknown",
                              "ns per nonzero"], rows, "lrrrrrr", reqs)
    else:
        w = wait("serial")
        for d in (2, 3):
            for k in ("ser.ns%d", "ser.nsnnz%d", "ser.slope%d"):
                pend(k % d, reqs, w)
        table(out, "serial", ["grid", "$n$", "unknowns $N$", "nonzeros", "time (s)", "ns per unknown",
                              "ns per nonzero"], [], "lrrrrrr", reqs, False, w)
    D = Dtol
    if D.complete("serial-tol"):
        for d in (2, 3):
            pts = sorted((c["n"], int(D.row0(cid)["iters"])) for cid, c in D.cells("serial-tol", dim=d))
            put("ser.itslope%d" % d, fx(slope([math.log(p[0] + 1) for p in pts], [math.log(p[1]) for p in pts]), 2),
                reqs)
            tp = sorted((int(D.row0(cid)["unknowns"]), D.med(cid)) for cid, c in D.cells("serial-tol", dim=d))
            put("ser.tslope%d" % d, fx(slope([math.log(p[0]) for p in tp], [math.log(p[1]) for p in tp]), 2), reqs)
            put("ser.tslope.pred%d" % d, fx(1 + 1.0 / d, 2), reqs)
            # the cost per unknown and iteration of these runs, as a power of N
            cp = sorted((int(D.row0(cid)["unknowns"]), D.med(cid) / (int(D.row0(cid)["iters"]) *
                                                                       int(D.row0(cid)["unknowns"])))
                        for cid, c in D.cells("serial-tol", dim=d))
            put("ser.tcslope%d" % d, fx(slope([math.log(p[0]) for p in cp], [math.log(p[1]) for p in cp]), 2), reqs)
    else:
        for d in (2, 3):
            pend("ser.itslope%d" % d, reqs, wait("serial-tol"))
            pend("ser.tslope%d" % d, reqs, wait("serial-tol"))
            pend("ser.tcslope%d" % d, reqs, wait("serial-tol"))
            put("ser.tslope.pred%d" % d, fx(1 + 1.0 / d, 2), reqs)

    # ---- strong / weak (E3, E4): one cluster for both, one build per series, 1-core baseline from that series
    D = Dsw
    for group, reqs in (("strong", ["E3"]), ("weak", ["E4"])):
        mixed = None
        try:
            for d in (2, 3):
                for v in (("classic", "blocking"), ("pipelined", "overlap")):
                    D.check_same_build([cid for cid, c in D.cells(group, dim=d, cg=v[0], halo=v[1])],
                                       "%s %dD %s/%s" % (group, d, v[0], v[1]))
        except RD.MixedBuild as e:
            mixed = str(e)
        if D.complete(group) and not mixed:
            Dr = D.filled_view()  # complete may mean: a run or its shared-node insurance run is recorded
            for d in (2, 3):
                rows = []
                series = {}
                for v in (("classic", "blocking"), ("pipelined", "overlap")):
                    cs = sorted(Dr.cells(group, dim=d, cg=v[0], halo=v[1]), key=lambda t: t[1]["ranks"])
                    series[v] = [(c["ranks"], Dr.med(cid)) for cid, c in cs]
                shared = set(c["ranks"] for cid, c in Dr.cells(group, dim=d) if c.get("placement"))
                for i, (p, _) in enumerate(series[("classic", "blocking")]):
                    row = [grp(p) + ("$^{\\dagger}$" if p in shared else "")]
                    for v in series:
                        t1, tp = series[v][0][1], series[v][i][1]
                        S = t1 / tp
                        E = S / p if group == "strong" else t1 / tp
                        row += [sig(tp, 3)] + ([fx(S, 1)] if group == "strong" else []) + [fx(E, 2)]
                    rows.append(row)
                for v, tag in ((("classic", "blocking"), "classic"), (("pipelined", "overlap"), "pipelined")):
                    t1, (ptop, ttop) = series[v][0][1], series[v][-1]
                    t72 = dict(series[v]).get(D.plan["cores_per_node"])
                    key = "%s.%d.%s" % ({"strong": "st", "weak": "wk"}[group], d, tag)
                    put(key + ".Ttop", sig(ttop, 3), reqs)
                    put(key + ".T1", sig(t1, 3), reqs)
                    if group == "strong":
                        put(key + ".Stop", fx(t1 / ttop, 1), reqs)
                        put(key + ".Etop", fx(t1 / (ptop * ttop), 2), reqs)
                        if t72:
                            put(key + ".Enode", fx(t1 / (D.plan["cores_per_node"] * t72), 2), reqs)
                    else:
                        put(key + ".Etop", fx(t1 / ttop, 2), reqs)
                        if t72:
                            put(key + ".Enode", fx(t1 / t72, 2), reqs)
                if group == "strong":
                    hd = ["cores", "classic T (s)", "$S$", "$E$", "pipelined T (s)", "$S$", "$E$"]
                    spec = "rrrrrrr"
                else:
                    hd = ["cores", "classic T (s)", "$E$", "pipelined T (s)", "$E$"]
                    spec = "rrrrr"
                table(out, "%s%d" % (group, d), hd, rows, spec, reqs)
        else:
            w = mixed or wait(group)
            Dv = D.filled_view()
            for d in (2, 3):
                for tag in ("classic", "pipelined"):
                    key = "%s.%d.%s" % ({"strong": "st", "weak": "wk"}[group], d, tag)
                    for s in (("Ttop", "T1", "Stop", "Etop", "Enode") if group == "strong" else
                              ("Ttop", "T1", "Etop", "Enode")):
                        pend(key + "." + s, reqs, w)
                if group == "strong":
                    hd, spec = ["cores", "classic T (s)", "$S$", "$E$", "pipelined T (s)", "$S$", "$E$"], "rrrrrrr"
                else:
                    hd, spec = ["cores", "classic T (s)", "$E$", "pipelined T (s)", "$E$"], "rrrrr"
                # the rows recorded so far, then a row saying what is missing (a partial table still waits)
                rows = []
                if not mixed:
                    series = {}
                    for v in (("classic", "blocking"), ("pipelined", "overlap")):
                        cs = sorted(Dv.cells(group, dim=d, cg=v[0], halo=v[1]), key=lambda t: t[1]["ranks"])
                        series[v] = dict((c["ranks"], Dv.med(cid)) for cid, c in cs)
                    common = sorted(set(series[("classic", "blocking")]) & set(series[("pipelined", "overlap")]))
                    if common and common[0] == 1:
                        for p in common:
                            row = [grp(p)]
                            for v in series:
                                t1, tp = series[v][1], series[v][p]
                                row += [sig(tp, 3)] + ([fx(t1 / tp, 1)] if group == "strong" else []) + \
                                    [fx(t1 / (p * tp) if group == "strong" else t1 / tp, 2)]
                            rows.append(row)
                table(out, "%s%d" % (group, d), hd, rows, spec, reqs, False, w, partial=bool(rows))

    # ---- the largest core count actually recorded, and where it ran (whole nodes, or the shared-node insurance job)
    def where(c):
        if not c.get("placement"):
            return ""
        nodes, per = c["nodes"], c["ranks"] // c["nodes"]
        return " (%d nodes $\\times$ %d cores, on nodes shared with other jobs)" % (nodes, per)
    # the shared-node points: said once in the text and keyed in the captions, only if such rows exist
    shared = [c for cid, c in Dsw.filled_view().cells("strong") if c.get("placement")] + \
        [c for cid, c in Dsw.filled_view().cells("weak") if c.get("placement")]
    if shared:
        c0 = shared[0]
        top_planned = max(c["ranks"] for cid, c in Dsw.cells("strong") if not c.get("placement"))
        tn = -(-top_planned // Dsw.plan["cores_per_node"])
        whole_top = any(c["ranks"] >= top_planned and not c.get("placement")
                        for cid, c in Dsw.filled_view().cells("strong"))
        put("spread.sent", " The points at %d cores marked by hollow diamonds come from %s run on %d nodes $\\times$ %d "
            "cores that shared its nodes with other jobs, with ranks not bound to cores, made %s. Other jobs' use of "
            "memory bandwidth and the unbound ranks can make these times longer and noisier than on whole nodes." %
            (c0["ranks"], "an additional" if whole_top else "a", c0["nodes"], c0["ranks"] // c0["nodes"],
             "while %d whole nodes were not yet available" % tn if whole_top else
             "because %d whole nodes were not available in time" % tn), ["E3", "E4"])
        put("spread.cap", " Hollow diamonds: %d nodes $\\times$ %d cores on nodes shared with other jobs, against the "
            "same one-core time." % (c0["nodes"], c0["ranks"] // c0["nodes"]), ["E3", "E4"])
        put("spread.tabnote", " A dagger marks the run on nodes shared with other jobs.", ["E3", "E4"])
        put("spread.except", " The one exception is the run at %d cores on nodes shared with other jobs, described in "
            "Section~\\ref{sec:mpi}." % c0["ranks"], ["E3", "E4"])
    else:
        for k in ("spread.sent", "spread.cap", "spread.tabnote", "spread.except"):
            put(k, "", ["E3", "E4"])
    top = Dsw.top_cells("strong", dim=3, cg="classic", halo="blocking")
    if Dsw.complete("strong", "weak") and top:
        tc = top[0][1]
        put("meas.top", tc["ranks"] * tc["threads"], ["E3", "E4"])
        put("meas.where", where(tc), ["E3", "E4"])
        both = [c for cid, c in Dsw.filled_view().cells("strong", dim=3, cg="classic", halo="blocking")
                if c["ranks"] >= 256]
        sp = [c for c in both if c.get("placement")]
        if sp and not tc.get("placement"):  # whole-node top recorded and the insurance run too: name both
            spc = [(cid, c) for cid, c in Dsw.cells("strong", dim=3, cg="classic", halo="blocking")
                   if c.get("placement") and cid in Dsw.cell_rows][0]
            one = [cid for cid, c in Dsw.cells("strong", dim=3, cg="classic", halo="blocking") if c["ranks"] == 1][0]
            put("meas.both", " The %d-core run%s reached a 3D classic efficiency of %s." % (
                spc[1]["ranks"], where(spc[1]), fx(Dsw.med(one) / (spc[1]["ranks"] * Dsw.med(spc[0])), 2)),
                ["E3"])
        else:
            put("meas.both", "", ["E3"])
        wt = {}
        for d in (2, 3):
            t = Dsw.top_cells("weak", dim=d, cg="classic", halo="blocking")
            wt[d] = t[0][1]["n"] if t else None
        put("wk.top.n2", grp(wt[2]) if wt[2] else "--", ["E4"])
        put("wk.top.n3", grp(wt[3]) if wt[3] else "--", ["E4"])
    else:
        w = wait("strong", "weak")
        for k, r in (("meas.top", ["E3", "E4"]), ("meas.where", ["E3", "E4"]), ("meas.both", ["E3"]),
                     ("wk.top.n2", ["E4"]), ("wk.top.n3", ["E4"])):
            pend(k, r, w)

    # ---- E3/E4 are met only at >= 256 cores (from either placement); a complete Atlas fallback says so
    STATUS["requirements"] = {}
    for rid, g in (("E3", "strong"), ("E4", "weak")):
        mc = Dsw.max_cores(g, recorded=True)
        if not Dsw.complete(g):
            STATUS["requirements"][rid] = {"filled": False, "kind": "waiting",
                                           "waiting_for": "; ".join(Dsw.waiting(g))}
        elif mc < 256:
            STATUS["requirements"][rid] = {"filled": False, "kind": "not_met", "waiting_for": (
                "%s scaling reached only %d cores (%s); at least 256 cores need Vanda" % (g, mc, NM[Dsw.cluster]))}
        else:
            STATUS["requirements"][rid] = {"filled": True, "kind": "met", "waiting_for": ""}
    mc = min(Dsw.max_cores("strong", recorded=True), Dsw.max_cores("weak", recorded=True))
    if Dsw.complete("strong", "weak"):
        put("scale.note", "" if mc >= 256 else (
            " These runs reach only %d cores, on %s, the most one user may use there; the runs on at least 256 "
            "cores need Vanda and are not in this report, so that requirement of the project is not met." %
            (mc, NM[Dsw.cluster])), ["E3", "E4"])
        put("scale.maxcores", mc, ["E3", "E4"])
    else:
        pend("scale.note", ["E3", "E4"], wait("strong", "weak"))
        pend("scale.maxcores", ["E3", "E4"], wait("strong", "weak"))

    # ---- communication split (E5), from the strong classic/blocking series
    D = Dsw
    reqs = ["E5"]
    cpn = D.plan["cores_per_node"]
    if D.complete("strong"):
        rows = []
        D = D.filled_view()  # the largest recorded count, whole nodes or the shared-node insurance run
        for d in (2, 3):
            cs = sorted(D.cells("strong", dim=d, cg="classic", halo="blocking"), key=lambda t: t[1]["ranks"])
            top = cs[-1][1]["ranks"]
            for cid, c in cs:
                if c["ranks"] not in (cpn, top):
                    continue
                r = D.row0(cid)
                it = float(r["iters"])
                tc, th, tr = (D.med(cid, k) for k in ("t_compute", "t_halo", "t_reduce"))
                tt = D.med(cid)
                rows.append(["%dD" % d, grp(c["ranks"]) + ("$^{\\dagger}$" if c.get("placement") else ""), fx(1e3 * tc / it, 3), fx(1e3 * th / it, 3),
                             fx(1e3 * tr / it, 3), fx(100 * (th + tr) / tt, 1) + "\\,\\%",
                             r["msgs_per_exch"], grp(int(r["doubles_per_exch_max"]))])
                if c["ranks"] == top:
                    put("cm.%d.halo" % d, fx(100 * th / tt, 1) + "\\,\\%", reqs)
                    put("cm.%d.red" % d, fx(100 * tr / tt, 1) + "\\,\\%", reqs)
                    put("cm.%d.comp" % d, fx(100 * tc / tt, 1) + "\\,\\%", reqs)
        table(out, "comm", ["grid", "cores", "computation", "halo exchange", "reductions", "communication share", "messages",
                            "halo values"], rows, "lrrrrrrr", reqs)
    else:
        w = wait("strong")
        for d in (2, 3):
            for k in ("halo", "red", "comp"):
                pend("cm.%d.%s" % (d, k), reqs, w)
        Dv = D.filled_view()
        rows = []
        for d in (2, 3):
            cs = sorted(Dv.cells("strong", dim=d, cg="classic", halo="blocking"), key=lambda t: t[1]["ranks"])
            for cid, c in cs:
                if c["ranks"] not in (cpn, 2 * cpn):
                    continue
                r = Dv.row0(cid)
                it = float(r["iters"])
                tc, th, tr = (Dv.med(cid, k) for k in ("t_compute", "t_halo", "t_reduce"))
                tt = Dv.med(cid)
                rows.append(["%dD" % d, grp(c["ranks"]), fx(1e3 * tc / it, 3), fx(1e3 * th / it, 3),
                             fx(1e3 * tr / it, 3), fx(100 * (th + tr) / tt, 1) + "\\,\\%",
                             r["msgs_per_exch"], grp(int(r["doubles_per_exch_max"]))])
        table(out, "comm", ["grid", "cores", "computation", "halo exchange", "reductions", "communication share", "messages",
                            "halo values"], rows, "lrrrrrrr", reqs, False, w, partial=bool(rows))

    # ---- variants (E5, E8)
    D = Dvar
    reqs = ["E5", "E8"]
    if D.complete("variants"):
        Ps = sorted(set(c["ranks"] for cid, c in D.cells("variants")))
        rows = []
        for d in (2, 3):
            best = {}
            for dc in range(1, d + 1):
                for cg in ("classic", "pipelined"):
                    for halo in ("blocking", "overlap"):
                        row = ["%dD" % d, "%dD" % dc, cg, HALO_WORD[halo]]
                        for p in Ps:
                            cs = D.cells("variants", dim=d, decomp=dc, cg=cg, halo=halo, ranks=p)
                            t = D.med(cs[0][0])
                            it = float(D.row0(cs[0][0])["iters"])
                            row.append(fx(1e3 * t / it, 3))
                            best.setdefault(p, []).append((t, dc, cg, halo))
                        rows.append(row)
            for p in Ps:
                b = sorted(best[p])
                t0 = b[0][0]
                for tag in (["node"] if p == Ps[0] else []) + (["top"] if p == Ps[-1] else []):
                    put("var.%d.%s.best" % (d, tag), "%dD decomposition with %s CG and %s halo exchange" %
                        (b[0][1], b[0][2], "blocking" if b[0][3] == "blocking" else "non-blocking"),
                        reqs)
                    put("var.%d.%s.spread" % (d, tag), fx(b[-1][0] / t0, 2), reqs)
        table(out, "variants", ["grid", "decomposition", "CG", "halo exchange"] + ["ms/it, %d cores" % p for p in Ps],
              rows,
              "llll" + "r" * len(Ps), reqs)
    else:
        w = wait("variants")
        for d in (2, 3):
            pend("var.%d.top.best" % d, reqs, w)
            pend("var.%d.top.spread" % d, reqs, w)
        # one node: if every one-node variant is recorded, its column and the node values are filled
        cells1 = [(cid, c) for cid, c in D.cells("variants") if c["ranks"] == cpn]
        if cells1 and all(cid in D.cell_rows for cid, c in cells1):
            rows = []
            for d in (2, 3):
                best = []
                for dc in range(1, d + 1):
                    for cg in ("classic", "pipelined"):
                        for halo in ("blocking", "overlap"):
                            cs = [cid for cid, c in cells1 if c["dim"] == d and c["decomp"] == dc and
                                  c["cg"] == cg and c["halo"] == halo]
                            t = D.med(cs[0])
                            it = float(D.row0(cs[0])["iters"])
                            rows.append(["%dD" % d, "%dD" % dc, cg, HALO_WORD[halo], fx(1e3 * t / it, 3)])
                            best.append((t, dc, cg, halo))
                best.sort()
                put("var.%d.node.best" % d, "%dD decomposition with %s CG and %s halo exchange" %
                    (best[0][1], best[0][2], "blocking" if best[0][3] == "blocking" else "non-blocking"), reqs)
                put("var.%d.node.spread" % d, fx(best[-1][0] / best[0][0], 2), reqs)
            table(out, "variants", ["grid", "decomposition", "CG", "halo exchange", "ms/it, %d cores" % cpn], rows,
                  "llllr", reqs,
                  False, w, partial=True)
        else:
            for d in (2, 3):
                pend("var.%d.node.best" % d, reqs, w)
                pend("var.%d.node.spread" % d, reqs, w)
            table(out, "variants", ["grid", "decomposition", "CG", "halo exchange", "ms/it"], [], "llllr", reqs, False,
                  w)

    # ---- layouts (E6)
    D = Dlay
    reqs = ["E6"]
    if D.complete("layout"):
        nodes = sorted(set(c["nodes"] for cid, c in D.cells("layout")))
        lays = sorted(set((c["ranks"] // c["nodes"], c["threads"]) for cid, c in D.cells("layout")))
        rows = []
        for (rpn, th) in lays:
            row = ["%d$\\times$%d" % (rpn, th)]
            for d in (2, 3):
                for nn in nodes:
                    cs = D.cells("layout", dim=d, nodes=nn, threads=th, ranks=rpn * nn)
                    row.append(sig(D.med(cs[0][0]), 3))
            rows.append(row)
        for d in (2, 3):
            for nn in nodes:
                ts = sorted((D.med(cid), c["ranks"] // nn, c["threads"]) for cid, c in
                            D.cells("layout", dim=d, nodes=nn))
                for tag in (["1"] if nn == 1 else []) + (["top"] if nn == nodes[-1] else []):
                    put("lay.%d.%s.best" % (d, tag), "%d$\\times$%d" % (ts[0][1], ts[0][2]), reqs)
                    put("lay.%d.%s.spread" % (d, tag), fx(ts[-1][0] / ts[0][0], 2), reqs)
        put("lay.top.sent", "; on %s they are %s and %s" % (nodes_phrase(nodes[-1]), V["lay.3.top.best"],
                                                            V["lay.2.top.best"]) if nodes[-1] > 1 else "", reqs)
        hd = ["ranks $\\times$ threads per node"] + ["%dD, %d node%s" % (d, nn, "s" if nn > 1 else "")
                                                     for d in (2, 3) for nn in nodes]
        table(out, "layout", hd, rows, "l" + "r" * (len(hd) - 1), reqs)
    else:
        w = wait("layout")
        for d in (2, 3):
            for tag in ("1", "top"):
                pend("lay.%d.%s.best" % (d, tag), reqs, w)
                pend("lay.%d.%s.spread" % (d, tag), reqs, w)
        pend("lay.top.sent", reqs, w)
        table(out, "layout", ["ranks $\\times$ threads per node", "time (s)"], [], "lr", reqs, False, w)

    # ---- GPU (E7): the 1-GPU cells (job vanda-gpu1) are enough for E7; the 2-GPU cells (vanda-gpu, which needs a
    # whole GPU node) are shown when they exist and do not hold E7 back (amendment gpu-split-2026-11-12)
    reqs = ["E7"]
    one = [(cid, c) for cid, c in G.cells("gpu") if c["gpus"] == 1]
    lay1 = [cid for cid, c in D.cells("layout") if c["nodes"] == 1]
    one_done = bool(one) and all(cid in G.cell_rows for cid, c in one)
    lay1_done = bool(lay1) and all(cid in D.cell_rows for cid in lay1)
    hd = ["grid", "GPUs", "GPU time (s)", "best 1-node CPU time (s)", "CPU node / GPU"]
    if one_done and lay1_done:
        rows = []
        for d in (2, 3):
            cpu_best = min(D.med(cid) for cid, c in D.cells("layout", dim=d, nodes=1))
            for cid, c in sorted(G.cells("gpu", dim=d), key=lambda t: t[1]["gpus"]):
                if cid not in G.cell_rows:  # a 2-GPU cell still waiting: say so in its row
                    rows.append("%dD & %d & \\multicolumn{3}{l}{\\pendingrow{a whole GPU node (job vanda-gpu)}}" %
                                (d, c["gpus"]))
                    continue
                t = G.med(cid)
                rows.append(["%dD" % d, str(c["gpus"]), sig(t, 3), sig(cpu_best, 3), fx(cpu_best / t, 2)])
                if c["gpus"] == 1:
                    put("gpu.%d.t" % d, sig(t, 3), reqs)
                    put("gpu.%d.vsnode" % d, fx(cpu_best / t, 2), reqs)
        table(out, "gpu", hd, rows, "lrrrr", reqs)
    else:
        w = "; ".join(([] if one_done else ["%s gpu: the 1-GPU runs (job vanda-gpu1)" % G.cluster]) +
                      ([] if lay1_done else D.waiting("layout")))
        for d in (2, 3):
            pend("gpu.%d.t" % d, reqs, w)
            pend("gpu.%d.vsnode" % d, reqs, w)
        table(out, "gpu", hd, [], "lrrrr", reqs, False, w)

    # ---- figure slots
    freqs = {"fig_serial": ["E2", "E10", "E14"], "fig_serial_tol": ["E2", "E10", "E14"],
             "fig_strong": ["E3", "E10", "E14"], "fig_weak": ["E4", "E10", "E14"],
             "fig_efficiency": ["E3", "E4", "E14"], "fig_comm": ["E5", "E10", "E14"],
             "fig_layout": ["E6", "E10", "E14"], "fig_graph_serial": ["E2", "E12", "E10", "E14"],
             "fig_graph_strong": ["E3", "E10", "E14"], "fig_graph_comm": ["E5", "E10", "E14"],
             "fig_graph_variants": ["E8", "E12", "E10", "E14"], "fig_graph_sweep": ["E11", "E12", "E10", "E14"]}
    lines = []
    for name, reqs in freqs.items():
        mp = os.path.join(figures, name + ".meta.json")
        pdf = os.path.join(figures, name + ".pdf")
        m = json.load(open(mp)) if os.path.exists(mp) else {"status": "missing",
                                                              "waiting_for": ["scripts/figures.py not run"]}
        filled = m.get("status") == "filled" and os.path.exists(pdf)
        partial = m.get("status") == "partial" and os.path.exists(pdf)
        msg = "" if filled else "; ".join(m.get("waiting_for", []))
        STATUS["figures"][name] = {"filled": filled, "partial": partial, "reqs": reqs, "waiting_for": msg,
                                   "meta": os.path.relpath(mp, REPO) if mp.startswith(REPO) else mp}
        lines.append("\\setslot{%s}{%d}{%s}" % (name, 1 if filled else 2 if partial else 0,
                                                  msg.replace("_", "\\_")))
    with open(os.path.join(out, "slots.tex"), "w") as f:
        f.write("% generated by scripts/report_macros.py; do not edit\n" + "\n".join(lines) + "\n")


# SNAP's published sizes (the dataset pages, "Networks with ground-truth communities"; email-Eu-core counts directed
# edges). The converter's counts are compared with these in the dataset table.
SNAP_PUBLISHED = {"email-Eu-core": (1005, 25571), "com-amazon": (334863, 925872), "com-dblp": (317080, 1049866),
                  "com-youtube": (1134890, 2987624), "com-lj": (3997962, 34681189),
                  "com-orkut": (3072441, 117185083)}


def graph_values(out, results):
    """The graph extension: design values from the plans and the code, the graph validation, and cluster values."""
    import graph_plan as GP
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import make_graph_plan as MG
    vplan = RD.load_plan("vanda")
    dsn = lambda d: GP.DATASETS[d]["display"]  # noqa: E731
    R11, R12 = ["E11"], ["E11", "E12"]
    # ---- design (exists before any run)
    put("gr.ndata", len(GP.ORDER), R11)
    put("gr.datalist", listing([dsn(d) for d in GP.ORDER]), R11)
    put("gr.strongdata", listing([dsn(d) for d in GP.STRONG_DATASETS]), R11)
    put("gr.K", 10, R11)
    put("gr.s", 5, R11)
    put("gr.a", "1", R11)
    put("gr.theta", "0.1", R11)
    put("gr.tol", sci(1e-8, 0), R11)
    put("gr.avals", ",".join("%g" % a for a in MG.A_VALUES), R12)        # used inside a math set
    put("gr.svals", ",".join(str(x) for x in MG.S_VALUES), R12)
    put("gr.keepvals", ",".join("%g" % k for k in MG.KEEP_VALUES), R12)
    put("gr.keeplist", listing(["%g" % k for k in MG.KEEP_VALUES if k < 1]), R12)
    put("gr.rhs", MG.STRONG_RHS, ["E3"])
    put("gr.siters", MG.SERIAL_ITERS, ["E2"])
    put("gr.longrep", MG.LONG_REPEAT_S // 60, ["E3"])
    gcells = [c for c in vplan["cells"].values() if GP.is_graph(c)]
    put("gr.plan.cells", len(gcells), ["E10"])
    sys.path.insert(0, os.path.join(REPO, "checks"))
    import run_plan as RP
    ch = sum(RP.job_estimate(vplan, j)[0] * RP.job_estimate(vplan, j)[1] / 3600.0 for j in vplan["jobs"]
             if j.get("binary") == "graph")
    put("gr.plan.coreh", grp(round(ch, -1)), ["E10"])
    counts = sorted(set(c["ranks"] for c in gcells if c["dataset"] == "com-orkut" and c["threads"] == 1 and
                        any(c is vplan["cells"][x] for x in vplan["groups"]["graph-strong"]["cells"])))
    put("gr.strong.counts", listing([str(x) for x in counts]), ["E3"])
    vc = sorted(set(c["ranks"] * c["threads"] for cid, c in vplan["cells"].items()
                    if cid in vplan["groups"]["graph-variants"]["cells"]))
    put("gr.var.cores", listing([str(x) for x in vc]), ["E8"])
    rows = []
    for d in GP.ORDER:
        V0, E0 = SNAP_PUBLISHED[d]
        rows.append([dsn(d), grp(V0), grp(E0)])
    # ---- graph validation (latest qualified validate_graph.py JSON, a cluster's preferred)
    best = None
    for cl in ("vanda", "atlas", "local"):
        js = sorted(glob.glob(os.path.join(REPO, "results", "validation", cl, "*-graph.json")))
        js = [j for j in js if json.load(open(j)).get("qualified")]
        if js:
            best = (cl, js[-1])
            break
    rq = ["E9"]
    keys = ("gr.val.where", "gr.val.spmv", "gr.val.x", "gr.val.iters", "gr.val.conv", "gr.val.bound", "gr.val.dense",
            "gr.val.tinyV", "gr.val.tinyE", "gr.val.bugspmv", "gr.val.bugby", "gr.val.layouts", "gr.val.spmvtol",
            "gr.val.xtol", "gr.val.densetol", "gr.val.bugacc", "gr.val.acc")
    if best is None:
        for k in keys:
            pend(k, rq, "a qualification run of checks/validate_graph.py")
    else:
        cl, path = best
        S = json.load(open(path))
        STATUS["graph_validation_source"] = os.path.relpath(path, REPO)
        put("gr.val.where", {"local": "a development laptop", "vanda": "a Vanda compute node",
                             "atlas": "an Atlas compute node"}[cl], rq)
        det = S["correct"]["details"]
        ag = [i for i in det["G1"]["items"] if i["kind"] == "agree"]
        cv = [i for i in det["G1"]["items"] if i["kind"] == "converged"]
        dn = [i for i in det["G2"]["items"] if i["kind"] == "dense"]
        cvt = [i for i in det["G2"]["items"] if i["kind"] == "convert"][0]
        T = S["tolerances"]
        put("gr.val.layouts", len(ag), rq)
        put("gr.val.spmv", sci(max(i["spmv_diff"] for i in ag), 1), rq)
        put("gr.val.x", sci(max(i["x_diff"] for i in ag), 1), rq)
        put("gr.val.iters", T["agree_iters"], rq)
        put("gr.val.spmvtol", sci(T["spmv_tol"], 0), rq)
        put("gr.val.xtol", sci(T["agree_tol"], 0), rq)
        put("gr.val.densetol", sci(T["dense_tol"], 0), rq)
        put("gr.val.conv", sci(max(i["diff"] for i in cv), 1), rq)
        put("gr.val.bound", sci(min(i["bound"] for i in cv), 1), rq)
        put("gr.val.acc", fx(cv[0]["accuracy_ref"], 3), rq)
        put("gr.val.dense", sci(max(i["diff"] for i in dn), 1), rq)
        put("gr.val.tinyV", cvt["meta"]["vertices"], rq)
        put("gr.val.tinyE", cvt["meta"]["edges"], rq)
        bug = S["bugs"][0] if S["bugs"] else None
        if bug:
            bag = [i for i in bug["details"]["G1"]["items"] if i["kind"] == "agree"]
            put("gr.val.bugspmv", sci(min(i["spmv_diff"] for i in bag), 1), rq)
            bcv = [i for i in bug["details"]["G1"]["items"] if i["kind"] == "converged"]
            put("gr.val.bugacc", fx(min(i["accuracy"] for i in bcv), 3) if bcv else "--", rq)
            put("gr.val.bugby", " and ".join(bug["refused_by"]), rq)
        else:
            for k in ("gr.val.bugspmv", "gr.val.bugacc", "gr.val.bugby"):
                pend(k, rq, "a qualification with the planted-bug build")

    # ---- cluster rows
    Dser = RD.choose(results, ["graph-serial"])
    Dst = RD.choose(results, ["graph-strong"])
    Dvar = RD.choose(results, ["graph-variants"])
    Dsw = RD.choose(results, ["graph-sweep"])
    NM = RD.NAMES
    for key, d in (("serial", Dser), ("strong", Dst), ("variants", Dvar), ("sweep", Dsw)):
        put("cl.gr.%s" % key, NM[d.cluster])

    # dataset table: converter counts from the 1-core natural-order rows, published counts, community selection
    if Dser.complete("graph-serial") and Dsw.complete("graph-sweep"):
        rows = []
        for d in GP.ORDER:
            cs = Dser.cells("graph-serial", dataset=d, order="natural")
            r = Dser.row0(cs[0][0])
            ds = [x for x in Dsw.cells("graph-sweep", dataset=d) if x[1]["a"] == 1.0 and x[1]["s"] == 5 and
                  x[1]["keep"] == 1.0]
            q = Dsw.row0(ds[0][0])
            V0, E0 = SNAP_PUBLISHED[d]
            rows.append([dsn(d), grp(r["vertices"]), grp(r["edges"]), "%s / %s" % (grp(V0), grp(E0)),
                         fx(float(r["avg_degree"]), 1), grp(r["max_degree"]), grp(q["eval_vertices"]),
                         fx(float(q["majority"]), 3)])
        table(out, "graphdata", ["dataset", "$V$", "$E$", "SNAP $V$ / $E$", "$2E/V$", "$d_{\\max}$", "evaluated",
                                 "majority"], rows, "lrrrrrrr", R12)
    else:
        w = "; ".join(Dser.waiting("graph-serial") + Dsw.waiting("graph-sweep"))
        table(out, "graphdata", ["dataset", "$V$", "$E$", "$2E/V$"], [], "lrrr", R12, False, w)

    # accuracy against the baselines (defaults a = 1, s = 5, all edges)
    if Dsw.complete("graph-sweep"):
        rows, accs = [], {}
        for d in GP.ORDER:
            cs = dict(((c["a"], c["s"], c["keep"]), cid) for cid, c in Dsw.cells("graph-sweep", dataset=d))
            cid = cs[(1.0, 5, 1.0)]
            q = Dsw.row0(cid)
            acc = float(q["accuracy"])
            accs[d] = acc
            ips = float(q["iters"]) / float(q["rhs"])
            rows.append([dsn(d), fx(acc, 3), fx(float(q["unreached"]), 3), fx(float(q["majority"]), 3),
                         fx(float(q["random"]), 3), grp(round(ips)), sig(float(q["t_solve"]), 3)])
            k8 = cs.get((1.0, 5, min(MG.KEEP_VALUES)))
            if k8:
                q8 = Dsw.row0(k8)
                put("gr.keep.%s.acc" % d, fx(float(q8["accuracy"]), 3), R12)
                put("gr.keep.%s.unr" % d, fx(float(q8["unreached"]), 3), R12)
                put("gr.keep.%s.itratio" % d, fx(ips / (float(q8["iters"]) / float(q8["rhs"])), 1), R12)
                put("gr.keep.%s.deg" % d, fx(float(q8["avg_degree"]), 1), R12)
                put("gr.keep.%s.loss" % d, fx(acc - float(q8["accuracy"]), 3), R12)
            put("gr.acc.%s" % d, fx(acc, 3), R11)
            put("gr.maj.%s" % d, fx(float(q["majority"]), 3), R11)
        lo, hi = min(accs, key=accs.get), max(accs, key=accs.get)
        put("gr.acc.lo", "%s on %s" % (fx(accs[lo], 3), dsn(lo)), R11)
        put("gr.acc.hi", "%s on %s" % (fx(accs[hi], 3), dsn(hi)), R11)
        # iterations against a (log-log slope), on the datasets that have the whole a range
        sl = []
        for d in GP.ORDER:
            pts = sorted((c["a"], Dsw.med(cid, "iters") / c["rhs"]) for cid, c in Dsw.cells("graph-sweep", dataset=d)
                         if c["s"] == 5 and c["keep"] == 1.0 and c["a"] <= 1.0)
            if len(pts) >= 3:
                sl.append(slope([math.log(p[0]) for p in pts], [math.log(p[1]) for p in pts]))
        put("gr.aslope", fx(statistics.median(sl), 2) if sl else "--", R12)
        table(out, "graphacc", ["dataset", "accuracy", "unreached", "majority", "random", "iterations/solve",
                                "time/solve (s)"], rows, "lrrrrrr", R11)
        rk = dict((c["dataset"], c["ranks"]) for cid, c in Dsw.cells("graph-sweep") if c["a"] == 1.0 and c["s"] == 5
                  and c["keep"] == 1.0)
        put("gr.sweep.ranks", max(rk.values()), R11)
        put("gr.sweep.ranks.email", rk.get("email-Eu-core", max(rk.values())), R11)
    else:
        w = "; ".join(Dsw.waiting("graph-sweep"))
        for d in GP.ORDER:
            for k in ("acc", "maj"):
                pend("gr.%s.%s" % (k, d), R11, w)
            for k in ("acc", "unr", "itratio", "deg", "loss"):
                pend("gr.keep.%s.%s" % (d, k), R12, w)
        for k in ("gr.acc.lo", "gr.acc.hi", "gr.aslope"):
            pend(k, R11, w)
        table(out, "graphacc", ["dataset", "accuracy", "majority", "random"], [], "lrrr", R11, False, w)

    # serial ladder: time per iteration against nonzeros, and the effect of the BFS order
    rq = ["E2", "E12"]
    if Dser.complete("graph-serial"):
        fits, gains = {}, []
        for order in ("natural", "bfs"):
            pts = sorted((int(Dser.row0(cid)["nonzeros"]), Dser.med(cid, "t_iter")) for cid, c in
                         Dser.cells("graph-serial", order=order))
            fits[order] = slope([math.log(p[0]) for p in pts], [math.log(p[1]) for p in pts])
            put("gr.ser.ns.%s" % order, fx(1e9 * pts[-1][1] / pts[-1][0], 2), rq)
        for d in GP.ORDER:
            tn = Dser.med(Dser.cells("graph-serial", dataset=d, order="natural")[0][0], "t_iter")
            tb = Dser.med(Dser.cells("graph-serial", dataset=d, order="bfs")[0][0], "t_iter")
            gains.append((tn / tb, d))
        put("gr.ser.slope", fx(fits["natural"], 2), rq)
        put("gr.ser.slopebfs", fx(fits["bfs"], 2), rq)
        g = max(gains)
        put("gr.ser.bfsgain", "%s (%s)" % (fx(g[0], 2), dsn(g[1])), rq)
    else:
        w = "; ".join(Dser.waiting("graph-serial"))
        for k in ("gr.ser.slope", "gr.ser.slopebfs", "gr.ser.bfsgain", "gr.ser.ns.natural", "gr.ser.ns.bfs"):
            pend(k, rq, w)

    # strong scaling (time per solve)
    rq = ["E3"]
    if Dst.complete("graph-strong"):
        Dst = Dst.filled_view()  # the top may be the shared-node insurance run (its partner not recorded)
        rows = []
        for d in GP.STRONG_DATASETS:
            for cg in ("classic", "pipelined"):
                cs = sorted(Dst.cells("graph-strong", dataset=d, cg=cg, threads=1), key=lambda t: t[1]["ranks"])
                Dst.check_same_build([cid for cid, c in cs], "graph-strong %s %s" % (d, cg))
                t1, tp, P = Dst.med(cs[0][0], "t_solve"), Dst.med(cs[-1][0], "t_solve"), cs[-1][1]["ranks"]
                n72 = [x for x in cs if x[1]["ranks"] == Dst.plan["cores_per_node"]]
                rows.append([dsn(d), cg, sig(t1, 3), sig(tp, 3) + (" ($%d^{\\dagger}$)" % P if cs[-1][1].get(
                    "placement") else ""), fx(t1 / tp, 1), fx(t1 / tp / P, 2)])
                put("gr.st.%s.%s.S" % (d, cg), fx(t1 / tp, 1), rq)
                put("gr.st.%s.%s.E" % (d, cg), fx(t1 / tp / P, 2), rq)
                put("gr.st.%s.%s.T1" % (d, cg), sig(t1, 3), rq)
                if n72:
                    put("gr.st.%s.%s.Enode" % (d, cg), fx(t1 / Dst.med(n72[0][0], "t_solve") / n72[0][1]["ranks"],
                                                          2), rq)
                else:
                    put("gr.st.%s.%s.Enode" % (d, cg), "--", rq)
                if cg == "classic":
                    r = Dst.row0(cs[-1][0])
                    tot = Dst.med(cs[-1][0], "t_total")
                    put("gr.comm.%s.halo" % d, "%s\\%%" % fx(100 * Dst.med(cs[-1][0], "t_halo") / tot, 0), ["E5"])
                    put("gr.comm.%s.red" % d, "%s\\%%" % fx(100 * Dst.med(cs[-1][0], "t_reduce") / tot, 0), ["E5"])
                    put("gr.comm.%s.ghosts" % d, grp(r["ghosts_max"]), ["E5"])
                    put("gr.comm.%s.nbrs" % d, grp(r["neighbors_max"]), ["E5"])
        put("gr.st.top", cs[-1][1]["ranks"], rq)
        table(out, "graphstrong", ["dataset", "CG", "$T(1)$ (s)", "$T(P_{\\max})$ (s)", "$S$", "$E$"], rows,
              "llrrrr", rq)
    else:
        w = "; ".join(Dst.waiting("graph-strong"))
        for d in GP.STRONG_DATASETS:
            for cg in ("classic", "pipelined"):
                for k in ("S", "E", "T1", "Enode"):
                    pend("gr.st.%s.%s.%s" % (d, cg, k), rq, w)
            for k in ("halo", "red", "ghosts", "nbrs"):
                pend("gr.comm.%s.%s" % (d, k), ["E5"], w)
        pend("gr.st.top", rq, w)
        table(out, "graphstrong", ["dataset", "CG", "$S$", "$E$"], [], "llrr", rq, False, w)

    # partitions: edge cut, ghosts, imbalance, and the best variant at the largest core count
    rq = ["E8", "E12"]
    if Dvar.complete("graph-variants"):
        rows = []
        for d in GP.STRONG_DATASETS:
            top = max(c["ranks"] for cid, c in Dvar.cells("graph-variants", dataset=d, threads=1))
            best = []
            for (o, p) in MG.VARIANT_PARTS:
                cs = Dvar.cells("graph-variants", dataset=d, threads=1, ranks=top, order=o, part=p,
                                exchange="neighbor", cg="classic")
                r = Dvar.row0(cs[0][0])
                rows.append([dsn(d), "%s, %s" % (o, p), "%s\\%%" % fx(100 * float(r["cut_fraction"]), 1),
                             grp(r["ghosts_max"]), grp(r["neighbors_max"]), fx(float(r["nnz_imbalance"]), 2),
                             sig(Dvar.med(cs[0][0], "t_solve"), 3)])
                put("gr.cut.%s.%s.%s" % (d, o, p), "%s\\%%" % fx(100 * float(r["cut_fraction"]), 1), rq)
                put("gr.imb.%s.%s.%s" % (d, o, p), fx(float(r["nnz_imbalance"]), 2), rq)
                for e in MG.EXCHANGES:
                    for cg in ("classic", "pipelined"):
                        cc = Dvar.cells("graph-variants", dataset=d, threads=1, ranks=top, order=o, part=p,
                                        exchange=e, cg=cg)
                        best.append((Dvar.med(cc[0][0], "t_solve"), o, p, e, cg))
            best.sort()
            put("gr.var.%s.best" % d, "%s order, %s partition, %s exchange, %s CG" % best[0][1:], rq)
            put("gr.var.%s.spread" % d, fx(best[-1][0] / best[0][0], 2), rq)
            put("gr.var.%s.top" % d, top, rq)
        table(out, "graphpart", ["dataset", "order, partition", "edges cut", "max ghosts", "max neighbours",
                                 "nnz imbalance", "time/solve (s)"], rows, "llrrrrr", rq)
    else:
        w = "; ".join(Dvar.waiting("graph-variants"))
        for d in GP.STRONG_DATASETS:
            for (o, p) in MG.VARIANT_PARTS:
                pend("gr.cut.%s.%s.%s" % (d, o, p), rq, w)
                pend("gr.imb.%s.%s.%s" % (d, o, p), rq, w)
            for k in ("best", "spread", "top"):
                pend("gr.var.%s.%s" % (d, k), rq, w)
        table(out, "graphpart", ["dataset", "order, partition", "edges cut", "nnz imbalance"], [], "llrr", rq,
              False, w)


def partial_values(out, results):
    """Values from the cells recorded so far, each named by the core count it describes (".72", ".144"), so a text
    that cites them never claims a scale it does not have. Each value waits on its own cells only. The values that
    name the largest planned count ("top") stay in cluster_values/graph_values and wait for the whole group."""
    import graph_plan as GP
    NM = RD.NAMES

    def med(D, cid, col="t_total"):
        return D.med(cid, col) if cid in D.cell_rows else None

    def need(key, reqs, waiting, fn):
        try:
            v = fn()
        except (KeyError, IndexError, TypeError, ZeroDivisionError, ValueError):
            v = None
        if v is None:
            pend(key, reqs, waiting)
        else:
            put(key, v, reqs)

    # ---- node facts (job environment files) and the calibrated bandwidths
    D = RD.choose(results, ["strong", "weak"])
    cpn = D.plan["cores_per_node"]
    envs = [json.load(open(e)) for e in sorted(glob.glob(os.path.join(results, D.cluster, "env", "*.json")))
            if not os.path.basename(e).startswith("discover")]
    socks = sorted(set(e.get("sockets") for e in envs if e.get("sockets")))
    cpu = sorted(set(e.get("cpu_model") for e in envs if e.get("cpu_model")))
    w = "%s job environment files" % NM[D.cluster]
    need("node.sockets", ["E5"], w, lambda: socks[0] if len(socks) == 1 else None)
    need("node.cps", ["E5"], w, lambda: cpn // socks[0] if len(socks) == 1 else None)
    need("node.cpu", ["E10"], w, lambda: cpu[0].replace("(R)", "").replace("(TM)", "") if len(cpu) == 1 else None)
    calp = os.path.join(results, D.cluster, "calibration.json")
    cal = json.load(open(calp)) if os.path.exists(calp) else {}
    w = "%s calibration (results/%s/calibration.json)" % (NM[D.cluster], D.cluster)
    need("cal.core", ["E5"], w, lambda: fx(cal["bw_core_gbs"], 1))
    need("cal.node", ["E5"], w, lambda: grp(round(cal["bw_node_gbs"])))
    need("cal.ratio", ["E5"], w, lambda: fx(cal["bw_node_gbs"] / cal["bw_core_gbs"], 1))
    bpp = D.plan["model"]["bytes_per_point_iter"]
    put("cg.bytes.classic", int(bpp["classic"]), ["E5"])
    put("cg.bytes.pipelined", int(bpp["pipelined"]), ["E5"])
    put("cg.byteratio", fx(bpp["pipelined"] / float(bpp["classic"]), 2), ["E5"])
    for cg, parts in STREAMS.items():
        tot = sum(k for _, k in parts)
        if 8 * tot != int(bpp[cg]):
            raise SystemExit("report_macros: STREAMS[%s] = %d streams, but the plan's model says %s bytes" %
                             (cg, tot, bpp[cg]))
        put("cg.st.%s" % cg, tot, ["E5"])
        for nm, k in parts:
            put("cg.st.%s.%s" % (cg, nm), k, ["E5"])
    for d in (2, 3):
        put("cg.flops%d" % d, FLOPS_CLASSIC[d], ["E5"])
        put("cg.ai%d" % d, fx(FLOPS_CLASSIC[d] / float(bpp["classic"]), 2), ["E5"])
    peak = SPEC["cpu.channels"] * 8 * SPEC["cpu.mts"] / 1000.0  # GB/s per socket
    put("spec.cpu.channels", SPEC["cpu.channels"], ["E10"])
    put("spec.cpu.mts", grp(SPEC["cpu.mts"]), ["E10"])
    put("spec.cpu.memtype", SPEC["cpu.memtype"], ["E10"])
    put("spec.cpu.peak", fx(peak, 1), ["E10"])
    put("spec.node.peak", fx(2 * peak, 1), ["E10"])
    put("spec.cpu.cache", fx(SPEC["cpu.cache_mb"], 1), ["E10"])
    put("spec.gpu.name", SPEC["gpu.name"], ["E10"])
    put("spec.gpu.mem", SPEC["gpu.mem_gb"], ["E10"])
    put("spec.gpu.bw", SPEC["gpu.bw_gbs"], ["E10"])
    if cal:
        put("cal.node.ofpeak", fx(cal["bw_node_gbs"] / (2 * peak), 2), ["E5"])
        put("cal.core.ofpeak", fx(cal["bw_core_gbs"] / peak, 2), ["E5"])
    else:
        pend("cal.node.ofpeak", ["E5"], w)
        pend("cal.core.ofpeak", ["E5"], w)

    # core counts by role, so the text names a role ("node") and not a number that only holds on one cluster
    role = {1: "one", cpn // 4: "q", cpn // 2: "half", cpn: "node", 2 * cpn: "2node"}

    def names(P):
        return [str(P)] + ([role[P]] if P in role else [])

    # ---- Poisson strong and weak, per core count recorded
    for group, tag, reqs in (("strong", "pst", ["E3"]), ("weak", "pwk", ["E4"])):
        for d in (2, 3):
            for cg, halo in (("classic", "blocking"), ("pipelined", "overlap")):
                cs = dict((c["ranks"], cid) for cid, c in D.cells(group, dim=d, cg=cg, halo=halo))
                w = "; ".join(D.waiting(group))
                t1 = med(D, cs.get(1))
                for P in sorted(cs):
                    tp = med(D, cs[P])
                    for nm in names(P):
                        key = "%s.%d.%s.%s" % (tag, d, cg, nm)
                        if group == "strong":
                            need(key + ".S", reqs, w, lambda: fx(t1 / tp, 1))
                            need(key + ".E", reqs, w, lambda: fx(t1 / (P * tp), 2))
                        else:
                            need(key + ".E", reqs, w, lambda: fx(t1 / tp, 2))
                        need(key + ".T", reqs, w, lambda: sig(tp, 3))
                for P, nm in role.items():  # a role this cluster's plan has no run for (Atlas: no second node)
                    if P not in cs:
                        key = "%s.%d.%s.%s" % (tag, d, cg, nm)
                        why = "no %d-core %s run in the %s plan" % (P, group, D.plan["plan"])
                        for k in ((".S", ".E", ".T") if group == "strong" else (".E", ".T")):
                            pend(key + k, reqs, why)
            # pipelined / classic time ratio at one node, and the gain from one socket's worth of ranks to a node
            cl = dict((c["ranks"], cid) for cid, c in D.cells(group, dim=d, cg="classic", halo="blocking"))
            pi = dict((c["ranks"], cid) for cid, c in D.cells(group, dim=d, cg="pipelined", halo="overlap"))
            for P in (1, cpn, 2 * cpn):
                need("%s.%d.pratio.%s" % (tag, d, role[P]), reqs, "; ".join(D.waiting(group)),
                     lambda: fx(med(D, pi[P]) / med(D, cl[P]), 2))
            if group == "strong":
                for a, b in ((cpn // 4, cpn // 2), (cpn // 2, cpn), (cpn, 2 * cpn)):
                    need("pst.%d.classic.gain.%s.%s" % (d, role[a], role[b]), reqs, "; ".join(D.waiting(group)),
                         lambda: fx(med(D, cl[a]) / med(D, cl[b]), 2))
            else:
                need("pwk.%d.classic.ratio.2node.node" % d, reqs, "; ".join(D.waiting(group)),
                     lambda: fx(med(D, cl[2 * cpn]) / med(D, cl[cpn]), 2))
    # communication shares at one and two nodes (strong runs), both variants
    for d in (2, 3):
        for cg, halo in (("classic", "blocking"), ("pipelined", "overlap")):
            cs = dict((c["ranks"], cid) for cid, c in D.cells("strong", dim=d, cg=cg, halo=halo))
            for P in (cpn, 2 * cpn):
                for col, nm in (("t_halo", "halo"), ("t_reduce", "red"), ("t_compute", "comp")):
                    need("pcm.%d.%s.%s.%s" % (d, cg, role[P], nm), ["E5"], "; ".join(D.waiting("strong")),
                         lambda: fx(100 * med(D, cs[P], col) / med(D, cs[P]), 1) + "\\,\\%")
    put("node.q", cpn // 4, ["E5"])
    # (the shared-node placement is described by spread.sent, spread.cap and spread.tabnote)
    # serial grids one by one: ns per unknown and per nonzero, per iteration
    Ds = RD.choose(results, ["serial"])
    for cid, c in Ds.cells("serial"):
        r = Ds.row0(cid) if cid in Ds.cell_rows else None
        need("ser.%d.n%d.ns" % (c["dim"], c["n"]), ["E2"], "; ".join(Ds.waiting("serial")),
             lambda: fx(1e9 * Ds.med(cid) / (float(r["iters"]) * int(r["unknowns"])), 2))
        need("ser.%d.n%d.N" % (c["dim"], c["n"]), ["E2"], "; ".join(Ds.waiting("serial")),
             lambda: grp(r["unknowns"]))
    big = {}
    for d in (2, 3):
        cs = sorted(Ds.cells("serial", dim=d), key=lambda t: t[1]["n"])
        if cs and cs[-1][0] in Ds.cell_rows:
            r = Ds.row0(cs[-1][0])
            big[d] = Ds.med(cs[-1][0]) / (float(r["iters"]) * int(r["unknowns"]))
    need("ser.ratio32", ["E2", "E12"], "; ".join(Ds.waiting("serial")), lambda: fx(big[3] / big[2], 2))
    V_ser_nsnnz2, r2 = [], None
    cs2 = sorted(Ds.cells("serial", dim=2), key=lambda t: t[1]["n"])
    if cs2 and cs2[-1][0] in Ds.cell_rows:
        r2 = Ds.row0(cs2[-1][0])
        V_ser_nsnnz2.append(Ds.med(cs2[-1][0]) / (float(r2["iters"]) * int(r2["nonzeros"])))
    import make_graph_plan as MG
    put("gr.smax", max(MG.S_VALUES), ["E11"])
    put("gr.amax", "%g" % max(MG.A_VALUES), ["E11"])
    put("gr.rand", fx(1.0 / 10, 3), ["E11"])
    put("node.cpn", cpn, ["E5"])
    put("node.cpn2", 2 * cpn, ["E5"])
    put("node.half", cpn // 2, ["E5"])

    # ---- graph strong, per core count recorded
    G = RD.choose(results, ["graph-strong"])
    w = "; ".join(G.waiting("graph-strong"))
    for ds in GP.STRONG_DATASETS:
        for cg in ("classic", "pipelined"):
            cs = dict((c["ranks"], cid) for cid, c in G.cells("graph-strong", dataset=ds, cg=cg, threads=1))
            t1 = med(G, cs.get(1), "t_solve")
            for P in (cpn, 2 * cpn):
                key = "pgs.%s.%s.%s" % (ds, cg, role[P])
                need(key + ".S", ["E3"], w, lambda: fx(t1 / med(G, cs[P], "t_solve"), 1))
                need(key + ".E", ["E3"], w, lambda: fx(t1 / med(G, cs[P], "t_solve") / P, 2))
                need(key + ".T", ["E3"], w, lambda: sig(med(G, cs[P], "t_solve"), 3))
                for col, nm in (("t_halo", "halo"), ("t_reduce", "red")):
                    need(key + "." + nm, ["E5"], w,
                         lambda: fx(100 * med(G, cs[P], col) / med(G, cs[P]), 0) + "\\,\\%")
            need("pgs.%s.%s.slowdown" % (ds, cg), ["E3"], w,
                 lambda: fx(med(G, cs[2 * cpn], "t_solve") / med(G, cs[cpn], "t_solve"), 2))
        cl = dict((c["ranks"], cid) for cid, c in G.cells("graph-strong", dataset=ds, cg="classic", threads=1))
        pi = dict((c["ranks"], cid) for cid, c in G.cells("graph-strong", dataset=ds, cg="pipelined", threads=1))
        for P in (cpn, 2 * cpn):
            need("pgs.%s.pratio.%s" % (ds, role[P]), ["E3"], w,
                 lambda: fx(med(G, pi[P], "t_solve") / med(G, cl[P], "t_solve"), 2))
        need("pgs.%s.itratio" % ds, ["E3"], w,
             lambda: fx(float(G.row0(pi[1])["iters"]) / float(G.row0(cl[1])["iters"]), 2))

    # ---- graph methods at one node (graph-variants at cpn cores), with the ranks x threads layouts
    V = RD.choose(results, ["graph-variants"])
    w = "; ".join(V.waiting("graph-variants"))
    rows = []
    for ds in GP.STRONG_DATASETS:
        def cell(order="natural", part="nnz", ex="neighbor", cg="classic", rpn=cpn, th=1):
            cs = [cid for cid, c in V.cells("graph-variants", dataset=ds, order=order, part=part, exchange=ex, cg=cg,
                                              threads=th, nodes=1) if c["ranks"] == rpn]
            return cs[0] if cs and cs[0] in V.cell_rows else None

        def ts(**kw):
            return med(V, cell(**kw), "t_solve")

        def r0(**kw):
            return V.row0(cell(**kw))
        base = dict()
        key = "gv.%s.node" % ds
        need(key + ".T", ["E8"], w, lambda: sig(ts(), 3))
        need(key + ".hybrid", ["E8", "E6"], w, lambda: fx(ts() / ts(rpn=2, th=cpn // 2), 2))
        need(key + ".hybrid.T", ["E8", "E6"], w, lambda: sig(ts(rpn=2, th=cpn // 2), 3))
        need(key + ".h8", ["E8", "E6"], w, lambda: fx(ts() / ts(rpn=8, th=cpn // 8), 2))
        need(key + ".rows", ["E8", "E12"], w, lambda: fx(ts(part="rows") / ts(), 2))
        need(key + ".imb.rows", ["E8", "E12"], w, lambda: fx(float(r0(part="rows")["nnz_imbalance"]), 2))
        need(key + ".bfs", ["E8", "E12"], w, lambda: fx(ts(order="bfs") / ts(), 2))
        need(key + ".a2a", ["E8"], w, lambda: fx(ts(ex="alltoallv") / ts(), 2))
        need(key + ".ovl", ["E8"], w, lambda: fx(ts(ex="overlap") / ts(), 2))
        need(key + ".pipe", ["E8"], w, lambda: fx(ts(cg="pipelined") / ts(), 2))
        for nm, kw in (("nat", {}), ("bfs", {"order": "bfs"}), ("hyb", {"rpn": 2, "th": cpn // 2})):
            need("%s.cut.%s" % (key, nm), ["E8", "E12"], w,
                 lambda: fx(100 * float(r0(**kw)["cut_fraction"]), 0) + "\\,\\%")
            need("%s.nbrs.%s" % (key, nm), ["E8"], w, lambda: grp(r0(**kw)["neighbors_max"]))
        need(key + ".halo", ["E5", "E8"], w,
             lambda: fx(100 * med(V, cell(), "t_halo") / med(V, cell()), 0) + "\\,\\%")
        for (o, p, rpn, th) in (("natural", "rows", cpn, 1), ("natural", "nnz", cpn, 1), ("bfs", "nnz", cpn, 1),
                                ("natural", "nnz", 8, cpn // 8), ("natural", "nnz", 2, cpn // 2)):
            c = cell(order=o, part=p, rpn=rpn, th=th)
            if c is None:
                continue
            r = V.row0(c)
            rows.append([GP.DATASETS[ds]["display"], "%s, %s" % (o, p), "%d$\\times$%d" % (rpn, th),
                         fx(100 * float(r["cut_fraction"]), 1) + "\\%", grp(r["ghosts_max"]), grp(r["neighbors_max"]),
                         fx(float(r["nnz_imbalance"]), 2), sig(med(V, c, "t_solve"), 3)])
    hd = ["dataset", "order, partition", "layout", "cut", "ghosts", "nbrs", "imbal.", "s/system"]
    if rows:
        table(out, "graphpart72", hd, rows, "lllrrrrr", ["E8", "E12"], partial=bool(V.waiting("graph-variants")),
              waiting="%d-core variants: %s" % (2 * 2 * cpn, w) if V.waiting("graph-variants") else "")
    else:
        table(out, "graphpart72", hd, [], "lllrrrrr", ["E8", "E12"], False, w)

    # ---- graph serial: BFS against natural order per dataset; sweep extras
    S = RD.choose(results, ["graph-serial"])
    w = "; ".join(S.waiting("graph-serial"))
    for ds in GP.ORDER:
        def tser(order):
            cs = [cid for cid, c in S.cells("graph-serial", dataset=ds, order=order)]
            return med(S, cs[0], "t_iter")
        need("gs.%s.bfsratio" % ds, ["E2", "E12"], w, lambda: fx(tser("natural") / tser("bfs"), 2))

        def treps(order):
            cs = [cid for cid, c in S.cells("graph-serial", dataset=ds, order=order)]
            return [float(r["t_iter"]) for r in S.cell_rows[cs[0]]]
        # how far the repeats of one order disagree, and the speed-up from the fastest repeat of each order
        need("gs.%s.natspread" % ds, ["E2", "E12"], w, lambda: fx(100 * (max(treps("natural")) - min(treps(
            "natural"))) / statistics.median(treps("natural")), 0) + "\\,\\%")
        need("gs.%s.bfsratio.fast" % ds, ["E2", "E12"], w, lambda: fx(min(treps("natural")) / min(treps("bfs")), 2))
        need("gs.%s.ns" % ds, ["E2", "E12"], w, lambda: fx(1e9 * tser("natural") / int(
            S.row0([cid for cid, c in S.cells("graph-serial", dataset=ds, order="natural")][0])["nonzeros"]), 2))
    # the full set per graph, in a table (the text cites a few)
    rows = []
    for ds in GP.ORDER:
        try:
            nat = [cid for cid, c in S.cells("graph-serial", dataset=ds, order="natural")][0]
            bfs = [cid for cid, c in S.cells("graph-serial", dataset=ds, order="bfs")][0]
            r = S.row0(nat)
            tn, tb = med(S, nat, "t_iter"), med(S, bfs, "t_iter")
            rows.append([GP.DATASETS[ds]["display"], grp(r["vertices"]), grp(r["nonzeros"]),
                         fx(1e9 * tn / int(r["nonzeros"]), 2), fx(1e9 * tb / int(r["nonzeros"]), 2), fx(tn / tb, 2)])
        except (IndexError, TypeError, KeyError):
            pass
    hd = ["graph", "$V$", "nonzeros", "ns/nonzero, natural", "ns/nonzero, BFS", "BFS speed-up"]
    if len(rows) == len(GP.ORDER):
        table(out, "graphserial", hd, rows, "lrrrrr", ["E2", "E12"])
    else:
        table(out, "graphserial", hd, rows, "lrrrrr", ["E2", "E12"], False, w, partial=bool(rows))
    W = RD.choose(results, ["graph-sweep"])
    w = "; ".join(W.waiting("graph-sweep"))
    for ds in GP.ORDER:
        cs = dict(((c["a"], c["s"], c["keep"]), cid) for cid, c in W.cells("graph-sweep", dataset=ds))
        avals = sorted(set(k[0] for k in cs))
        for nm, k in (("s1", (1.0, 1, 1.0)), ("s20", (1.0, 20, 1.0)), ("s2", (1.0, 2, 1.0)),
                      ("amin", (avals[0] if avals else 0, 5, 1.0)), ("a100", (100.0, 5, 1.0))):
            need("gw.%s.%s.acc" % (ds, nm), ["E11"], w, lambda: fx(float(W.row0(cs[k])["accuracy"]), 3))
            need("gw.%s.%s.unr" % (ds, nm), ["E11"], w, lambda: fx(float(W.row0(cs[k])["unreached"]), 3))
            need("gw.%s.%s.it" % (ds, nm), ["E11", "E12"], w,
                 lambda: grp(round(float(W.row0(cs[k])["iters"]) / W.plan["cells"][cs[k]]["rhs"])))
        need("gw.%s.amin" % ds, ["E11"], w, lambda: "%g" % avals[0])
        need("gw.%s.it" % ds, ["E11", "E12"], w,
             lambda: grp(round(float(W.row0(cs[(1.0, 5, 1.0)])["iters"]) / 10)))
        need("gw.%s.deg" % ds, ["E11", "E12"], w, lambda: fx(float(W.row0(cs[(1.0, 5, 1.0)])["avg_degree"]), 1))
        need("gw.%s.dmax" % ds, ["E11", "E12"], w, lambda: grp(W.row0(cs[(1.0, 5, 1.0)])["max_degree"]))
        need("gw.%s.itratio" % ds, ["E12"], w, lambda: fx(
            (float(W.row0(cs[(1.0, 5, 1.0)])["iters"]) / 10) / math.sqrt(2 * int(W.row0(cs[(1.0, 5, 1.0)])[
                "max_degree"]) + 1), 1))

    # accuracy over the majority baseline, the range over the four graphs the conclusions name
    lifts = []
    for ds in ("com-amazon", "com-lj", "com-youtube", "com-orkut"):
        try:
            cs = dict(((c["a"], c["s"], c["keep"]), cid) for cid, c in W.cells("graph-sweep", dataset=ds))
            r = W.row0(cs[(1.0, 5, 1.0)])
            lifts.append(float(r["accuracy"]) / float(r["majority"]))
        except (KeyError, TypeError, ZeroDivisionError):
            pass
    need("gr.lift.range", ["E11"], "; ".join(W.waiting("graph-sweep")),
         lambda: "%s to %s" % (fx(min(lifts), 1), fx(max(lifts), 1)) if len(lifts) == 4 else None)
    # graph against grid, cost per nonzero on the largest of each; bandwidth share of one rank on a full node
    # bytes streamed per nonzero: the graph operator (rows: 96 B of CG vectors as for the grid, plus the CSR row
    # data; entries: the column index) against the 2D stencil (96 B per unknown over its nonzeros per unknown)
    def gbytes(ds):
        r = S.row0([cid for cid, c in S.cells("graph-serial", dataset=ds, order="natural")][0])
        V, nnz = int(r["vertices"]), int(r["nonzeros"])
        return ((int(bpp["classic"]) + GRAPH_BYTES_ROW) * V + GRAPH_BYTES_NNZ * (nnz - V)) / float(nnz)
    put("gs.bytes.row", GRAPH_BYTES_ROW, ["E2", "E12"])
    put("gs.bytes.nnz", GRAPH_BYTES_NNZ, ["E2", "E12"])
    need("gs.com-orkut.bpnnz", ["E2", "E12"], "graph-serial runs", lambda: fx(gbytes("com-orkut"), 1))
    need("gs.com-orkut.streamns", ["E2", "E12"], "graph-serial runs and the calibration",
         lambda: fx(gbytes("com-orkut") / cal["bw_core_gbs"], 2))
    need("ser.bpnnz2", ["E2", "E12"], "serial runs", lambda: fx(int(bpp["classic"]) * int(r2["unknowns"]) /
                                                                 float(r2["nonzeros"]), 1))
    need("gs.vsgrid", ["E2", "E12"], "graph-serial and serial runs", lambda: fx(
        S.med([cid for cid, c in S.cells("graph-serial", dataset="com-orkut", order="natural")][0], "t_iter") /
        int(S.row0([cid for cid, c in S.cells("graph-serial", dataset="com-orkut", order="natural")][0])["nonzeros"])
        / float(V_ser_nsnnz2[0]), 1) if V_ser_nsnnz2 else None)
    need("cal.share", ["E4"], "%s calibration" % NM[D.cluster],
         lambda: fx(cal["bw_node_gbs"] / cpn / cal["bw_core_gbs"], 2))

def slope(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


# ASCII spellings of the non-ASCII characters in the appendix files (code comments and the README)
ASCII_FOR = {"≥": ">=", "≤": "<=", "×": "x", "−": "-", "Δ": "Delta", "∏": "prod", "∑": "sum", "Σ": "Sum",
             "‖": "||", "…": "...", "²": "^2", "³": "^3", "·": "*", "—": "--", "–": "-", "→": "->", "π": "pi",
             "ρ": "rho", "κ": "kappa", "ε": "eps", "ᵢ": "_i", "ⱼ": "_j", "≠": "!=", "≈": "~", "√": "sqrt",
             "∂": "d", "’": "'", "‘": "'", "“": '"', "”": '"', "∈": "in", "Ω": "Omega", "°": " deg", "⁻": "^-",
             "¹": "^1", "⁰": "^0", "₂": "_2", "λ": "lambda", "∞": "inf", "ᵈ": "^d", "\u202f": " ", "θ": "theta",
             "≲": "<~", "≳": ">~", "±": "+-", "µ": "u", "μ": "mu", "←": "<-", "⇒": "=>", "✓": "ok", "✗": "x"}


def literate(out):
    chars = set()
    for p in APPENDIX_FILES:
        with open(os.path.join(REPO, p), encoding="utf-8") as f:
            chars |= set(ch for ch in f.read() if ord(ch) > 126)
    known = {"≥": "$\\geq$", "≤": "$\\leq$", "×": "$\\times$", "−": "-", "Δ": "$\\Delta$", "∏": "$\\prod$",
             "∑": "$\\sum$", "Σ": "$\\Sigma$", "‖": "$\\|$", "…": "...", "²": "$^2$", "³": "$^3$", "·": "$\\cdot$",
             "—": "--", "–": "-", "→": "$\\to$", "π": "$\\pi$", "ρ": "$\\rho$", "κ": "$\\kappa$", "ε": "$\\epsilon$",
             "ᵢ": "$_i$", "ⱼ": "$_j$", "≠": "$\\neq$", "≈": "$\\approx$", "√": "$\\surd$", "∂": "$\\partial$",
             "’": "'", "‘": "'", "“": "\"", "”": "\"", "^": "\\^{}", "∈": "$\\in$", "Ω": "$\\Omega$", "°": "$^\\circ$",
             "⁻": "$^-$", "¹": "$^1$", "⁰": "$^0$", "₂": "$_2$", "λ": "$\\lambda$", "∞": "$\\infty$",
             "ᵈ": "$^d$", "\u202f": " ", "θ": "$\\theta$"}
    unknown = sorted(c for c in chars if c not in known and c not in ASCII_FOR)
    # listings cannot replace characters above 255 under XeTeX (tectonic), so the appendix prints ASCII copies of
    # the files (report/generated/listing/<path>), with each non-ASCII character spelled out as below
    for p in APPENDIX_FILES:
        with open(os.path.join(REPO, p), encoding="utf-8") as f:
            text = f.read()
        dst = os.path.join(out, "listing", p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="ascii") as f:
            f.write("".join(ch if ord(ch) < 127 else ASCII_FOR.get(ch, "?") for ch in text))
    with open(os.path.join(out, "literate.tex"), "w", encoding="utf-8") as f:
        f.write("% generated by scripts/report_macros.py: the list of appendix files (printed from ASCII copies)\n")
        f.write("\\newcommand{\\appendixfiles}{%s}\n" % ",".join(APPENDIX_FILES))
    STATUS["appendix_files"] = APPENDIX_FILES
    STATUS["appendix_unknown_chars"] = unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(REPO, "results"))
    ap.add_argument("--figures", default=os.path.join(REPO, "figures"))
    ap.add_argument("--out", default=os.path.join(REPO, "report", "generated"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for f in glob.glob(os.path.join(a.out, "tab_*.tex")):
        os.remove(f)
    RD._CACHE.clear()
    design_values(a.out, a.results)
    validation_values(a.out)
    cluster_values(a.out, a.results, a.figures)
    graph_values(a.out, a.results)
    partial_values(a.out, a.results)
    literate(a.out)
    put("generated_at", datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y, %H:%M UTC"))
    with open(os.path.join(a.out, "values.tex"), "w") as f:
        f.write("% generated by scripts/report_macros.py; do not edit\n")
        for k in sorted(V):
            f.write("\\setval{%s}{%s}\n" % (k, V[k]))
    STATUS["results"] = a.results
    STATUS["figures_dir"] = a.figures
    with open(os.path.join(a.out, "status.json"), "w") as f:
        json.dump(STATUS, f, indent=1)
    nv = len(STATUS["values"])
    pv = sum(1 for v in STATUS["values"].values() if not v["filled"])
    nt = len(STATUS["tables"])
    pt = sum(1 for v in STATUS["tables"].values() if not v["filled"])
    nf = len(STATUS["figures"])
    pf = sum(1 for v in STATUS["figures"].values() if not v["filled"])
    print("report_macros: %d values (%d waiting for cluster data), %d tables (%d waiting), %d figures (%d waiting)"
          % (nv, pv, nt, pt, nf, pf))
    if STATUS["appendix_unknown_chars"]:
        print("  appendix characters without a replacement: %s" % "".join(STATUS["appendix_unknown_chars"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
