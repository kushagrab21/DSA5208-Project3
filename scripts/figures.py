#!/usr/bin/env python3
"""Report figures, drawn from Atlas/Vanda run records only.

  python3 scripts/figures.py                      all figures -> figures/<name>.pdf + figures/<name>.meta.json
  python3 scripts/figures.py --selftest           fabricated cluster rows in a scratch directory (TEST DOUBLE); checks
                                                  every figure fills, axes are log where required, a local row is
                                                  refused, and nothing is written to figures/ or report/

Rows come only through checks/run_record.figure_rows (via scripts/reportdata.py): a local row in the cluster folders
makes the script refuse. A figure is drawn only when every planned run it needs is recorded; otherwise its metadata
says "unfilled" and lists what it is waiting for, and any stale image is removed. The metadata records the axis scales
read back from the drawn axes, the source CSVs with their sha256, and the binaries behind the rows; the requirements
check reads it.
"""
import argparse
import datetime
import json
import math
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "checks"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

import reportdata as RD  # noqa: E402

# Reference palette (dataviz skill), light mode, validated with scripts/validate_palette.js:
#   variants: blue/orange (adjacent PASS); components: aqua/violet/red (all-pairs PASS with a CVD warn -> direct
#   labels and distinct markers); node counts: aqua/violet (PASS). Aqua is below 3:1 contrast -> every figure has a
#   table with the same numbers in the report.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
VARIANT = {("classic", "blocking"): ("#2a78d6", "classic CG, blocking halo"),
           ("pipelined", "overlap"): ("#eb6834", "pipelined CG, overlapped halo")}
DIMSTYLE = {2: ("--", "o", "2D (5-point)"), 3: ("-", "s", "3D (7-point)")}
COMP = [("t_compute", "#1baf7a", "o", "compute"), ("t_halo", "#6250d6", "s", "halo exchange"),
        ("t_reduce", "#e34948", "^", "global reductions")]
NODES = ["#1baf7a", "#6250d6"]

FIGURES = {}


def figure(name, groups, gpu=False):
    def deco(fn):
        FIGURES[name] = (fn, groups, gpu)
        return fn
    return deco


def style():
    plt.rcParams.update({"font.size": 8.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK, "axes.titlesize": 9, "legend.fontsize": 8,
                         "pdf.fonttype": 42})


def new_fig(ncols, w=7.0, h=2.9):
    fig, axes = plt.subplots(1, ncols, figsize=(w, h), facecolor=SURFACE)
    axes = list(axes) if ncols > 1 else [axes]
    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(True, which="major", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    return fig, axes


def count_axis(ax, ticks, axis="x"):
    """Log2 axis with the actual counts as tick labels (cores, ranks)."""
    getattr(ax, "set_%sscale" % axis)("log", base=2)
    a = ax.xaxis if axis == "x" else ax.yaxis
    a.set_major_locator(FixedLocator(sorted(set(ticks))))
    a.set_major_formatter(FuncFormatter(lambda v, _: "%d" % round(v)))
    a.set_minor_locator(NullLocator())
    ax.tick_params(axis=axis, labelsize=7)


def plain_log_y(ax):
    """Log y axis with plain numbers (0.5, 2, 30) instead of 3x10^0 on short ranges."""
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "%g" % v))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: "%g" % v if str("%g" % v)[0] in "25" else ""))


def end_label(ax, x, y, text, color=INK2, dy=0):
    ax.annotate(text, (x, y), xytext=(5, dy), textcoords="offset points", va="center", fontsize=7.5, color=color)


def axes_meta(ax, panel, xq, yq):
    return [{"panel": panel, "axis": "x", "quantity": xq, "scale": ax.get_xscale()},
            {"panel": panel, "axis": "y", "quantity": yq, "scale": ax.get_yscale()}]


# ---------------------------------------------------------------------------------------------------------------
# Figures. Each returns (fig, axes metadata, cell ids used).
# ---------------------------------------------------------------------------------------------------------------
@figure("fig_serial", ["serial"])
def fig_serial(D):
    fig, (a1, a2) = new_fig(2)
    used, meta = [], []
    for d in (2, 3):
        ls, mk, lab = DIMSTYLE[d]
        pts = []
        for cid, c in D.cells("serial", dim=d):
            r = D.row0(cid)
            pts.append((int(r["unknowns"]), int(r["nonzeros"]), D.med(cid)))
            used.append(cid)
        pts.sort()
        for ax, k in ((a1, 0), (a2, 1)):
            ax.plot([p[k] for p in pts], [p[2] for p in pts], color=VARIANT[("classic", "blocking")][0], ls=ls,
                    marker=mk, ms=5, lw=1.8, mec=SURFACE, mew=1, label=lab)
            end_label(ax, pts[-1][k], pts[-1][2], lab, dy=-7 if d == 2 else 7)
    for ax, xl, q in ((a1, "unknowns N (matrix dimension)", "size"), (a2, "nonzeros of the matrix", "size")):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(xl)
        ax.margins(x=0.25)
        meta += axes_meta(ax, xl.split()[0], q, "time")
    a1.set_ylabel("time for %d iterations, 1 core (s)" % D.plan["fixed_iters"])
    a1.legend(frameon=False, loc="upper left")
    return fig, meta, used


@figure("fig_serial_tol", ["serial-tol"])
def fig_serial_tol(D):
    fig, (a1, a2) = new_fig(2)
    used, meta = [], []
    for d in (2, 3):
        ls, mk, lab = DIMSTYLE[d]
        pts = []
        for cid, c in D.cells("serial-tol", dim=d):
            r = D.row0(cid)
            pts.append((c["n"], int(r["unknowns"]), int(r["iters"]), D.med(cid)))
            used.append(cid)
        pts.sort()
        a1.plot([p[0] for p in pts], [p[2] for p in pts], color=VARIANT[("classic", "blocking")][0], ls=ls,
                marker=mk, ms=5, lw=1.8, mec=SURFACE, mew=1, label=lab)
        a2.plot([p[1] for p in pts], [p[3] for p in pts], color=VARIANT[("classic", "blocking")][0], ls=ls,
                marker=mk, ms=5, lw=1.8, mec=SURFACE, mew=1, label=lab)
        end_label(a1, pts[-1][0], pts[-1][2], lab, dy=-7 if d == 2 else 7)
        end_label(a2, pts[-1][1], pts[-1][3], lab, dy=-7 if d == 2 else 7)
    for ax in (a1, a2):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.margins(x=0.25)
    a1.set_xlabel("grid points per direction n")
    a1.set_ylabel("CG iterations to tolerance")
    a2.set_xlabel("unknowns N")
    a2.set_ylabel("time to tolerance, 1 core (s)")
    a1.legend(frameon=False, loc="upper left")
    meta = axes_meta(a1, "iterations", "size", "iterations") + axes_meta(a2, "time", "size", "time")
    return fig, meta, used


def _scaling(D, group, ideal):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    for ax, d in zip(axes, (2, 3)):
        for (cg, halo), (color, lab) in VARIANT.items():
            pts = sorted((c["ranks"] * c["threads"], D.med(cid), c["n"]) for cid, c in
                         D.cells(group, dim=d, cg=cg, halo=halo))
            series = [cid for cid, c in D.cells(group, dim=d, cg=cg, halo=halo)]
            D.check_same_build(series, "%s %dD %s/%s" % (group, d, cg, halo))
            used += series
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            ticks += xs
            ax.plot(xs, ys, color=color, marker="o", ms=4.5, lw=1.8, mec=SURFACE, mew=1, label=lab)
            end_label(ax, xs[-1], ys[-1], cg, dy=-6 if cg == "classic" else 6)
            if (cg, halo) == ("classic", "blocking"):
                ax.plot(xs, [ideal(ys[0], x) for x in xs], color=MUTED, lw=1, ls=":", label="ideal (classic)")
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlabel("cores (MPI ranks, 1 thread each)")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 2.2)
        title = "%dD" % d
        ax.set_title(title, loc="left")
        meta += axes_meta(ax, title, "cores", "time")
    axes[0].set_ylabel("time for %d iterations (s)" % D.plan["fixed_iters"])
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


@figure("fig_strong", ["strong"])
def fig_strong(D):
    return _scaling(D, "strong", lambda t1, p: t1 / p)


@figure("fig_weak", ["weak"])
def fig_weak(D):
    return _scaling(D, "weak", lambda t1, p: t1)


@figure("fig_efficiency", ["strong", "weak"])
def fig_efficiency(D):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    for ax, group, title in zip(axes, ("strong", "weak"), ("strong scaling: T(1)/(P T(P))", "weak scaling: T(1)/T(P)")):
        for d in (2, 3):
            ls, mk, dlab = DIMSTYLE[d]
            for (cg, halo), (color, vlab) in VARIANT.items():
                cs = D.cells(group, dim=d, cg=cg, halo=halo)
                D.check_same_build([cid for cid, c in cs], "%s %dD %s/%s" % (group, d, cg, halo))
                used += [cid for cid, c in cs]
                pts = sorted((c["ranks"] * c["threads"], D.med(cid)) for cid, c in cs)
                t1 = pts[0][1]
                xs = [p[0] for p in pts]
                ys = [t1 / (p[0] * p[1]) if group == "strong" else t1 / p[1] for p in pts]
                ticks += xs
                ax.plot(xs, ys, color=color, ls=ls, marker=mk, ms=4, lw=1.6, mec=SURFACE, mew=1,
                        label="%s, %s" % (dlab.split()[0], vlab))
        count_axis(ax, ticks)
        ax.set_ylim(0, 1.15)
        ax.axhline(1.0, color=MUTED, lw=0.8, ls=":")
        ax.set_xlabel("cores")
        ax.set_title(title, loc="left")
        meta += axes_meta(ax, group, "cores", "efficiency")
    axes[0].set_ylabel("parallel efficiency")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=2)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


@figure("fig_comm", ["strong"])
def fig_comm(D):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    for ax, d in zip(axes, (2, 3)):
        cs = sorted(D.cells("strong", dim=d, cg="classic", halo="blocking"), key=lambda t: t[1]["ranks"])
        D.check_same_build([cid for cid, c in cs], "strong %dD classic/blocking" % d)
        used += [cid for cid, c in cs]
        xs = [c["ranks"] for cid, c in cs]
        ticks += xs
        for col, color, mk, lab in COMP:
            # one rank has no halo or reduction partner: those series start at two ranks
            pts = [(c["ranks"], D.med(cid, col) / float(D.row0(cid)["iters"])) for cid, c in cs]
            pts = [p for p in pts if p[1] > 0]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, marker=mk, ms=4.5, lw=1.6, mec=SURFACE,
                    mew=1, label=lab)
            end_label(ax, pts[-1][0], pts[-1][1], lab)
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 5)
        ax.set_xlabel("cores (MPI ranks)")
        ax.set_title("%dD, classic CG, blocking halo" % d, loc="left")
        meta += axes_meta(ax, "%dD" % d, "cores", "time")
    axes[0].set_ylabel("time per iteration, mean over ranks (s)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


@figure("fig_layout", ["layout"])
def fig_layout(D):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    node_counts = sorted(set(c["nodes"] for cid, c in D.cells("layout")))
    for ax, d in zip(axes, (2, 3)):
        for color, nn in zip(NODES, node_counts):
            cs = sorted(D.cells("layout", dim=d, nodes=nn), key=lambda t: t[1]["ranks"])
            used += [cid for cid, c in cs]
            xs = [c["ranks"] // nn for cid, c in cs]
            ys = [D.med(cid) for cid, c in cs]
            ticks += xs
            lab = "%d node%s (%d cores)" % (nn, "s" if nn > 1 else "", nn * D.plan["cores_per_node"])
            ax.plot(xs, ys, color=color, marker="o", ms=4.5, lw=1.8, mec=SURFACE, mew=1, label=lab)
            end_label(ax, xs[-1], ys[-1], lab.split(" (")[0])
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 3)
        ax.set_xlabel("MPI ranks per node (threads = %d / ranks)" % D.plan["cores_per_node"])
        ax.set_title("%dD" % d, loc="left")
        meta += axes_meta(ax, "%dD" % d, "cores", "time")
    axes[0].set_ylabel("time for %d iterations (s)" % D.plan["fixed_iters"])
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=2)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


# ---------------------------------------------------------------------------------------------------------------
def build(results, out, names=None, stamp_text=None):
    style()
    os.makedirs(out, exist_ok=True)
    report = []
    for name, (fn, groups, gpu) in FIGURES.items():
        if names and name not in names:
            continue
        D = RD.choose(results, groups)
        pdf, metap = os.path.join(out, name + ".pdf"), os.path.join(out, name + ".meta.json")
        meta = {"figure": name, "script": "scripts/figures.py", "script_sha256": RD.sha256(os.path.abspath(__file__)),
                "plan": D.plan["plan"], "cluster": D.cluster, "groups": groups,
                "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        mixed = None
        if D.complete(*groups):
            try:
                fig, axes, used = fn(D)
            except RD.MixedBuild as e:
                mixed = str(e)
                plt.close("all")
        if not D.complete(*groups) or mixed:
            meta.update({"status": "unfilled", "waiting_for": [mixed] if mixed else D.waiting(*groups)})
            if os.path.exists(pdf):
                os.remove(pdf)
            report.append("%-16s UNFILLED  waiting for %s" % (name, "; ".join(meta["waiting_for"])))
        else:
            if stamp_text:
                fig.text(0.5, 0.5, stamp_text, fontsize=26, color="#b3261e", alpha=0.25, ha="center", va="center",
                         rotation=20)
            if not getattr(fig, "_p3_layout", False):
                fig.tight_layout()
            for ax in fig.axes:
                if ax.get_yscale() == "log":
                    plain_log_y(ax)
            fig.savefig(pdf, facecolor=SURFACE)
            plt.close(fig)
            rows = D.used_rows(used)
            meta.update({"status": "filled", "axes": axes, "rows": len(rows), "sources": D.sources(used),
                         "binaries": sorted(set(r["binary_sha256"] for r in rows)),
                         "clusters": sorted(set(r["cluster"] for r in rows)), "image_sha256": RD.sha256(pdf)})
            report.append("%-16s filled    %d rows, axes %s" % (
                name, len(rows), ", ".join("%s:%s=%s" % (a["panel"], a["quantity"], a["scale"]) for a in axes)))
        with open(metap, "w") as f:
            json.dump(meta, f, indent=1)
    return report


# ---------------------------------------------------------------------------------------------------------------
# Selftest with fabricated cluster rows (TEST DOUBLE) in a scratch directory
# ---------------------------------------------------------------------------------------------------------------
FAKE_SHA = "d0" * 32


def fake_rows(plan, cid, jobid, utc, sha, host="TEST-DOUBLE", speed=1.0):
    """TEST-DOUBLE record rows for one cell, shaped like real ones (times from the plan's cost model x speed)."""
    import p3common as C
    from run_plan import cell_seconds, model_of
    M = model_of(plan)
    c = plan["cells"][cid]
    N = c["n"] ** c["dim"]
    P = c["ranks"]
    reps = c.get("repeats", 1)
    local = N / float(P)
    per = speed * (cell_seconds(plan, c) - M["launch_s"] - M["setup_s_per_point"] * local * 1.02) / reps
    iters = c["iters"] if c["mode"] == "fixed" else int(M["tol_iters_per_n"] * (c["n"] + 1))
    out = []
    for rep in range(1, reps + 1):
        t = per * (1 + 0.01 * rep)
        halo = 0.12 * t if P > 1 else 0.0
        red = 0.04 * t * math.log(P, 2) / 8 if P > 1 else 0.0
        row = dict((k, "0") for k in C.RECORD_COLUMNS)
        row.update({
            "schema": C.RECORD_SCHEMA, "utc": utc, "cluster": plan["cluster"], "host": host, "pbs_jobid": jobid,
            "cell": cid, "tag": "test", "nodes": c["nodes"], "ranks": P, "threads": c["threads"],
            "gpus": c.get("gpus", 0), "dim": c["dim"], "n": c["n"], "unknowns": N,
            "nonzeros": N + 2 * c["dim"] * (c["n"] - 1) * c["n"] ** (c["dim"] - 1),
            "decomp": "%dD" % c["decomp"], "pdims": "x", "local_max": -(-N // P), "local_min": N // P,
            "cg": c["cg"], "halo": c["halo"], "mode": c["mode"],
            "iters_req": c["iters"] if c["mode"] == "fixed" else 1000000,
            "tol": "na" if c["mode"] == "fixed" else repr(c["tol"]), "iters": iters, "repeat": rep,
            "t_total": "%.6e" % t, "t_halo": "%.6e" % halo, "t_reduce": "%.6e" % red,
            "t_compute": "%.6e" % (t - halo - red), "t_other": "0", "t_halo_max": "%.6e" % halo,
            "t_reduce_max": "%.6e" % red, "t_compute_max": "%.6e" % (t - halo - red), "t_setup": "1",
            "msgs_per_exch": 2 * c["decomp"] if P > 1 else 0, "doubles_per_exch_max": 0,
            "allreduces": 0, "exchanges": iters, "rel_res": "1e-9", "true_rel_res": "1e-9",
            "err_max": "1e-5", "err_l2": "1e-5", "converged": "na" if c["mode"] == "fixed" else "1",
            "breakdown": "0", "binary_sha256": sha, "git_sha": "testdouble",
            "build": "omp=1;offload=%d;bug=0;cxx=TEST DOUBLE;mpi=TEST DOUBLE" % (1 if c.get("gpus") else 0),
            "mpi_thread": "funneled", "problem": "expoly"})
        out.append(row)
    return out


def fabricate(results, plan_name="vanda", jobs=None):
    """Writes TEST-DOUBLE rows for every cell of a plan (or of the named jobs), shaped like real records, plus a
    validated list."""
    import p3common as C
    plan = RD.load_plan(plan_name)
    for jobi, job in enumerate(plan["jobs"]):
        if jobs is not None and job["id"] not in jobs:
            continue
        path = os.path.join(results, plan["cluster"], "TESTDOUBLE.%d.csv" % jobi)
        for cid in job["cells"]:
            for row in fake_rows(plan, cid, "TESTDOUBLE.%s.%d" % (plan_name, jobi), "2026-11-13T0%d:00:00Z" %
                                 (jobi % 10), FAKE_SHA):
                C.append_csv(path, C.RECORD_COLUMNS, row)
    envd = os.path.join(results, plan["cluster"], "env")
    os.makedirs(envd, exist_ok=True)
    with open(os.path.join(envd, "TESTDOUBLE.0.json"), "w") as f:
        json.dump({"pbs_jobid": "TESTDOUBLE.0", "cpu_model": "TEST DOUBLE CPU", "mem_total_gb": 0,
                   "modules": "TEST DOUBLE"}, f)
    C.append_csv(os.path.join(results, "validated_binaries.csv"), C.VALIDATED_COLUMNS, {
        "utc": "TESTDOUBLE", "cluster": plan["cluster"], "host": "TEST-DOUBLE", "binary_sha256": FAKE_SHA,
        "binary": "TEST DOUBLE", "build": "TEST DOUBLE", "validate_sha256": "-", "cases": "-",
        "bug_binaries_refused": "-", "verdict": "QUALIFIED"})


def snapshot(d):
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            out[p] = os.path.getmtime(p)
    return out


def selftest():
    import p3common as C
    guard = [os.path.join(REPO, "figures"), os.path.join(REPO, "report")]
    before = dict((g, snapshot(g)) for g in guard)
    ok = True
    with tempfile.TemporaryDirectory(prefix="p3fig_") as td:
        res, out = os.path.join(td, "results"), os.path.join(td, "figures")
        fabricate(res)
        lines = build(res, out, stamp_text="TEST DOUBLE")
        for line in lines:
            print("  " + line)
        metas = [json.load(open(os.path.join(out, n + ".meta.json"))) for n in FIGURES]
        filled = all(m["status"] == "filled" for m in metas)
        print("  every figure filled from fabricated rows: %s" % ("yes" if filled else "NO"))
        ok &= filled
        bad = [(m["figure"], a["panel"], a["axis"]) for m in metas for a in m.get("axes", [])
               if a["quantity"] in ("time", "size", "cores") and a["scale"] != "log"]
        print("  time/size/core axes not logarithmic: %d %s" % (len(bad), bad if bad else ""))
        ok &= not bad
        # a local row among the cluster rows must make the figures refuse
        src = os.path.join(REPO, "results", "local")
        local_rows = C.read_csv(sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(".csv"))[0]) \
            if os.path.isdir(src) else []
        if local_rows:
            lr = dict((k, local_rows[0][k]) for k in C.RECORD_COLUMNS)
            C.append_csv(os.path.join(res, "vanda", "smuggled_local.csv"), C.RECORD_COLUMNS, lr)
            try:
                build(res, os.path.join(td, "figures2"))
                print("  local row among cluster rows: NOT refused")
                ok = False
            except C.Refused as e:
                print("  local row among cluster rows: REFUSED (%s)" % e)
        else:
            print("  local row test skipped: no results/local rows")
            ok = False
    after = dict((g, snapshot(g)) for g in guard)
    clean = before == after
    print("  figures/ and report/ untouched by the selftest: %s" % ("yes" if clean else "NO"))
    ok &= clean
    print("FIGURES SELFTEST: %s" % ("PASS" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*")
    ap.add_argument("--results", default=os.path.join(REPO, "results"))
    ap.add_argument("--out", default=os.path.join(REPO, "figures"))
    ap.add_argument("--stamp", default=None, help="watermark text (used for TEST DOUBLE builds)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    import p3common as C
    try:
        lines = build(a.results, a.out, a.names, a.stamp)
    except C.Refused as e:
        print("FIGURES: REFUSED: %s" % e)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
