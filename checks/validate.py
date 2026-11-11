#!/usr/bin/env python3
"""Validation of the CG solver: a small, named set of cases, each with a one-line purpose.

  python3 checks/validate.py --binary bin/p3cg
      Runs the cases and prints PASS or REFUSED. Development use: records nothing.

  python3 checks/validate.py --qualify --binary bin/p3cg --bug-binary bin/p3cg_bug1 --bug-binary bin/p3cg_bug2
      The binding form. The check qualifies only if it PASSES the correct build AND REFUSES every planted-bug
      build. Only then is the correct binary's sha256 appended to results/validated_binaries.csv, which the timing
      gate (checks/timing_gate.py) and the figure loader (checks/run_record.py) require.

The output is also written to results/validation/<cluster>/<utc>.txt and the solver rows to the matching .csv.
Standard library only, Python >= 3.6.
"""
import argparse
import array
import datetime
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3common as C  # noqa: E402

# ------------------------------------------------------------------------------------------------------------------
# Tolerances, with their reasons (printed with the cases).
# ------------------------------------------------------------------------------------------------------------------
ORDER_BAND = (1.9, 2.1)
ORDER_WHY = ("the 5-/7-point stencil is second order, so halving h divides the error by 4 (order 2); "
             "solves use tol 1e-12 so the algebraic error is far below the discretisation error")
AGREE_ITERS = 25
AGREE_TOL = 1e-10
AGREE_WHY = ("after the same %d iterations, a P-rank run differs from the 1-rank run only in the order in which "
             "the partial sums of each dot product are added (the stencil and vector updates are the same "
             "operations on the same numbers once the halos are right); CG amplifies those last-bit differences "
             "to ~1e-13 here. %.0e leaves a margin of more than 100x over that and is ~9 orders below the effect "
             "of one wrong halo face (~0.5)" % (AGREE_ITERS, AGREE_TOL))
PIPE_TOL = 1e-10
PIPE_WHY = ("pipelined CG uses different recurrences, so its iterates are not rounding-equal to classic CG; "
            "only converged answers can be compared. For any x, ||x - x*||/||x*|| <= cond(A) ||b - Ax||/||b||, "
            "with cond(A) = cot^2(pi h/2) for this operator, so two converged answers must satisfy "
            "||x_p - x_s||/||x_s|| <= cond(A) (rho_p + rho_s) / (1 - cond(A) rho_s), rho = true relative residual")


class Runner:
    def __init__(self, binary, launcher, workdir, record_path, timeout=600):
        self.binary = binary
        self.launcher = launcher
        self.workdir = workdir
        self.record_path = record_path
        self.timeout = timeout
        self.count = 0

    def run(self, dim, n, np=1, threads=1, decomp=None, cg="classic", halo="blocking", iters=None, tol=None,
            maxit=None, tag="validate"):
        """Runs the solver once; returns (record row dict, solution array)."""
        self.count += 1
        dump = os.path.join(self.workdir, "x%03d.bin" % self.count)
        rec = os.path.join(self.workdir, "r%03d.csv" % self.count)
        cmd = self.launcher + ["-np", str(np), self.binary, "--dim", str(dim), "--n", str(n), "--cg", cg,
                               "--halo", halo, "--record", rec, "--dump", dump, "--quiet", "--tag", tag,
                               "--cell", "validate"]
        if decomp is not None:
            cmd += ["--decomp", str(decomp)]
        if iters is not None:
            cmd += ["--iters", str(iters)]
        if tol is not None:
            cmd += ["--tol", repr(tol)]
        if maxit is not None:
            cmd += ["--maxit", str(maxit)]
        env = dict(os.environ)
        env["OMP_NUM_THREADS"] = str(threads)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                           env=env, timeout=self.timeout)
        if p.returncode != 0 or not os.path.exists(rec) or not os.path.exists(dump):
            raise RuntimeError("solver failed (exit %d): %s\n%s" % (p.returncode, " ".join(cmd), p.stdout[-2000:]))
        row = C.read_csv(rec)[-1]
        # Keep every solver row of this validation as evidence.
        C.append_csv(self.record_path, C.RECORD_COLUMNS, row)
        x = array.array("d")
        with open(dump, "rb") as f:
            x.frombytes(f.read())
        os.remove(dump)
        os.remove(rec)
        return row, x


def rel_diff(a, b):
    num = math.sqrt(sum((p - q) * (p - q) for p, q in zip(a, b)))
    den = math.sqrt(sum(q * q for q in b))
    return num / den


def cond_A(n):
    h = 1.0 / (n + 1)
    return 1.0 / math.tan(math.pi * h / 2) ** 2


def layout(np, threads, decomp, halo, cg="classic"):
    return "ranks=%d threads=%d decomp=%dD halo=%-8s cg=%s" % (np, threads, decomp, halo, cg)


# ------------------------------------------------------------------------------------------------------------------
# Cases
# ------------------------------------------------------------------------------------------------------------------
def case_order(R, dim, ns, out):
    errs, ok = [], True
    for n in ns:
        row, _ = R.run(dim, n, tol=1e-12, maxit=20000)
        e = float(row["err_max"])
        errs.append(e)
        conv = row["converged"] == "1"
        ok = ok and conv
        out("    n=%-4d h=1/%-4d iters=%-5s converged=%s  max|x - u_exact| = %.4e" %
            (n, n + 1, row["iters"], "yes" if conv else "NO", e))
    for i in range(len(ns) - 1):
        p = math.log(errs[i] / errs[i + 1]) / math.log((ns[i + 1] + 1) / (ns[i] + 1))
        inside = ORDER_BAND[0] <= p <= ORDER_BAND[1]
        ok = ok and inside
        out("    observed order h=1/%d -> 1/%d: %.3f  (%s [%.1f, %.1f])" %
            (ns[i] + 1, ns[i + 1] + 1, p, "in" if inside else "OUTSIDE", ORDER_BAND[0], ORDER_BAND[1]))
    return ok


def case_agree(R, dim, n, layouts, out):
    _, ref = R.run(dim, n, np=1, iters=AGREE_ITERS)
    out("    reference: 1 rank, 1 thread, n=%d, %d iterations" % (n, AGREE_ITERS))
    ok, worst = True, 0.0
    for (np, th, dc, halo) in layouts:
        _, x = R.run(dim, n, np=np, threads=th, decomp=dc, halo=halo, iters=AGREE_ITERS)
        d = rel_diff(x, ref)
        worst = max(worst, d)
        good = d <= AGREE_TOL
        ok = ok and good
        out("    %s  ||x_P - x_1||/||x_1|| = %.3e  %s" % (layout(np, th, dc, halo), d, "ok" if good else "TOO LARGE"))
    out("    largest difference %.3e (tolerance %.0e)" % (worst, AGREE_TOL))
    return ok


def case_pipelined(R, specs, out):
    ok = True
    for (dim, n) in specs:
        rs, xs = R.run(dim, n, np=1, tol=PIPE_TOL, maxit=20000)
        rho_s = float(rs["true_rel_res"])
        kappa = cond_A(n)
        out("    %dD n=%d classic, 1 rank:   iters=%-4s true residual %.2e   (cond(A) = %.0f)" %
            (dim, n, rs["iters"], rho_s, kappa))
        ok = ok and rs["converged"] == "1"
        for (np, halo) in ((1, "blocking"), (4, "overlap")):
            rp, xp = R.run(dim, n, np=np, decomp=dim, halo=halo, cg="pipelined", tol=PIPE_TOL, maxit=20000)
            rho_p = float(rp["true_rel_res"])
            conv = rp["converged"] == "1"
            d = rel_diff(xp, xs)
            denom = 1.0 - kappa * rho_s
            bound = kappa * (rho_p + rho_s) / denom if denom > 0 else float("inf")
            # Convergence is judged on the true residual too: the recursive one can drift (pipelined CG).
            good = conv and rho_p <= 10 * PIPE_TOL and d <= bound
            ok = ok and good
            out("    %dD n=%d pipelined, %d rank%s %-8s iters=%-4s true residual %.2e  diff %.2e <= bound %.2e  %s" %
                (dim, n, np, "s" if np > 1 else " ", halo, rp["iters"], rho_p, d, bound,
                 "ok" if good else ("NOT CONVERGED" if not conv else "FAILS")))
    return ok


CASES = [
    ("V1", "order-2d", "2D serial solver converges and its error against the exact solution falls as h^2",
     ORDER_WHY, lambda R, out: case_order(R, 2, [31, 63, 127], out)),
    ("V2", "order-3d", "3D serial solver converges and its error against the exact solution falls as h^2",
     ORDER_WHY, lambda R, out: case_order(R, 3, [15, 31, 63], out)),
    ("V3", "agree-2d", "2D parallel runs (1D/2D splits, uneven blocks, both halo variants, threads) equal the "
     "serial run to rounding", AGREE_WHY,
     lambda R, out: case_agree(R, 2, 50, [(2, 1, 1, "blocking"), (3, 1, 1, "overlap"), (4, 1, 2, "blocking"),
                                          (6, 1, 2, "overlap"), (2, 2, 2, "overlap")], out)),
    ("V4", "agree-3d", "3D parallel runs (1D/2D/3D splits, uneven blocks, both halo variants, threads) equal the "
     "serial run to rounding", AGREE_WHY,
     lambda R, out: case_agree(R, 3, 21, [(4, 1, 1, "blocking"), (4, 1, 2, "overlap"), (6, 1, 3, "overlap"),
                                          (8, 1, 3, "blocking"), (8, 1, 3, "overlap"), (2, 2, 3, "blocking")], out)),
    ("V5", "pipelined", "pipelined CG (1 and 4 ranks) reaches the same converged answer as classic CG, 2D and 3D",
     PIPE_WHY, lambda R, out: case_pipelined(R, [(2, 63), (3, 31)], out)),
]


def run_cases(binary, launcher, record_path, out):
    """Runs every case on one binary. Returns (passed, failed case ids, number of solver runs)."""
    failed = []
    with tempfile.TemporaryDirectory(prefix="p3val_") as wd:
        R = Runner(binary, launcher, wd, record_path)
        for cid, name, purpose, why, fn in CASES:
            out("  %s %s: %s" % (cid, name, purpose))
            try:
                ok = fn(R, out)
            except Exception as e:  # a crash or a missing output refuses the binary
                out("    ERROR: %s" % str(e).splitlines()[0])
                ok = False
            out("    -> %s" % ("PASS" if ok else "FAIL"))
            if not ok:
                failed.append(cid)
        return (not failed), failed, R.count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--qualify", action="store_true", help="also require every --bug-binary to be refused")
    ap.add_argument("--bug-binary", action="append", default=[])
    ap.add_argument("--launcher", default=None, help="mpirun prefix (default: P3_MPIRUN or detected)")
    args = ap.parse_args()
    if args.qualify and not args.bug_binary:
        ap.error("--qualify needs at least one --bug-binary")

    launcher = args.launcher.split() if args.launcher else C.default_launcher()
    binary = os.path.abspath(args.binary)
    sha = C.sha256_file(binary)
    ver = C.binary_version(binary, launcher)
    if ver.get("sha256") != sha:
        print("REFUSED: %s --version reports sha256=%s, file hash is %s" % (binary, ver.get("sha256"), sha))
        return 2
    if "bug=0" not in ver.get("build", ""):
        print("REFUSED: %s is a planted-bug build (%s)" % (binary, ver.get("build")))
        return 2

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = []

    def out(s=""):
        print(s)
        sys.stdout.flush()
        lines.append(s)

    tmp_records = os.path.join(C.RESULTS, "validation", "_pending_%s.csv" % stamp)
    out("validate.py  %s  (sha256 of validate.py: %s)" % (stamp, C.sha256_file(os.path.abspath(__file__))))
    out("launcher: %s" % " ".join(launcher))
    out("%d cases; tolerances and their reasons:" % len(CASES))
    out("  order:     observed order in [%.1f, %.1f]: %s" % (ORDER_BAND[0], ORDER_BAND[1], ORDER_WHY))
    out("  agree:     relative 2-norm difference <= %.0e: %s" % (AGREE_TOL, AGREE_WHY))
    out("  pipelined: %s" % PIPE_WHY)
    out()
    out("CORRECT BUILD  %s" % binary)
    out("  sha256 %s" % sha)
    out("  build  %s" % ver.get("build"))
    passed, failed, nruns = run_cases(binary, launcher, tmp_records, out)
    out("  VERDICT correct build: %s  (%d/%d cases, %d solver runs)" %
        ("PASS" if passed else "REFUSED (failed: %s)" % ", ".join(failed), len(CASES) - len(failed), len(CASES),
         nruns))

    refused_all = True
    bug_summ = []
    for bb in args.bug_binary:
        bb = os.path.abspath(bb)
        bsha = C.sha256_file(bb)
        bver = C.binary_version(bb, launcher)
        out()
        out("PLANTED-BUG BUILD  %s" % bb)
        out("  sha256 %s" % bsha)
        out("  build  %s" % bver.get("build"))
        if "bug=0" in bver.get("build", ""):
            out("  this is not a planted-bug build; it cannot qualify the check")
            refused_all = False
            continue
        bpass, bfailed, bruns = run_cases(bb, launcher, tmp_records, out)
        if bpass:
            refused_all = False
            out("  VERDICT planted bug: PASSED  <- the check did NOT refuse it")
        else:
            out("  VERDICT planted bug: REFUSED by %s  (%d solver runs)" % (", ".join(bfailed), bruns))
            bug_summ.append("%s:%s" % (os.path.basename(bb), "+".join(bfailed)))

    # Cluster label as the solver recorded it (atlas/vanda only inside a PBS job).
    rows = C.read_csv(tmp_records) if os.path.exists(tmp_records) else []
    cluster = rows[0]["cluster"] if rows else "local"
    host = rows[0]["host"] if rows else "?"
    vdir = os.path.join(C.RESULTS, "validation", cluster)
    if not os.path.isdir(vdir):
        os.makedirs(vdir)
    if os.path.exists(tmp_records):
        os.rename(tmp_records, os.path.join(vdir, "%s.csv" % stamp))

    out()
    if args.qualify:
        qualified = passed and refused_all
        out("QUALIFICATION: correct build %s; planted bugs %s -> check %s" %
            ("PASSED" if passed else "FAILED", "all REFUSED" if refused_all else "NOT all refused",
             "QUALIFIED" if qualified else "NOT QUALIFIED"))
        if qualified:
            C.append_csv(C.VALIDATED, C.VALIDATED_COLUMNS, {
                "utc": stamp, "cluster": cluster, "host": host, "binary_sha256": sha, "binary": binary,
                "build": ver.get("build", ""), "validate_sha256": C.sha256_file(os.path.abspath(__file__)),
                "cases": ";".join(c[0] for c in CASES), "bug_binaries_refused": ";".join(bug_summ),
                "verdict": "QUALIFIED"})
            out("VALIDATED BINARY sha256=%s (cluster=%s) -> %s" % (sha, cluster, os.path.relpath(C.VALIDATED, C.REPO)))
            out("Timing runs and report figures accept only this hash.")
    else:
        out("RESULT: %s (development run; nothing recorded; use --qualify to validate a binary)" %
            ("PASS" if passed else "REFUSED"))
    with open(os.path.join(vdir, "%s.txt" % stamp), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("output kept in %s" % os.path.relpath(os.path.join(vdir, "%s.txt" % stamp), C.REPO))
    if args.qualify:
        return 0 if (passed and refused_all) else 1
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
