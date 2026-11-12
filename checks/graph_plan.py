"""Graph cells of the run plans (the SNAP community-labelling extension): ids, solver arguments, matching rows to
cells, the cost model and the coverage rules. Used by checks/run_plan.py and scripts/make_graph_plan.py.

A graph cell is a dict with "kind": "graph" and: dataset, order (natural|bfs), part (rows|nnz), exchange
(alltoallv|neighbor|overlap), cg, a, K, s, keep, mode (tol|fixed), tol, iters, rhs (systems solved: K = the whole
labelling, fewer = timing only), ranks, threads, nodes, repeats, binary "graph", optional queue.
Standard library only, Python >= 3.6.
"""
import math

GRAPH_GROUPS = ("graph-serial", "graph-strong", "graph-variants", "graph-sweep")
STRONG_DATASETS = ("com-lj", "com-orkut")

# SNAP counts (undirected, after dropping self-loops and duplicates; email-Eu-core symmetrised) and the largest
# degree. email-Eu-core and com-amazon: measured by bin/p3convert on the Mac (12 Nov). The other maximum degrees are
# ASSUMED (SNAP-reported values) until the cluster conversion writes <name>.meta.json; they only enter the cost
# estimate below, never a result.
DATASETS = {
    "email-Eu-core": {"display": "email-Eu-core", "V": 1005, "E": 16064, "dmax": 345, "measured": True},
    "com-amazon": {"display": "com-Amazon", "V": 334863, "E": 925872, "dmax": 549, "measured": True},
    "com-dblp": {"display": "com-DBLP", "V": 317080, "E": 1049866, "dmax": 343, "measured": False},
    "com-youtube": {"display": "com-Youtube", "V": 1134890, "E": 2987624, "dmax": 28754, "measured": False},
    "com-lj": {"display": "com-LiveJournal", "V": 3997962, "E": 34681189, "dmax": 14815, "measured": False},
    "com-orkut": {"display": "com-Orkut", "V": 3072441, "E": 117185083, "dmax": 33313, "measured": False},
}
ORDER = ("email-Eu-core", "com-amazon", "com-dblp", "com-youtube", "com-lj", "com-orkut")

DEFAULT_MODEL = {
    "note": "graph cost model; ASSUMED values (Mac measurements scaled to a server core) until cluster rows exist",
    "bytes_per_nnz": 24.0,          # 4 (column index) + the random read of x_j (a cache line fragment)
    "bytes_per_row_iter": {"classic": 96.0, "pipelined": 128.0},  # vector updates, as the stencil's per point
    "iters_coeff": 3.5,             # iterations per solve ~ coeff * sqrt((2 d_max + a)/a); Mac: 3.4 (com-amazon)
    "iters_cap": 6000,
    "fs_gbs": 1.0,                  # file system read rate per job
    "setup_ns_per_nnz": 60.0,       # ghost lists, local CSR
    "convert_ns_per_edge": 600.0,   # bin/p3convert (Mac: ~270 ns per edge for com-amazon)
    "cut_fraction": 0.8,            # share of a rank's entries that point to ghosts (natural order, many ranks)
    "safety": 3.0,                  # walltime = safety x estimate (iteration counts are uncertain)
}


def is_graph(c):
    return c.get("kind") == "graph"


def fnum(x):
    return ("%g" % x).replace("+", "")


def cell_id(c):
    s = "g-%s-%s-%s-%s-%s-a%s-s%d-k%s-r%dx%d-N%d" % (c["dataset"], c["order"], c["part"], c["exchange"],
                                                     c["cg"][:4], fnum(c["a"]), c["s"], fnum(c["keep"]),
                                                     c["ranks"], c["threads"], c["nodes"])
    s += ("-i%d" % c["iters"]) if c["mode"] == "fixed" else ("-tol%s" % fnum(c["tol"]))
    s += "-rhs%d" % c["rhs"]
    if c.get("queue"):
        s += "-q%s" % c["queue"]
    return s


def make_cell(dataset, ranks, threads=1, nodes=1, order="natural", part="nnz", exchange="neighbor", cg="classic",
              a=1.0, s=5, K=10, keep=1.0, mode="tol", tol=1e-8, iters=100, rhs=None, repeats=3, queue=None):
    c = {"kind": "graph", "dataset": dataset, "order": order, "part": part, "exchange": exchange, "cg": cg,
         "a": float(a), "K": K, "s": s, "keep": float(keep), "mode": mode, "tol": tol if mode == "tol" else None,
         "iters": iters if mode == "fixed" else 0, "rhs": K if rhs is None else rhs, "ranks": ranks,
         "threads": threads, "nodes": nodes, "repeats": repeats, "gpus": 0, "binary": "graph"}
    if queue:
        c["queue"] = queue
    return c


def cell_args(c):
    a = ["--order", c["order"], "--part", c["part"], "--exchange", c["exchange"], "--cg", c["cg"], "--a",
         fnum(c["a"]), "--K", str(c["K"]), "--s", str(c["s"]), "--keep", fnum(c["keep"]), "--rhs", str(c["rhs"]),
         "--repeats", str(c.get("repeats", 1))]
    if c["mode"] == "fixed":
        a += ["--iters", str(c["iters"])]
    else:
        a += ["--tol", fnum(c["tol"]), "--maxit", "100000"]
    return a


def matches(c, r):
    try:
        same = (r["dataset"] == c["dataset"] and r["order"] == c["order"] and r["part"] == c["part"] and
                r["exchange"] == c["exchange"] and r["cg"] == c["cg"] and int(r["ranks"]) == c["ranks"] and
                int(r["threads"]) == c["threads"] and int(r["nodes"]) == c["nodes"] and r["mode"] == c["mode"] and
                int(r["K"]) == c["K"] and int(r["s"]) == c["s"] and int(r["rhs"]) == c["rhs"] and
                abs(float(r["a"]) - c["a"]) <= 1e-9 * c["a"] and abs(float(r["keep"]) - c["keep"]) <= 1e-9)
        if c["mode"] == "fixed":
            same = same and int(r["iters_req"]) == c["iters"]
        else:
            same = same and abs(float(r["tol"]) - c["tol"]) <= 1e-6 * c["tol"]
        return same
    except (KeyError, ValueError, TypeError):
        return False


def model(plan):
    m = dict(DEFAULT_MODEL)
    m.update(plan.get("graph_model", {}))
    return m


def iters_per_solve(c, m):
    d = DATASETS[c["dataset"]]
    if c["mode"] == "fixed":
        return float(c["iters"])
    # CG: iterations ~ sqrt(cond) log(2/tol); cond(L + aI) <= (2 d_max + a)/a; the coefficient is for tol 1e-8.
    est = m["iters_coeff"] * math.sqrt((2.0 * d["dmax"] * c["keep"] + c["a"]) / c["a"])
    return min(est, m["iters_cap"]) * math.log(2.0 / c["tol"]) / math.log(2.0 / 1e-8)


def cell_seconds(plan, c, base_model):
    """Estimated seconds for one graph cell (all repeats). base_model: run_plan.model_of(plan) (bandwidths, latency,
    network, launch). Rough by design."""
    m = model(plan)
    d = DATASETS[c["dataset"]]
    V, E = float(d["V"]), float(d["E"]) * c["keep"]
    nnz = 2 * E + V
    P, T = c["ranks"], c["threads"]
    rpn = -(-P // c["nodes"])
    loc_nnz, loc_rows = nnz / P * 1.05, V / P
    active = rpn * T
    per_core = min(base_model["bw_core_gbs"], base_model["bw_node_gbs"] / active)
    t_it = (loc_nnz * m["bytes_per_nnz"] + loc_rows * m["bytes_per_row_iter"][c["cg"]]) / (per_core * T * 1e9)
    if P > 1:
        ghosts = min(V, loc_nnz * m["cut_fraction"])
        t_it += min(P - 1, 128) * 4 * base_model["latency_s"] + ghosts * 8 / (base_model["net_gbs"] * 1e9)
        nred = 2 if c["cg"] == "classic" else 1
        t_it += nred * 2 * math.log(P, 2) * base_model["latency_s"]
    t_load = (16 * V + 8 * E / P) / (m["fs_gbs"] * 1e9) + 16 * V / (base_model["net_gbs"] * 1e9) + \
        m["setup_ns_per_nnz"] * loc_nnz * 1e-9
    reps = c.get("repeats", 1)
    return base_model["launch_s"] + t_load + reps * c["rhs"] * iters_per_solve(c, m) * t_it


def prep_seconds(plan, datasets):
    m = model(plan)
    return sum(m["convert_ns_per_edge"] * DATASETS[x]["E"] * 1e-9 * 2 + 30 for x in datasets)


def coverage(plan):
    """(problems, not_met) for the graph part of a cluster plan."""
    P, cells, g = plan, plan["cells"], plan["groups"]
    bad, not_met = [], []
    for need in GRAPH_GROUPS:
        if need not in g or not g[need]["cells"]:
            bad.append("group %s missing or empty (the graph extension, E11/E12)" % need)
    if bad:
        return bad, not_met

    def cores(c):
        return c["ranks"] * c["threads"]

    for gid in GRAPH_GROUPS:
        for cid in g[gid]["cells"]:
            if not is_graph(cells[cid]) or cells[cid].get("binary") != "graph":
                bad.append("%s: cell %s is not a graph cell" % (gid, cid))
    ser = [cells[x] for x in g["graph-serial"]["cells"] if cores(cells[x]) == 1]
    ds = sorted(set(c["dataset"] for c in ser), key=lambda x: DATASETS[x]["E"])
    if len(ds) < 4:
        bad.append("graph-serial: fewer than 4 datasets on 1 core")
    elif DATASETS[ds[-1]]["E"] / float(DATASETS[ds[0]]["E"]) < 10 ** 1.5:
        bad.append("graph-serial: datasets span less than 1.5 decades of edges")
    strong = [cells[x] for x in g["graph-strong"]["cells"]]
    for dset in STRONG_DATASETS:
        for cg in ("classic", "pipelined"):
            series = [c for c in strong if c["dataset"] == dset and c["cg"] == cg]
            if not any(cores(c) == 1 for c in series):
                bad.append("graph-strong %s %s: no 1-core baseline" % (dset, cg))
            top = max([cores(c) for c in series] or [0])
            if top < 256:
                msg = "graph-strong %s %s: no run on >= 256 cores (largest %d)" % (dset, cg, top)
                (not_met if P.get("fallback") else bad).append(msg)
            if len(set((c["order"], c["part"], c["exchange"], c["rhs"], c["a"], c["s"]) for c in series)) > 1:
                bad.append("graph-strong %s %s: cells differ in more than the rank count" % (dset, cg))
    var = [cells[x] for x in g["graph-variants"]["cells"]]
    for dset in STRONG_DATASETS:
        vs = [c for c in var if c["dataset"] == dset and c["threads"] == 1]
        counts = sorted(set(cores(c) for c in vs))
        if len(counts) < 2:
            bad.append("graph-variants %s: fewer than two core counts" % dset)
        for n in counts:
            at = [c for c in vs if cores(c) == n]
            combos = set((c["order"], c["part"], c["exchange"], c["cg"]) for c in at)
            want = set((o, p, e, cg) for (o, p) in (("natural", "rows"), ("natural", "nnz"), ("bfs", "nnz"))
                       for e in ("alltoallv", "neighbor", "overlap") for cg in ("classic", "pipelined"))
            if not want <= combos:
                bad.append("graph-variants %s at %d cores: %d of the %d partition x exchange x CG combinations "
                           "missing" % (dset, n, len(want - combos), len(want)))
    sw = [cells[x] for x in g["graph-sweep"]["cells"]]
    for dset in sorted(set(c["dataset"] for c in sw)):
        cs = [c for c in sw if c["dataset"] == dset]
        if any(c["rhs"] != c["K"] or c["mode"] != "tol" for c in cs):
            bad.append("graph-sweep %s: a cell does not solve all K systems to tolerance (no accuracy)" % dset)
        if len(set(c["a"] for c in cs)) < 4 or len(set(c["s"] for c in cs)) < 4 or len(set(c["keep"] for c in cs)) < 3:
            bad.append("graph-sweep %s: fewer than 4 values of a, 4 of s or 3 of keep" % dset)
    if len(set(c["dataset"] for c in sw)) < 4:
        bad.append("graph-sweep: fewer than 4 datasets (the sparsity comparison needs the ladder)")
    # added after the plan was frozen? then by an amendment with a reason
    ams = dict((x.get("id"), x) for x in P.get("amendments", []))
    for kind, items in (("group", list(g.items())), ("cell", list(cells.items())),
                        ("job", [(j["id"], j) for j in P["jobs"]])):
        for iid, it in items:
            for am in [it.get("amendment")] + list(it.get("changed_by", [])):  # added by / changed by
                if am and not (am in ams and ams[am].get("reason")):
                    bad.append("%s %s names amendment %s, which is not recorded with a reason" % (kind, iid, am))
    for j in P["jobs"]:
        gc = [cid for cid in j["cells"] if is_graph(cells.get(cid, {}))]
        if gc and j.get("binary") != "graph":
            bad.append("job %s runs graph cells but is not a graph job" % j["id"])
    return bad, not_met
