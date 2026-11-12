#!/usr/bin/env python3
"""Validation of the graph solver bin/p3graph (and of the converter bin/p3convert): two named cases, and the
refusal of a planted ghost-exchange bug.

  python3 checks/validate_graph.py --binary bin/p3graph
      Runs G1 and G2 and prints PASS or REFUSED. Development use: records nothing.

  python3 checks/validate_graph.py --qualify --binary bin/p3graph --bug-binary bin/p3graph_bug1
      The binding form (case G3): the check qualifies only if it PASSES the correct build AND REFUSES the planted-bug
      build (PLANT_GHOST_BUG=1: each rank's ghosts from its first source neighbour are never stored). Only then is
      the correct binary's sha256 appended to results/validated_binaries.csv with cases "G1;G2", which the timing
      gate (checks/timing_gate.py --require-cases G1,G2) and the figure loader require.

G1 needs DATA/csr/email-Eu-core.{natural,bfs}.{csr,cmty} (scripts/convert_snap.sh email-Eu-core); DATA is --data,
else P3_DATA, else the repository's data/, else ~/p3data. G2 builds its own tiny graph with --convert.
Output: results/validation/<cluster>/<utc>-graph.{txt,csv,json}. Standard library only, Python >= 3.6.
"""
import argparse
import array
import bisect
import datetime
import json
import math
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3common as C  # noqa: E402

AGREE_ITERS = 10
AGREE_TOL = 1e-10
SPMV_TOL = 1e-14
CONV_TOL = 1e-12
AGREE_WHY = ("SpMV: every y_i = (d_i + a) x_i - sum of the neighbours' x_j is the same floating-point sum in every "
             "partition and exchange (rows keep their neighbour order), so natural-order layouts agree bitwise and "
             "the BFS-numbered file, whose rows list the same neighbours in another order, agrees to rounding "
             "(~1e-15); %.0e leaves a margin, while one missing ghost changes y_i by a whole x_j. CG after %d "
             "iterations: runs differ only in the order in which the dot products' partial sums are added (~1e-15 "
             "here); %.0e is far above that and far below the effect of one wrong ghost. Measured on email-Eu-core, "
             "that rounding difference grows about 1000x every 5 iterations once CG has resolved the hub eigenvalues "
             "(1e-13 at 15, 1e-10 at 20, 1e-7 at 25 iterations; also between 1 and 2 threads on one rank), so a fixed-"
             "iteration comparison is sharp only up to ~10 iterations. Converged answers are compared like V5: "
             "||x_P - x_1||/||x_1|| <= c (rho_P + rho_1)/(1 - c rho_1), rho = true relative residual, with "
             "c = (2 d_max + a)/a >= cond(L + aI) (Gershgorin: lambda_max(L) <= 2 d_max)"
             % (SPMV_TOL, AGREE_ITERS, AGREE_TOL))
DENSE_A, DENSE_TOL, DENSE_SOLVE_TOL = 0.5, 1e-10, 1e-13
DENSE_WHY = ("for the tiny graph cond(L + aI) <= (2 d_max + a)/a = 21 (d_max = 5, a = %.1f), and the solves stop at a "
             "relative residual of %.0e, so the relative error is at most ~21 x %.0e = 2e-12; %.0e leaves a 50x "
             "margin; a lost ghost or a wrong edge changes x by more than 1e-3" %
             (DENSE_A, DENSE_SOLVE_TOL, DENSE_SOLVE_TOL, DENSE_TOL))

# G2's hand-made graph, in SNAP's text format: two 5-cliques {1..5} and {11..15}, a bridge 5-11, a tail 15-20-21,
# vertex 30 with only a self-loop (it must stay as an isolated vertex), the self-loop 3-3 and the duplicate 2-1.
TINY_EDGES = ([(i, j) for i in range(1, 6) for j in range(i + 1, 6)] +
              [(i, j) for i in range(11, 16) for j in range(i + 1, 16)] +
              [(5, 11), (15, 20), (20, 21), (3, 3), (2, 1), (30, 30)])
TINY_CMTY = [[1, 2, 3, 4, 5], [11, 12, 13, 14, 15, 20, 21], [30]]
TINY_EXPECT = {"vertices": 13, "edges": 23, "self_loops_dropped": 2, "duplicate_entries_dropped": 2,
               "isolated_vertices": 1, "communities": 3, "max_degree": 5}


class Runner:
    def __init__(self, binary, launcher, workdir, record_path, timeout=900):
        self.binary, self.launcher, self.workdir, self.record_path, self.timeout = (binary, launcher, workdir,
                                                                                     record_path, timeout)
        self.count = 0

    def run(self, graph, np=1, threads=1, order="natural", part="nnz", exchange="neighbor", cg="classic",
            extra=(), dump=True, spmv=False, seeds=False):
        """Runs p3graph once; returns (record row, {"x": array, "y": array, "seeds": text})."""
        self.count += 1
        w = lambda s: os.path.join(self.workdir, "%s%03d" % (s, self.count))  # noqa: E731
        rec = w("r") + ".csv"
        cmd = self.launcher + ["-np", str(np), self.binary, "--graph", graph, "--order", order, "--part", part,
                               "--exchange", exchange, "--cg", cg, "--record", rec, "--quiet", "--cell", "validate",
                               "--tag", "validate-graph"] + list(extra)
        if dump:
            cmd += ["--dump", w("x") + ".bin"]
        if spmv:
            cmd += ["--spmv-dump", w("y") + ".bin"]
        if seeds:
            cmd += ["--write-seeds", w("s") + ".txt"]
        env = dict(os.environ)
        env["OMP_NUM_THREADS"] = str(threads)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           universal_newlines=True, env=env, timeout=self.timeout)
        if p.returncode != 0 or not os.path.exists(rec):
            raise RuntimeError("solver failed (exit %d): %s\n%s" % (p.returncode, " ".join(cmd), p.stdout[-2000:]))
        with open(rec) as f:
            header = f.readline().strip().split(",")
        if header != C.GRAPH_COLUMNS:
            raise RuntimeError("record header is not the %s schema of checks/p3common.py" % C.GRAPH_SCHEMA)
        row = C.read_csv(rec)[-1]
        C.append_csv(self.record_path, C.GRAPH_COLUMNS, row)
        out = {}
        for key, path in (("x", w("x") + ".bin"), ("y", w("y") + ".bin")):
            if os.path.exists(path):
                a = array.array("d")
                with open(path, "rb") as f:
                    a.frombytes(f.read())
                out[key] = a
                os.remove(path)
        if seeds:
            with open(w("s") + ".txt") as f:
                out["seeds"] = f.read()
        os.remove(rec)
        return row, out


def csr_orig(path):
    """SNAP ids of the vertices of a .csr file, in its vertex order."""
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic != b"P3CSR001":
            raise RuntimeError("%s is not a P3CSR001 file" % path)
        V, nnz, _, _ = struct.unpack("<4q", f.read(32))
        f.seek(40 + 8 * (V + 1) + 4 * nnz)
        a = array.array("q")
        a.frombytes(f.read(8 * V))
    return list(a)


def to_natural(vec, orig_from, orig_nat):
    """Re-indexes per-vertex blocks of vec (len = k*V) from one vertex order to the natural order."""
    V = len(orig_nat)
    pos = [bisect.bisect_left(orig_nat, o) for o in orig_from]
    out = array.array("d", [0.0]) * len(vec)
    for b in range(len(vec) // V):
        for i, p in enumerate(pos):
            out[b * V + p] = vec[b * V + i]
    return out


def rel_diff(a, b):
    num = math.sqrt(sum((p - q) * (p - q) for p, q in zip(a, b)))
    den = math.sqrt(sum(q * q for q in b)) or 1.0
    return num / den if len(a) == len(b) else float("inf")


def layout(np, th, order, part, ex, cg):
    return "ranks=%d threads=%d order=%-7s part=%-4s exchange=%-9s cg=%s" % (np, th, order, part, ex, cg)


# ------------------------------------------------------------------------------------------------------------------
def case_agree(R, data, out, log):
    g = os.path.join(data, "csr", "email-Eu-core")
    for o in ("natural", "bfs"):
        for ext in (".csr", ".cmty"):
            if not os.path.exists(g + "." + o + ext):
                raise RuntimeError("missing %s.%s%s: run scripts/convert_snap.sh email-Eu-core first" % (g, o, ext))
    orig_nat, orig_bfs = csr_orig(g + ".natural.csr"), csr_orig(g + ".bfs.csr")
    it = ["--iters", str(AGREE_ITERS), "--rhs", "2"]
    ok, worst_y, worst_x = True, 0.0, 0.0
    for cg, layouts in (("classic", [(2, 1, "natural", "rows", "alltoallv"), (3, 1, "natural", "nnz", "neighbor"),
                                     (4, 1, "natural", "rows", "overlap"), (4, 2, "natural", "nnz", "alltoallv"),
                                     (5, 1, "bfs", "nnz", "neighbor"), (3, 2, "bfs", "rows", "overlap")]),
                        ("pipelined", [(4, 1, "natural", "nnz", "overlap"), (3, 1, "bfs", "rows", "neighbor")])):
        r0, ref = R.run(g, np=1, cg=cg, extra=it, spmv=True)
        out("    reference %s: 1 rank, email-Eu-core (V=%s, E=%s), y = (L+aI)v and %d iterations on 2 right-hand "
            "sides" % (cg, r0["vertices"], r0["edges"], AGREE_ITERS))
        for (np, th, order, part, ex) in layouts:
            row, res = R.run(g, np=np, threads=th, order=order, part=part, exchange=ex, cg=cg, extra=it, spmv=True)
            y, x = res.get("y", []), res.get("x", [])
            if order == "bfs":
                y, x = to_natural(y, orig_bfs, orig_nat), to_natural(x, orig_bfs, orig_nat)
            dy, dx = rel_diff(y, ref["y"]), rel_diff(x, ref["x"])
            ghosts = int(row["ghosts_sum"])
            good = dy <= SPMV_TOL and dx <= AGREE_TOL and ghosts > 0
            worst_y, worst_x = max(worst_y, dy), max(worst_x, dx)
            ok = ok and good
            log.append({"kind": "agree", "cg": cg, "ranks": np, "threads": th, "order": order, "part": part,
                        "exchange": ex, "spmv_diff": dy, "x_diff": dx, "ghosts": ghosts,
                        "edge_cut": int(row["edge_cut"]), "nnz_imbalance": float(row["nnz_imbalance"]), "ok": good})
            out("    %s  SpMV %.2e  x %.2e  (cut %s edges, %s ghosts)  %s" %
                (layout(np, th, order, part, ex, cg), dy, dx, row["edge_cut"], ghosts, "ok" if good else
                 ("NO GHOSTS EXCHANGED" if ghosts == 0 else "TOO LARGE")))
    out("    largest differences: SpMV %.2e (tolerance %.0e), x after %d iterations %.2e (tolerance %.0e)" %
        (worst_y, SPMV_TOL, AGREE_ITERS, worst_x, AGREE_TOL))
    # Converged answers (all K = 10 systems, tol 1e-12), against the condition-number bound.
    conv = ["--tol", repr(CONV_TOL), "--maxit", "5000"]
    r1, s1 = R.run(g, np=1, extra=conv)
    rho1, c = float(r1["true_rel_res"]), (2 * float(r1["max_degree"]) + 1.0) / 1.0
    out("    converged reference: 1 rank classic, K=%s systems to tol %.0e: %s iterations, true residual %.1e, "
        "accuracy %.4f; c = (2 d_max + a)/a = %.0f" % (r1["K"], CONV_TOL, r1["iters"], rho1, float(r1["accuracy"]), c))
    for (np, order, part, ex, cg) in ((4, "natural", "rows", "overlap", "classic"),
                                      (3, "bfs", "nnz", "neighbor", "pipelined")):
        row, res = R.run(g, np=np, order=order, part=part, exchange=ex, cg=cg, extra=conv)
        x = res["x"] if order == "natural" else to_natural(res["x"], orig_bfs, orig_nat)
        rho = float(row["true_rel_res"])
        d = rel_diff(x, s1["x"])
        den = 1.0 - c * rho1
        bound = c * (rho + rho1) / den if den > 0 else float("inf")
        good = row["converged"] == "1" and d <= bound
        ok = ok and good
        log.append({"kind": "converged", "ranks": np, "order": order, "part": part, "exchange": ex, "cg": cg,
                    "diff": d, "bound": bound, "rho": rho, "rho_ref": rho1, "accuracy": float(row["accuracy"]),
                    "accuracy_ref": float(r1["accuracy"]), "ok": good})
        out("    %s  converged: diff %.2e <= bound %.2e (true residual %.1e), accuracy %.4f  %s" %
            (layout(np, 1, order, part, ex, cg), d, bound, rho, float(row["accuracy"]), "ok" if good else "FAILS"))
    return ok


def dense_solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def case_dense(R, convert, workdir, out, log):
    d = os.path.join(workdir, "tiny")
    os.makedirs(d)
    with open(os.path.join(d, "tiny.txt"), "w") as f:
        f.write("# G2 test graph (SNAP format)\n# FromNodeId\tToNodeId\n")
        for u, v in TINY_EDGES:
            f.write("%d\t%d\n" % (u, v))
    with open(os.path.join(d, "tiny.cmty"), "w") as f:
        for c in TINY_CMTY:
            f.write("\t".join(str(v) for v in c) + "\n")
    p = subprocess.run([convert, "--edges", os.path.join(d, "tiny.txt"), "--cmty", os.path.join(d, "tiny.cmty"),
                        "--out", os.path.join(d, "tiny"), "--name", "tiny"], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("p3convert failed: %s" % p.stdout[-500:])
    with open(os.path.join(d, "tiny.meta.json")) as f:
        meta = json.load(f)
    ok = True
    bad = ["%s=%s (expected %s)" % (k, meta.get(k), v) for k, v in TINY_EXPECT.items() if meta.get(k) != v]
    ok = ok and not bad
    log.append({"kind": "convert", "meta": meta, "expected": TINY_EXPECT, "ok": not bad})
    out("    converter: V=%s E=%s self-loops dropped=%s duplicate entries dropped=%s isolated=%s  %s" %
        (meta.get("vertices"), meta.get("edges"), meta.get("self_loops_dropped"),
         meta.get("duplicate_entries_dropped"), meta.get("isolated_vertices"),
         "ok (as constructed)" if not bad else "WRONG: " + "; ".join(bad)))
    # The validator's own matrix, from the edge list above (not from the converter's output).
    ids = sorted(set(v for e in TINY_EDGES for v in e))
    ix = dict((v, i) for i, v in enumerate(ids))
    V = len(ids)
    E = set((min(u, v), max(u, v)) for u, v in TINY_EDGES if u != v)
    A = [[0.0] * V for _ in range(V)]
    for u, v in E:
        A[ix[u]][ix[v]] = A[ix[v]][ix[u]] = -1.0
    for i in range(V):
        A[i][i] = DENSE_A - sum(A[i][j] for j in range(V) if j != i)
    g = os.path.join(d, "tiny")
    orig_nat, orig_bfs = csr_orig(g + ".natural.csr"), csr_orig(g + ".bfs.csr")
    common = ["--K", "2", "--s", "1", "--a", repr(DENSE_A), "--tol", repr(DENSE_SOLVE_TOL), "--maxit", "1000"]
    ref = None
    for (np, order, part, ex, cg) in ((1, "natural", "nnz", "neighbor", "classic"),
                                      (3, "natural", "rows", "neighbor", "classic"),
                                      (3, "natural", "nnz", "overlap", "pipelined"),
                                      (2, "bfs", "rows", "alltoallv", "classic")):
        row, res = R.run(g, np=np, order=order, part=part, exchange=ex, cg=cg, extra=common, seeds=True)
        if ref is None:
            seeds = [[int(t) for t in line.split("seeds=")[1].split(",")] for line in res["seeds"].splitlines()
                     if line.startswith("c=")]
            ref = []
            for sc in seeds:
                b = [0.0] * V
                for sid in sc:
                    b[ix[sid]] = 1.0
                ref += dense_solve(A, b)
        x = res["x"]
        if order == "bfs":
            x = to_natural(x, orig_bfs, orig_nat)
        dx = rel_diff(x, ref)
        acc = float(row["accuracy"])
        good = dx <= DENSE_TOL and row["converged"] == "1" and acc == 1.0 and (np == 1 or int(row["ghosts_sum"]) > 0)
        ok = ok and good
        log.append({"kind": "dense", "ranks": np, "order": order, "part": part, "exchange": ex, "cg": cg,
                    "diff": dx, "iters": int(row["iters"]), "true_rel_res": float(row["true_rel_res"]),
                    "accuracy": acc, "ok": good})
        out("    %s  ||x - x_dense||/||x_dense|| = %.2e  true residual %.1e  accuracy %.2f  %s" %
            (layout(np, 1, order, part, ex, cg), dx, float(row["true_rel_res"]), acc, "ok" if good else "FAILS"))
    return ok


CASES = [
    ("G1", "agree-email", "on email-Eu-core, the parallel SpMV and 10 CG iterations (classic and pipelined; 2-5 ranks, "
     "threads; rows/nnz partitions; alltoallv/neighbor/overlap exchange; natural and BFS order) equal the 1-rank run "
     "to rounding, and converged parallel answers are within the condition-number bound of the 1-rank answer", AGREE_WHY, lambda R, a, out, log: case_agree(R, a.data, out, log)),
    ("G2", "dense-tiny", "on a hand-made graph (two 5-cliques, a bridge, a tail, a self-loop, a duplicate edge), the "
     "converter's counts are as constructed and x matches a dense solve on 1-3 ranks; labels are all correct",
     DENSE_WHY, lambda R, a, out, log: case_dense(R, a.convert, R.workdir, out, log)),
]


def run_cases(binary, launcher, record_path, args, out, details):
    failed = []
    with tempfile.TemporaryDirectory(prefix="p3gval_") as wd:
        R = Runner(binary, launcher, wd, record_path)
        for cid, name, purpose, why, fn in CASES:
            out("  %s %s: %s" % (cid, name, purpose))
            log = []
            try:
                ok = fn(R, args, out, log)
            except Exception as e:  # a crash or a missing output refuses the binary
                out("    ERROR: %s" % str(e).splitlines()[0])
                ok = False
            out("    -> %s" % ("PASS" if ok else "FAIL"))
            details[cid] = {"name": name, "ok": ok, "items": log}
            if not ok:
                failed.append(cid)
        return (not failed), failed, R.count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--qualify", action="store_true", help="also require every --bug-binary to be refused (G3)")
    ap.add_argument("--bug-binary", action="append", default=[])
    ap.add_argument("--convert", default=os.path.join(C.REPO, "bin", "p3convert"))
    ap.add_argument("--data", default=C.DATA)
    ap.add_argument("--launcher", default=None, help="mpirun prefix (default: P3_MPIRUN or detected)")
    args = ap.parse_args()
    if args.qualify and not args.bug_binary:
        ap.error("--qualify needs at least one --bug-binary")
    launcher = args.launcher.split() if args.launcher else C.default_launcher()
    binary = os.path.abspath(args.binary)
    args.convert = os.path.abspath(args.convert)
    sha = C.sha256_file(binary)
    ver = C.binary_version(binary, launcher)
    if ver.get("sha256") != sha:
        print("REFUSED: %s --version reports sha256=%s, file hash is %s" % (binary, ver.get("sha256"), sha))
        return 2
    if "graph=1" not in ver.get("build", "") or "bug=0" not in ver.get("build", ""):
        print("REFUSED: %s is not a correct p3graph build (%s)" % (binary, ver.get("build")))
        return 2
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = []

    def out(s=""):
        print(s)
        sys.stdout.flush()
        lines.append(s)

    me = C.sha256_file(os.path.abspath(__file__))
    tmp_records = os.path.join(C.RESULTS, "validation", "_pending_%s%s" % (stamp, C.GRAPH_SUFFIX))
    out("validate_graph.py  %s  (sha256 of validate_graph.py: %s)" % (stamp, me))
    out("launcher: %s" % " ".join(launcher))
    out("data: %s   converter: %s (sha256 %s)" % (args.data, args.convert, C.sha256_file(args.convert)))
    out("%d cases + the planted-bug refusal (G3); tolerances and their reasons:" % len(CASES))
    out("  agree: %s" % AGREE_WHY)
    out("  dense: %s" % DENSE_WHY)
    out()
    out("CORRECT BUILD  %s" % binary)
    out("  sha256 %s" % sha)
    out("  build  %s" % ver.get("build"))
    summary = {"stamp": stamp, "validate_sha256": me, "launcher": " ".join(launcher), "data": args.data,
               "convert": {"path": args.convert, "sha256": C.sha256_file(args.convert)},
               "tolerances": {"agree_iters": AGREE_ITERS, "agree_tol": AGREE_TOL, "spmv_tol": SPMV_TOL, "conv_tol": CONV_TOL,
                              "dense_tol": DENSE_TOL, "dense_solve_tol": DENSE_SOLVE_TOL, "dense_a": DENSE_A},
               "cases": [{"id": c[0], "name": c[1], "purpose": c[2], "why": c[3]} for c in CASES],
               "correct": {}, "bugs": []}
    cdet = {}
    passed, failed, nruns = run_cases(binary, launcher, tmp_records, args, out, cdet)
    summary["correct"] = {"binary": binary, "sha256": sha, "build": ver.get("build", ""), "passed": passed,
                          "failed": failed, "runs": nruns, "details": cdet}
    out("  VERDICT correct build: %s  (%d/%d cases, %d solver runs)" %
        ("PASS" if passed else "REFUSED (failed: %s)" % ", ".join(failed), len(CASES) - len(failed), len(CASES),
         nruns))
    refused_all, bug_summ = True, []
    for bb in args.bug_binary:
        bb = os.path.abspath(bb)
        bsha, bver = C.sha256_file(bb), C.binary_version(bb, launcher)
        out()
        out("G3 PLANTED-BUG BUILD  %s" % bb)
        out("  sha256 %s" % bsha)
        out("  build  %s" % bver.get("build"))
        if "bug=0" in bver.get("build", "") or "graph=1" not in bver.get("build", ""):
            out("  this is not a planted-bug p3graph build; it cannot qualify the check")
            refused_all = False
            continue
        bdet = {}
        bpass, bfailed, bruns = run_cases(bb, launcher, tmp_records, args, out, bdet)
        summary["bugs"].append({"binary": bb, "sha256": bsha, "build": bver.get("build", ""), "refused": not bpass,
                                "refused_by": bfailed, "runs": bruns, "details": bdet})
        if bpass:
            refused_all = False
            out("  VERDICT planted bug: PASSED  <- the check did NOT refuse it")
        else:
            out("  VERDICT planted bug: REFUSED by %s  (%d solver runs)" % (", ".join(bfailed), bruns))
            bug_summ.append("%s:%s" % (os.path.basename(bb), "+".join(bfailed)))
    rows = C.read_csv(tmp_records) if os.path.exists(tmp_records) else []
    cluster = rows[0]["cluster"] if rows else "local"
    host = rows[0]["host"] if rows else "?"
    vdir = os.path.join(C.RESULTS, "validation", cluster)
    if not os.path.isdir(vdir):
        os.makedirs(vdir)
    if os.path.exists(tmp_records):
        os.rename(tmp_records, os.path.join(vdir, "%s%s" % (stamp, C.GRAPH_SUFFIX)))
    out()
    qualified = bool(args.qualify and passed and refused_all)
    if args.qualify:
        out("QUALIFICATION: correct build %s; planted bug %s -> check %s" %
            ("PASSED" if passed else "FAILED", "REFUSED (G3)" if refused_all else "NOT refused",
             "QUALIFIED" if qualified else "NOT QUALIFIED"))
        if qualified:
            C.append_csv(C.VALIDATED, C.VALIDATED_COLUMNS, {
                "utc": stamp, "cluster": cluster, "host": host, "binary_sha256": sha, "binary": binary,
                "build": ver.get("build", ""), "validate_sha256": me, "cases": ";".join(c[0] for c in CASES),
                "bug_binaries_refused": ";".join(bug_summ), "verdict": "QUALIFIED"})
            out("VALIDATED BINARY sha256=%s (cluster=%s, cases G1;G2) -> %s" %
                (sha, cluster, os.path.relpath(C.VALIDATED, C.REPO)))
            out("Graph timing runs (timing_gate.py --require-cases G1,G2) and graph figures accept only this hash.")
    else:
        out("RESULT: %s (development run; nothing recorded; use --qualify to validate a binary)" %
            ("PASS" if passed else "REFUSED"))
    with open(os.path.join(vdir, "%s-graph.txt" % stamp), "w") as f:
        f.write("\n".join(lines) + "\n")
    summary.update({"cluster": cluster, "host": host, "mode": "qualify" if args.qualify else "development",
                    "qualified": qualified})
    with open(os.path.join(vdir, "%s-graph.json" % stamp), "w") as f:
        json.dump(summary, f, indent=1)
    print("output kept in %s" % os.path.relpath(os.path.join(vdir, "%s-graph.txt" % stamp), C.REPO))
    if args.qualify:
        return 0 if qualified else 1
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
