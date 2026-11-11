#!/usr/bin/env python3
"""Writes the run plans config/run_plan.<cluster>.json (vanda, atlas, local) with the arithmetic behind each size.

  python3 scripts/make_plan.py            # all three plans
  python3 scripts/make_plan.py vanda      # one plan

A plan lists every timed run ("cell") the report needs and groups the cells into PBS jobs. checks/run_plan.py
reads it: it prints the graded cells filled/total, estimates core-hours, writes the PBS scripts, and refuses a job
that is not in the plan unless the plan records why (key "unplanned"). Once runs start, set "frozen": true and
change the plan only by adding "unplanned"/"reruns" entries with a reason; regenerating a frozen plan is refused.
"""
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXED_ITERS = 100
REPEATS = 3

# Strong-scaling grids: about 6.7e7 unknowns in both 2D and 3D, so 2D and 3D differ only in the stencil (5 vs 7
# nonzeros per row) and in the halo surface per rank, not in work.
STRONG = {2: 8192, 3: 406}  # 8192^2 = 67,108,864; 406^3 = 66,923,416
# Weak scaling: about 2.1e6 unknowns per rank in both dimensions.
WEAK_BASE = {2: 1448, 3: 128}  # 1448^2 = 2,096,704; 128^3 = 2,097,152
# Serial sweep: 8 sizes per dimension; 3D sizes chosen so that N matches the 2D size at each step (within 5%), so at
# each N the nonzeros differ only through the stencil (5N vs 7N).
SERIAL = {2: [64, 128, 256, 512, 1024, 2048, 4096, 8192], 3: [16, 25, 40, 64, 101, 161, 256, 406]}
# Iterations-to-tolerance sweep (how CG's iteration count grows with n): small sizes only.
SERIAL_TOL = {2: [64, 128, 256, 512, 1024], 3: [16, 25, 40, 64, 101]}
TOL = 1e-8


def weak_n(dim, ranks):
    return int(round(WEAK_BASE[dim] * ranks ** (1.0 / dim)))


def cell_id(c):
    s = "%dd-n%d-r%dx%d-N%d-d%d-%s-%s" % (c["dim"], c["n"], c["ranks"], c["threads"], c["nodes"], c["decomp"],
                                         c["cg"][:4], c["halo"][:4])
    s += "-i%d" % c["iters"] if c["mode"] == "fixed" else "-tol%g" % c["tol"]
    if c.get("gpus", 0):
        s += "-g%d" % c["gpus"]
    return s


class Plan:
    def __init__(self, name, cluster, cores_per_node, notes):
        self.p = {"plan": name, "cluster": cluster, "frozen": False, "generated_by": "scripts/make_plan.py",
                  "cores_per_node": cores_per_node, "fixed_iters": FIXED_ITERS, "repeats": REPEATS,
                  "notes": notes, "arithmetic": [], "groups": {}, "cells": {}, "jobs": [],
                  "unplanned": [], "reruns": []}

    def cell(self, group, dim, n, ranks, threads=1, nodes=1, decomp=None, cg="classic", halo="blocking",
             mode="fixed", gpus=0, binary="cpu"):
        c = {"dim": dim, "n": n, "ranks": ranks, "threads": threads, "nodes": nodes,
             "decomp": dim if decomp is None else decomp, "cg": cg, "halo": halo, "mode": mode,
             "iters": FIXED_ITERS if mode == "fixed" else 0, "tol": TOL if mode == "tol" else None,
             "repeats": REPEATS if mode == "fixed" else 1, "gpus": gpus, "binary": binary}
        cid = cell_id(c)
        self.p["cells"].setdefault(cid, c)
        g = self.p["groups"][group]
        if cid not in g["cells"]:
            g["cells"].append(cid)
        return cid

    def group(self, gid, requirement, description, graded=True):
        self.p["groups"][gid] = {"requirement": requirement, "description": description, "graded": graded,
                                 "cells": []}

    def job(self, jid, nodes, ncpus, cells, binary="cpu", gpus_per_node=0, validate_first=False, note="",
            place="excl"):
        # place=excl: timing jobs reserve whole nodes so no other job shares their memory bandwidth or network.
        cells = [c for c in cells]
        self.p["jobs"].append({"id": jid, "nodes": nodes, "ncpus_per_node": ncpus, "gpus_per_node": gpus_per_node,
                               "binary": binary, "validate_first": validate_first, "place": place, "cells": cells,
                               "note": note})


def by_nodes(plan, cells_filter=None):
    """Splits cells by node count so each job allocates exactly the nodes its cells use."""
    out = {}
    for cid, c in plan.p["cells"].items():
        if c["binary"] != "cpu":
            continue
        if cells_filter and not cells_filter(cid, c):
            continue
        out.setdefault(c["nodes"], []).append(cid)
    return out


def scaling_counts(cpn, max_nodes):
    if cpn == 72:
        return [1, 2, 4, 9, 18, 36, 72, 144, 288]
    if cpn == 24:
        return [1, 2, 4, 6, 12, 24, 48, 96, 192, 264]
    if cpn == 10:
        return [1, 2, 4, 8]
    raise ValueError(cpn)


def layouts(cpn):
    if cpn == 72:
        return [(1, 72), (2, 36), (4, 18), (8, 9), (72, 1)]
    if cpn == 24:
        return [(1, 24), (2, 12), (4, 6), (8, 3), (24, 1)]
    if cpn == 10:
        return [(1, 8), (2, 4), (4, 2), (8, 1)]
    raise ValueError(cpn)


def build_cluster_plan(name, cpn, max_nodes, has_gpu, notes):
    P = Plan(name, name, cpn, notes)
    A = P.p["arithmetic"]
    counts = scaling_counts(cpn, max_nodes)
    top = counts[-1]
    A.append("Fixed %d CG iterations per timed run (runs comparable, core-hours bounded); %d repeats in one process, "
             "report the median; validation runs iterate to a tolerance instead (checks/validate.py)." %
             (FIXED_ITERS, REPEATS))
    A.append("Strong grids: 2D n=%d -> N=%s; 3D n=%d -> N=%s. Same work, different stencil and surface/volume." %
             (STRONG[2], format(STRONG[2] ** 2, ","), STRONG[3], format(STRONG[3] ** 3, ",")))
    A.append("Memory at 1 rank: N x 8 B = %.2f GB per vector; classic CG holds 5 vectors (x b r p q) = %.1f GB, "
             "pipelined 8 (x b r p w s z n) = %.1f GB; fits one node." %
             (STRONG[2] ** 2 * 8 / 1e9, 5 * STRONG[2] ** 2 * 8 / 1e9, 8 * STRONG[2] ** 2 * 8 / 1e9))
    A.append("Serial time at the strong grid: classic ~96 B/point/iteration (stencil 3 streams, update 6, p update 3) "
             "-> 6.4 GB per iteration; at ~10 GB/s for one server core about 0.6 s/iteration, ~1 min per run of %d "
             "iterations, ~3 min with %d repeats (Mac M5 measured: 1.1 ns/point/iteration, i.e. ~85 GB/s)." %
             (FIXED_ITERS, REPEATS))
    A.append("Rank counts %s: up to %d cores = %d nodes x %d (>= 256 required)." %
             (counts, top, top // cpn if top % cpn == 0 else top // cpn + 1, cpn))
    A.append("Weak scaling: n(P) = round(n0 * P^(1/d)), n0 = %d (2D), %d (3D) -> ~2.1e6 unknowns per rank; "
             "at P=%d: 2D n=%d (N=%.2e), 3D n=%d (N=%.2e); total memory %.0f GB (pipelined) over %d nodes." %
             (WEAK_BASE[2], WEAK_BASE[3], top, weak_n(2, top), weak_n(2, top) ** 2, weak_n(3, top),
              weak_n(3, top) ** 3, 8 * 8 * weak_n(3, top) ** 3 / 1e9, max(1, top // cpn)))
    A.append("Serial sweep: 2D n=%s, 3D n=%s; matrix dimension N from 4.1e3 to 6.7e7 and nonzeros 5N (2D) or 7N (3D), "
             "so at each N two nonzero counts are measured." % (SERIAL[2], SERIAL[3]))
    A.append("Iterations-to-tolerance (tol %g) for 2D n=%s and 3D n=%s: CG needs O(n) iterations (cond(A) = "
             "cot^2(pi h/2) ~ (2(n+1)/pi)^2), which is why fixed-iteration timing is used for scaling." %
             (TOL, SERIAL_TOL[2], SERIAL_TOL[3]))

    P.group("serial", "E2", "serial runtime vs problem size, 2D and 3D, matrix dimension and nonzeros varying")
    for d in (2, 3):
        for n in SERIAL[d]:
            P.cell("serial", d, n, 1)
    P.group("serial-tol", "E2", "serial iterations and time to tolerance vs n (how CG itself scales)")
    for d in (2, 3):
        for n in SERIAL_TOL[d]:
            P.cell("serial-tol", d, n, 1, mode="tol")

    variants = [("classic", "blocking"), ("pipelined", "overlap")]
    P.group("strong", "E3,E5", "strong scaling 1..%d ranks (1 thread), classic+blocking and pipelined+overlap" % top)
    P.group("weak", "E4,E5", "weak scaling 1..%d ranks (1 thread), ~2.1e6 unknowns per rank" % top)
    for d in (2, 3):
        for (cg, halo) in variants:
            for r in counts:
                nodes = max(1, -(-r // cpn))
                P.cell("strong", d, STRONG[d], r, nodes=nodes, cg=cg, halo=halo)
                P.cell("weak", d, weak_n(d, r), r, nodes=nodes, cg=cg, halo=halo)
    A.append("Strong/weak series run with two variants: classic CG + blocking halo (baseline) and pipelined CG + "
             "overlapped halo (communication hidden). Speedup S = T(1)/T(P), efficiency E = S/P (strong) and "
             "T(1)/T(P) (weak), each against the 1-rank run of the same variant.")

    P.group("variants", "E8,E5", "methods of parallelisation at %d and %d ranks: decomposition 1D/2D(/3D) x halo "
            "blocking/overlap x CG classic/pipelined" % (cpn, top))
    for r in (cpn, top):
        nodes = max(1, -(-r // cpn))
        for d in (2, 3):
            for dc in range(1, d + 1):
                for cg in ("classic", "pipelined"):
                    for halo in ("blocking", "overlap"):
                        P.cell("variants", d, STRONG[d], r, nodes=nodes, decomp=dc, cg=cg, halo=halo)
    A.append("Variants: full factorial at %d ranks (1 node) and %d ranks: 3D 3x2x2 = 12 cells, 2D 2x2x2 = 8 cells, "
             "per rank count; 1D slabs of the 3D grid at %d ranks are %.1f planes thick." %
             (cpn, top, top, STRONG[3] / top))

    lay_nodes = [1, max(1, top // cpn)]
    P.group("layout", "E6", "MPI+OpenMP: ranks x threads per %d-core node, on %s nodes" % (cpn, lay_nodes))
    for nn in lay_nodes:
        for (rpn, th) in layouts(cpn):
            for d in (2, 3):
                P.cell("layout", d, STRONG[d], rpn * nn, threads=th, nodes=nn)
    A.append("Layouts per node %s on 1 and %d nodes (strong grid, classic+blocking): same cores, fewer ranks -> "
             "fewer and larger halo messages and fewer ranks in each MPI_Allreduce." %
             (["%dx%d" % l for l in layouts(cpn)], lay_nodes[-1]))

    if has_gpu:
        P.group("gpu", "E7", "OpenMP target offload, 1 rank per GPU (X=OpenMP requires >= 1 GPU run)")
        for d in (2, 3):
            P.cell("gpu", d, STRONG[d], 1, gpus=1, binary="offload")
            P.cell("gpu", d, STRONG[d], 2, gpus=2, binary="offload")
        A.append("GPU: strong grids on 1 GPU and on 2 GPUs (2 ranks, one GPU each) of one GPU node; halos go "
                 "through host buffers (target update), so the 2-GPU run shows that cost.")

    # Jobs: one per node count (exclusive nodes), the 1-node work split so no job runs for hours.
    serial_cells = P.p["groups"]["serial"]["cells"] + P.p["groups"]["serial-tol"]["cells"]
    P.job("%s-validate" % name, 1, min(cpn, 8) if cpn > 8 else cpn, [], validate_first=True,
          note="build correct + planted-bug binaries on a compute node, qualify validate.py, record the hash",
          place="pack")
    P.job("%s-serial" % name, 1, cpn, serial_cells, note="serial sweep, whole node reserved so memory bandwidth is "
          "not shared")
    one = sorted(set(c for c in by_nodes(P).get(1, []) if c not in serial_cells))
    strong_weak_1 = [c for c in one if c in P.p["groups"]["strong"]["cells"] or c in P.p["groups"]["weak"]["cells"]]
    rest_1 = [c for c in one if c not in strong_weak_1]
    P.job("%s-1node-scaling" % name, 1, cpn, strong_weak_1, note="strong and weak scaling up to %d ranks" % cpn)
    P.job("%s-1node-variants-layouts" % name, 1, cpn, rest_1, note="variants and layouts on one node")
    for nn, cells in sorted(by_nodes(P).items()):
        if nn == 1:
            continue
        P.job("%s-%dnode" % (name, nn), nn, cpn, sorted(cells), note="all %d-node cells" % nn)
    if has_gpu:
        P.job("%s-gpu" % name, 1, 16, P.p["groups"]["gpu"]["cells"], binary="offload", gpus_per_node=2,
              validate_first=True, note="offload build + validation on the GPU node, then the GPU cells; "
              "ncpus/gpus per node are placeholders until `hpc gpu` shows the GPU node shape")
    return P


def build_local_plan():
    P = Plan("local", "local", 10, ["Development only: proves plan -> gate -> run -> record -> status -> figure on "
                                    "the Mac (Apple M5: 4 performance + 6 efficiency cores, shared memory "
                                    "bandwidth). Rows are labelled cluster=local and are refused by report figures."])
    P.p["repeats"] = REPEATS
    P.p["arithmetic"].append("Grids ~4.2e6 unknowns (2D n=2048, 3D n=161); ~0.5 s per 100-iteration run serially.")
    P.group("strong", "dev", "local strong scaling 1..8 ranks")
    P.group("layout", "dev", "local ranks x threads at 8 cores")
    for d, n in ((2, 2048), (3, 161)):
        for r in (1, 2, 4, 8):
            P.cell("strong", d, n, r)
            P.cell("strong", d, n, r, cg="pipelined", halo="overlap")
        for (rpn, th) in layouts(10):
            P.cell("layout", d, n, rpn, threads=th)
    P.job("local-smoke", 1, 10, sorted(P.p["cells"]), note="local smoke run of the timing pipeline")
    return P


def write(P):
    path = os.path.join(REPO, "config", "run_plan.%s.json" % P.p["plan"])
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
        if old.get("frozen"):
            print("REFUSED: %s is frozen; record changes as 'unplanned' or 'reruns' entries with a reason" % path)
            return 1
        # keep hand-entered fields across regeneration
        for k in ("core_hour_budget", "budget_source", "pbs", "unplanned", "reruns", "model"):
            if k in old:
                P.p[k] = old[k]
    with open(path, "w") as f:
        json.dump(P.p, f, indent=1, sort_keys=False)
        f.write("\n")
    print("wrote %s: %d cells, %d jobs" % (os.path.relpath(path, REPO), len(P.p["cells"]), len(P.p["jobs"])))
    return 0


def defaults(P):
    P.p.setdefault("core_hour_budget", None)
    P.p.setdefault("budget_source", "unknown until first login (Vanda allocation; Atlas is unlimited per Lecture 8)")
    P.p.setdefault("pbs", {"queue_cpu": "", "queue_gpu": "", "project": "", "place": "excl",
                           "note": "fill queue/project from `hpc cpu`, `hpc gpu` and `qstat -Qf` on first login"})
    P.p.setdefault("model", {
        "note": "core-hour estimate model; ASSUMED server values until the first cluster rows recalibrate them",
        "bytes_per_point_iter": {"classic": 96, "pipelined": 128},
        "bw_core_gbs": 10.0, "bw_node_gbs": 200.0, "bw_gpu_gbs": 800.0,
        "latency_s": 3e-6, "net_gbs": 10.0, "setup_s_per_point": 6e-8, "launch_s": 5.0,
        "tol_iters_per_n": 4.0, "job_overhead_s": 300.0, "safety": 2.0})
    return P


def main(argv):
    which = argv[1:] or ["vanda", "atlas", "local"]
    rc = 0
    for w in which:
        if w == "vanda":
            P = build_cluster_plan("vanda", 72, 4, True, [
                "Primary plan. 72 cores per CPU node (Lecture 9). Strong and weak to 288 cores = 4 nodes.",
                "GPU node shape (GPUs and CPU cores per node) unknown until `hpc gpu`; the gpu job is a placeholder "
                "shape."])
        elif w == "atlas":
            P = build_cluster_plan("atlas", 24, 11, False, [
                "Fallback if Vanda is down (circuit D5). 24 cores per node is UNVERIFIED (older NUS material); "
                "check `pbsnodes`/`qstat -Qf` and the queue's node and core caps before using this plan.",
                "Atlas has no GPUs: the GPU cell stays in the Vanda plan."])
        elif w == "local":
            P = build_local_plan()
        else:
            print("unknown plan %s" % w)
            return 2
        rc |= write(defaults(P))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
