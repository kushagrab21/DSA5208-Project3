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
VARIANT = {("classic", "blocking"): ("#2a78d6", "classic CG, blocking halo exchange"),
           ("pipelined", "overlap"): ("#eb6834", "pipelined CG, non-blocking halo exchange")}
DIMSTYLE = {2: ("--", "o", "2D (5-point)"), 3: ("-", "s", "3D (7-point)")}
COMP = [("t_compute", "#1baf7a", "o", "computation"), ("t_halo", "#6250d6", "s", "halo exchange"),
        ("t_reduce", "#e34948", "^", "reductions (MPI_Allreduce)")]
NODES = ["#1baf7a", "#6250d6"]

FIGURES = {}

# Cells with a "placement" (the shared-node insurance run, e.g. 8 x 32 cores, unbound) are drawn as hollow diamonds in
# the series colour, off the line through the whole-node runs; their speedups use the same 1-core baseline.
SPREAD_MARK = dict(marker="D", ms=6, mfc="none", mew=1.4, ls="none")


def spread_label(c):
    return "%d$\\times$%d cores, shared nodes, unbound" % (c["nodes"], c["ranks"] // c["nodes"])


def split_place(cs):
    """(whole-node cells, shared-placement cells) of a series [(cid, cell)]."""
    return [t for t in cs if not t[1].get("placement")], [t for t in cs if t[1].get("placement")]


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
    ts = sorted(set(ticks))
    # two counts within 20% (256 on shared nodes next to 288 on whole nodes) would print on top of each other: keep the
    # larger tick; the marker of the other stays, and the caption names it
    ts = [t for i, t in enumerate(ts) if not (i + 1 < len(ts) and ts[i + 1] < 1.2 * t)]
    a.set_major_locator(FixedLocator(ts))
    a.set_major_formatter(FuncFormatter(lambda v, _: "%d" % round(v)))
    a.set_minor_locator(NullLocator())
    ax.tick_params(axis=axis, labelsize=7)


def plain_log_y(ax, axis="y"):
    """Log axis with plain numbers (0.5, 2, 30) instead of 3x10^0, labelled to suit its range: under about one decade
    the ticks are 1-2-3-5-7 per decade (else a short axis shows no number at all); up to two and a half decades the
    2s and 5s are labelled too; beyond that only the powers of ten."""
    from matplotlib.ticker import LogLocator
    a = ax.yaxis if axis == "y" else ax.xaxis
    lo, hi = sorted(ax.get_ylim() if axis == "y" else ax.get_xlim())
    dec = math.log10(hi / lo) if lo > 0 else 9
    def nice(v, _=None):  # 0.5, 2, 30 ... but 10^6 rather than 1e+06, and 10^-4 rather than 0.0001
        if v <= 0:
            return ""
        e = math.log10(v)
        if abs(e - round(e)) < 1e-9 and (v >= 1e4 or v < 1e-3):
            return "$10^{%d}$" % round(e)
        return "%g" % v
    fmt = FuncFormatter(nice)
    if dec < 1.2:
        a.set_major_locator(LogLocator(base=10, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0)))
        a.set_major_formatter(fmt)
        a.set_minor_locator(NullLocator())
    elif dec < 2.5:
        a.set_major_formatter(fmt)
        a.set_minor_formatter(FuncFormatter(lambda v, _: nice(v) if str("%g" % v)[0] in "25" else ""))
    else:
        a.set_major_formatter(fmt)
        a.set_minor_formatter(FuncFormatter(lambda v, _: ""))


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
        end_label(a1, pts[-1][0], pts[-1][2], lab, dy=-7 if d == 2 else 12)
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
            main, extra = split_place(D.cells(group, dim=d, cg=cg, halo=halo))
            pts = sorted((c["ranks"] * c["threads"], D.med(cid), c["n"]) for cid, c in main)
            series = [cid for cid, c in main + extra]
            D.check_same_build(series, "%s %dD %s/%s" % (group, d, cg, halo))
            used += series
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            ticks += xs + [c["ranks"] for cid, c in extra]
            ax.plot(xs, ys, color=color, marker="o", ms=4.5, lw=1.8, mec=SURFACE, mew=1, label=lab)
            for k, (cid, c) in enumerate(extra):
                ax.plot([c["ranks"]], [D.med(cid)], color=color, **SPREAD_MARK,
                        label=spread_label(c) if (cg, halo) == ("classic", "blocking") and k == 0 else None)
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
                cs, extra = split_place(D.cells(group, dim=d, cg=cg, halo=halo))
                D.check_same_build([cid for cid, c in cs + extra], "%s %dD %s/%s" % (group, d, cg, halo))
                used += [cid for cid, c in cs + extra]
                pts = sorted((c["ranks"] * c["threads"], D.med(cid)) for cid, c in cs)
                t1 = pts[0][1]
                for cid, c in extra:  # same 1-core baseline
                    P = c["ranks"]
                    ax.plot([P], [t1 / (P * D.med(cid)) if group == "strong" else t1 / D.med(cid)], color=color,
                            **SPREAD_MARK)
                    ticks.append(P)
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
        cs, extra = split_place(sorted(D.cells("strong", dim=d, cg="classic", halo="blocking"),
                                       key=lambda t: t[1]["ranks"]))
        D.check_same_build([cid for cid, c in cs + extra], "strong %dD classic/blocking" % d)
        used += [cid for cid, c in cs + extra]
        for cid, c in extra:
            for col, color, mk, lab in COMP:
                ax.plot([c["ranks"]], [D.med(cid, col) / float(D.row0(cid)["iters"])], color=color, **SPREAD_MARK)
            ticks.append(c["ranks"])
        xs = [c["ranks"] for cid, c in cs]
        ticks += xs
        for k, (col, color, mk, lab) in enumerate(COMP):
            # one rank has no halo or reduction partner (its recorded time is timer overhead): those series start at
            # two ranks
            pts = [(c["ranks"], D.med(cid, col) / float(D.row0(cid)["iters"])) for cid, c in cs
                   if col == "t_compute" or c["ranks"] > 1]
            pts = [p for p in pts if p[1] > 0]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, marker=mk, ms=4.5, lw=1.6, mec=SURFACE,
                    mew=1, label=lab)
            end_label(ax, pts[-1][0], pts[-1][1], lab, dy=(0, -9, 9)[k])
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 5)
        ax.set_xlabel("cores (MPI ranks)")
        ax.set_title("%dD, classic CG, blocking halo exchange" % d, loc="left")
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
# Graph extension (SNAP community labelling): rows of bin/p3graph, cells of the graph-* groups.
# ---------------------------------------------------------------------------------------------------------------
import graph_plan as GP  # noqa: E402

ORDERSTYLE = {"natural": ("#2a78d6", "-", "o", "natural (SNAP id) order"),
              "bfs": ("#eb6834", "--", "s", "BFS (Cuthill-McKee) order")}
DSCOLOR = dict(zip(GP.ORDER, ["#52514e", "#2a78d6", "#1baf7a", "#6250d6", "#eb6834", "#e34948"]))
DSMARK = dict(zip(GP.ORDER, ["o", "s", "^", "D", "v", "P"]))
CGSTYLE = {"classic": ("#2a78d6", "o", "classic CG"), "pipelined": ("#eb6834", "^", "pipelined CG")}


GLABEL = {"email-Eu-core": (6, -2, "left"), "com-amazon": (-6, 4, "right"), "com-dblp": (6, -9, "left"),
          "com-youtube": (6, -2, "left"), "com-lj": (-6, 2, "right"), "com-orkut": (-6, 4, "right")}


def short(ds):
    return GP.DATASETS[ds]["display"].replace("com-", "")


@figure("fig_graph_serial", ["graph-serial"])
def fig_graph_serial(D):
    fig, (a1, a2) = new_fig(2)
    used, meta = [], []
    for order, (color, ls, mk, lab) in ORDERSTYLE.items():
        pts = []
        for cid, c in D.cells("graph-serial", order=order):
            r = D.row0(cid)
            pts.append((int(r["nonzeros"]), int(r["vertices"]), D.med(cid, "t_iter"), c["dataset"]))
            used.append(cid)
        pts.sort()
        for ax, k in ((a1, 0), (a2, 1)):
            # six different graphs, not one series: markers only, no line suggesting a path between them
            ax.plot([p[k] for p in pts], [p[2] for p in pts], color=color, ls="none", marker=mk, ms=5.5,
                    mec=SURFACE, mew=1, label=lab)
        if order == "natural":
            for p in pts:
                dx, dy, ha = GLABEL.get(p[3], (6, -3, "left"))
                for ax, k in ((a1, 0), (a2, 1)):
                    ax.annotate(short(p[3]), (p[k], p[2]), xytext=(dx, dy), textcoords="offset points",
                                fontsize=6.5, color=INK2, ha=ha)
    for ax, xl in ((a1, "nonzeros of L + aI (2E + V)"), (a2, "vertices V (matrix dimension)")):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel(xl)
        ax.margins(x=0.2)
        meta += axes_meta(ax, xl.split()[0], "size", "time")
    a1.set_ylabel("time per CG iteration, 1 core (s)")
    a2.legend(frameon=False, loc="lower right", fontsize=7)
    return fig, meta, used


def _graph_series(D, group, dset, cg):
    cs = sorted(D.cells(group, dataset=dset, cg=cg, threads=1), key=lambda t: t[1]["ranks"])
    return cs


@figure("fig_graph_strong", ["graph-strong"])
def fig_graph_strong(D):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    for ax, dset in zip(axes, GP.STRONG_DATASETS):
        last = {}
        for cg in CGSTYLE:
            cs = split_place(_graph_series(D, "graph-strong", dset, cg))[0]
            last[cg] = D.med(cs[-1][0], "t_solve") if cs else 0
        for cg, (color, mk, lab) in CGSTYLE.items():
            cs, extra = split_place(_graph_series(D, "graph-strong", dset, cg))
            D.check_same_build([cid for cid, c in cs + extra], "graph-strong %s %s" % (dset, cg))
            used += [cid for cid, c in cs + extra]
            for k, (cid, c) in enumerate(extra):
                ax.plot([c["ranks"]], [D.med(cid, "t_solve")], color=color, **SPREAD_MARK,
                        label=spread_label(c) if cg == "classic" and k == 0 else None)
                ticks.append(c["ranks"])
            xs = [c["ranks"] for cid, c in cs]
            ys = [D.med(cid, "t_solve") for cid, c in cs]
            ticks += xs
            ax.plot(xs, ys, color=color, marker=mk, ms=4.5, lw=1.8, mec=SURFACE, mew=1, label=lab)
            # the series that ends higher gets its label above (pipelined ends lower than classic across nodes)
            end_label(ax, xs[-1], ys[-1], cg, dy=7 if ys[-1] >= max(last.values()) else -7)
            if cg == "classic":
                ax.plot(xs, [ys[0] / x for x in xs], color=MUTED, lw=1, ls=":", label="ideal (classic)")
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 2.2)
        ax.set_xlabel("cores (MPI ranks, 1 thread each)")
        ax.set_title(GP.DATASETS[dset]["display"], loc="left")
        meta += axes_meta(ax, dset, "cores", "time")
    axes[0].set_ylabel("time per solve (s)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


@figure("fig_graph_comm", ["graph-strong"])
def fig_graph_comm(D):
    fig, axes = new_fig(2)
    used, meta, ticks = [], [], []
    comp = [("t_compute", "#1baf7a", "o", "products and vectors"), ("t_halo", "#6250d6", "s", "ghost exchange"),
            ("t_reduce", "#e34948", "^", "reductions (MPI_Allreduce)")]
    for ax, dset in zip(axes, GP.STRONG_DATASETS):
        cs, extra = split_place(_graph_series(D, "graph-strong", dset, "classic"))
        D.check_same_build([cid for cid, c in cs + extra], "graph-strong %s classic" % dset)
        used += [cid for cid, c in cs + extra]
        for cid, c in extra:
            for col, color, mk, lab in comp:
                ax.plot([c["ranks"]], [D.med(cid, col) / float(D.row0(cid)["iters"])], color=color, **SPREAD_MARK)
            ticks.append(c["ranks"])
        ticks += [c["ranks"] for cid, c in cs]
        for k, (col, color, mk, lab) in enumerate(comp):
            pts = [(c["ranks"], D.med(cid, col) / float(D.row0(cid)["iters"])) for cid, c in cs
                   if col == "t_compute" or c["ranks"] > 1]  # 1 rank: no ghosts, no partner in a reduction
            pts = [p for p in pts if p[1] > 0]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, marker=mk, ms=4.5, lw=1.6, mec=SURFACE,
                    mew=1, label=lab)
            end_label(ax, pts[-1][0], pts[-1][1], lab, dy=(-7, 7, 0)[k])
        count_axis(ax, ticks)
        ax.set_yscale("log")
        ax.set_xlim(min(ticks) / 1.4, max(ticks) * 6)
        ax.set_xlabel("cores (MPI ranks)")
        ax.set_title("%s, classic CG" % GP.DATASETS[dset]["display"], loc="left")
        meta += axes_meta(ax, dset, "cores", "time")
    axes[0].set_ylabel("time per iteration, mean over ranks (s)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


VARIANT_ROWS = [(o, p, e) for (o, p) in (("natural", "rows"), ("natural", "nnz"), ("bfs", "nnz"))
                for e in ("alltoallv", "neighbor", "overlap")]
LAYOUT_ROWS = [(8, 9), (2, 36), (8, 12), (2, 48)]  # ranks x threads per node (Vanda: first two; Atlas: last two)


@figure("fig_graph_variants", ["graph-variants"])
def fig_graph_variants(D):
    fig, axes = new_fig(2, h=3.4)
    used, meta = [], []
    for ax, dset in zip(axes, GP.STRONG_DATASETS):
        counts = sorted(set(c["ranks"] for cid, c in D.cells("graph-variants", dataset=dset, threads=1)))
        for ci, n in enumerate(counts):
            for cg, (_, mk, lab) in CGSTYLE.items():
                xs, ys = [], []
                for yi, (o, p, e) in enumerate(VARIANT_ROWS):
                    cs = D.cells("graph-variants", dataset=dset, threads=1, ranks=n, order=o, part=p, exchange=e,
                                 cg=cg)
                    for cid, c in cs:
                        used.append(cid)
                        xs.append(D.med(cid, "t_solve"))
                        ys.append(yi + (-0.15 if cg == "classic" else 0.15))
                ax.plot(xs, ys, ls="none", marker=mk, ms=5, color=NODES[ci % 2], mec=SURFACE, mew=0.8,
                        label="%s, %d cores" % (lab, n))
        labels = ["%s/%s, %s" % (o, p, e) for (o, p, e) in VARIANT_ROWS]
        # MPI + OpenMP: the default method (natural/nnz, neighbor, classic) with fewer ranks and more threads
        for (rpn, th) in LAYOUT_ROWS:
            for ci, n in enumerate(counts):
                cs = [(cid, c) for cid, c in D.cells("graph-variants", dataset=dset, threads=th)
                      if c["ranks"] * th == n and c["ranks"] // c["nodes"] == rpn]
                if not cs:
                    continue
                if "%d ranks x %d threads, nnz, neighbor" % (rpn, th) not in labels:
                    labels.append("%d ranks x %d threads, nnz, neighbor" % (rpn, th))
                yi = labels.index("%d ranks x %d threads, nnz, neighbor" % (rpn, th))
                for cid, c in cs:
                    used.append(cid)
                    ax.plot([D.med(cid, "t_solve")], [yi - 0.15], ls="none", marker="o", ms=5, color=NODES[ci % 2],
                            mec=SURFACE, mew=0.8)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=6.5)
        ax.invert_yaxis()
        ax.set_xscale("log")
        ax.set_xlabel("time per solve (s)")
        ax.set_title(GP.DATASETS[dset]["display"], loc="left")
        meta += [{"panel": dset, "axis": "x", "quantity": "time", "scale": ax.get_xscale()},
                 {"panel": dset, "axis": "y", "quantity": "variant", "scale": ax.get_yscale()}]
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=4, fontsize=7)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


@figure("fig_graph_sweep", ["graph-sweep"])
def fig_graph_sweep(D):
    fig, axes = plt.subplots(2, 3, figsize=(7.0, 4.6), facecolor=SURFACE, sharex="col")
    for ax in axes.flat:
        ax.set_facecolor(SURFACE)
        ax.grid(True, which="major", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    used, meta = [], []
    base = {"a": 1.0, "s": 5, "keep": 1.0}
    sweeps = (("a", "shift a in L + aI"), ("s", "seeds per community s"), ("keep", "average degree 2E/V"))
    for dset in GP.ORDER:
        cs = D.cells("graph-sweep", dataset=dset)
        if not cs:
            continue
        for j, (var, xl) in enumerate(sweeps):
            pts = []
            for cid, c in cs:
                if all(c[k] == v for k, v in base.items() if k != var):
                    r = D.row0(cid)
                    x = float(r["avg_degree"]) if var == "keep" else c[var]
                    pts.append((x, D.med(cid, "accuracy"), D.med(cid, "iters") / float(c["rhs"])))
                    used.append(cid)
            pts.sort()
            for i in (0, 1):
                axes[i][j].plot([p[0] for p in pts], [p[1 + i] for p in pts], color=DSCOLOR[dset],
                                marker=DSMARK[dset], ms=4, lw=1.4, mec=SURFACE, mew=0.8,
                                label=GP.DATASETS[dset]["display"] if j == 0 and i == 0 else None)
    for j, (var, xl) in enumerate(sweeps):
        for i in (0, 1):
            ax = axes[i][j]
            ax.set_xscale("log")
            if i == 0:
                ax.set_ylim(0, 1.05)
            else:
                ax.set_yscale("log")
                ax.set_xlabel(xl)
            meta += [{"panel": "%s-%s" % (var, "accuracy" if i == 0 else "iterations"), "axis": "x",
                      "quantity": var, "scale": ax.get_xscale()},
                     {"panel": "%s-%s" % (var, "accuracy" if i == 0 else "iterations"), "axis": "y",
                      "quantity": "accuracy" if i == 0 else "iterations", "scale": ax.get_yscale()}]
    axes[0][0].set_ylabel("accuracy (evaluated vertices)")
    axes[1][0].set_ylabel("CG iterations per solve")
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="lower center", ncol=6, fontsize=7)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig._p3_layout = True
    return fig, meta, used


# ---------------------------------------------------------------------------------------------------------------
def build(results, out, names=None, stamp_text=None):
    style()
    os.makedirs(out, exist_ok=True)
    RD._CACHE.clear()  # every build reads the records afresh: a row added since the last build must be seen
    report = []
    for name, (fn, groups, gpu) in FIGURES.items():
        if names and name not in names:
            continue
        D = RD.choose(results, groups)
        pdf, metap = os.path.join(out, name + ".pdf"), os.path.join(out, name + ".meta.json")
        meta = {"figure": name, "script": "scripts/figures.py", "script_sha256": RD.sha256(os.path.abspath(__file__)),
                "plan": D.plan["plan"], "cluster": D.cluster, "groups": groups,
                "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        mixed, partial = None, False
        if D.complete(*groups):
            # complete may mean a run or its insurance partner is recorded: draw from the recorded cells
            unrec = any(c not in D.cell_rows for g in groups for c in D.group_cells(g))
            try:
                fig, axes, used = fn(D.filled_view() if unrec else D)
            except RD.MixedBuild as e:
                mixed = str(e)
                plt.close("all")
        elif D.settled(*groups):
            # every missing cell is outstanding (its run failed and a rerun is recorded in the plan): draw what was
            # measured, as a finished figure. The report states the core count each series reaches.
            try:
                fig, axes, used = fn(D.filled_view())
                meta["outstanding"] = sorted(c for g in groups for c in D.group_cells(g) if c not in D.cell_rows)
            except RD.MixedBuild as e:
                mixed = str(e)
                plt.close("all")
        elif all(D.group_status(g)[0] > 0 for g in groups):
            # PARTIAL: draw the recorded cells only (every series from its own 1-core cell); the figure stays
            # waiting for its E rows and the report prints what it waits for under it
            try:
                fig, axes, used = fn(D.filled_view())
                partial = True
            except RD.MixedBuild as e:
                mixed = str(e)
                plt.close("all")
            except Exception as e:  # a series without its baseline, etc.: not drawable yet
                report.append("%-16s (partial drawing failed: %s)" % (name, str(e).splitlines()[0][:80]))
                plt.close("all")
        if not (D.complete(*groups) or D.settled(*groups) or partial) or mixed:
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
                if ax.get_xscale() == "log" and not isinstance(ax.xaxis.get_major_locator(), FixedLocator):
                    plain_log_y(ax, "x")  # count axes keep their own ticks (count_axis)
            fig.savefig(pdf, facecolor=SURFACE)
            plt.close(fig)
            rows = D.used_rows(used)
            meta.update({"status": "partial" if partial else "filled", "axes": axes, "rows": len(rows),
                         "sources": D.sources(used), "binaries": sorted(set(r["binary_sha256"] for r in rows)),
                         "clusters": sorted(set(r["cluster"] for r in rows)), "image_sha256": RD.sha256(pdf)})
            if partial:
                meta["waiting_for"] = D.waiting(*groups)
            report.append("%-16s %-9s %d rows, axes %s%s" % (
                name, "PARTIAL" if partial else "filled", len(rows),
                ", ".join("%s:%s=%s" % (a["panel"], a["quantity"], a["scale"]) for a in axes),
                ("; waiting for " + "; ".join(meta["waiting_for"])) if partial else ""))
        with open(metap, "w") as f:
            json.dump(meta, f, indent=1)
    return report


# ---------------------------------------------------------------------------------------------------------------
# Selftest with fabricated cluster rows (TEST DOUBLE) in a scratch directory
# ---------------------------------------------------------------------------------------------------------------
FAKE_SHA = "d0" * 32
FAKE_GSHA = "e0" * 32  # the TEST-DOUBLE p3graph binary


def fake_graph_rows(plan, cid, jobid, utc, sha, host="TEST-DOUBLE", speed=1.0):
    """TEST-DOUBLE graph rows (schema p3graph-1) for one graph cell: times from the graph cost model x speed, a made-up
    accuracy that rises with s and falls with sparsification. Never real data: the build string says TEST DOUBLE."""
    import p3common as C
    from run_plan import cell_seconds
    c = plan["cells"][cid]
    d = GP.DATASETS[c["dataset"]]
    V, E = d["V"], int(d["E"] * c["keep"])
    P, reps = c["ranks"], c.get("repeats", 1)
    t = speed * cell_seconds(plan, c) / reps
    it = int(GP.iters_per_solve(c, GP.model(plan))) * c["rhs"]
    acc = max(0.0, min(1.0, (0.55 + 0.08 * math.log(c["s"] + 1)) * c["keep"] ** 0.4))
    out = []
    for rep in range(1, reps + 1):
        tt = t * (1 + 0.01 * rep)
        halo = 0.2 * tt if P > 1 else 0.0
        red = 0.05 * tt * math.log(P, 2) / 8 if P > 1 else 0.0
        row = dict((k, "0") for k in C.GRAPH_COLUMNS)
        row.update({
            "schema": C.GRAPH_SCHEMA, "utc": utc, "cluster": plan["cluster"], "host": host, "pbs_jobid": jobid,
            "cell": cid, "tag": "test" + ("@" + c["placement"] if c.get("placement") else ""), "nodes": c["nodes"],
            "ranks": P, "threads": c["threads"],
            "dataset": c["dataset"], "order": c["order"], "keep": "%g" % c["keep"], "vertices": V, "edges": E,
            "nonzeros": 2 * E + V, "avg_degree": "%.6e" % (2.0 * E / V), "max_degree": d["dmax"], "part": c["part"],
            "exchange": c["exchange"], "cg": c["cg"], "a": "%g" % c["a"], "K": c["K"], "s": c["s"],
            "theta": "0.1", "seed": 1, "rhs": c["rhs"], "mode": c["mode"],
            "iters_req": c["iters"] if c["mode"] == "fixed" else 100000,
            "tol": "na" if c["mode"] == "fixed" else "%g" % c["tol"], "iters": it, "iters_min": it // c["rhs"],
            "iters_max": it // c["rhs"], "repeat": rep, "t_total": "%.6e" % tt, "t_solve": "%.6e" % (tt / c["rhs"]),
            "t_iter": "%.6e" % (tt / max(it, 1)), "t_halo": "%.6e" % halo, "t_reduce": "%.6e" % red,
            "t_compute": "%.6e" % (tt - halo - red), "t_other": "0", "t_halo_max": "%.6e" % halo,
            "t_reduce_max": "%.6e" % red, "t_compute_max": "%.6e" % (tt - halo - red), "t_setup": "1", "t_read": "1",
            "rows_max": -(-V // P), "rows_min": V // P, "nnz_max": (2 * E + V) // P + 1, "nnz_min": (2 * E + V) // P,
            "nnz_imbalance": "1.01", "ghosts_max": 0 if P == 1 else min(V, (2 * E) // P),
            "ghosts_sum": 0 if P == 1 else min(V, (2 * E) // P) * P,
            "edge_cut": 0 if P == 1 else int(E * (1 - 1.0 / P) * (0.4 if c["order"] == "bfs" else 0.9)),
            "cut_fraction": "0" if P == 1 else "%.4f" % ((1 - 1.0 / P) * (0.4 if c["order"] == "bfs" else 0.9)),
            "neighbors_max": 0 if P == 1 else min(P - 1, 64), "doubles_per_exch_max": 0, "allreduces": 2 * it,
            "exchanges": it, "rel_res": "1e-9", "true_rel_res": "1e-9",
            "converged": "na" if c["mode"] == "fixed" else "1", "breakdown": "0",
            "accuracy": "%.6e" % (acc if c["rhs"] == c["K"] else -1), "eval_vertices": 1000,
            "unreached": "%.6e" % ((1 - c["keep"]) * 0.3 if c["rhs"] == c["K"] else -1), "majority": "0.2",
            "random": "%.6e" % (1.0 / c["K"]), "seeds_sha": "ab" * 32, "communities": "0;1",
            "binary_sha256": sha, "git_sha": "testdouble",
            "build": "omp=1;offload=0;graph=1;bug=0;cxx=TEST DOUBLE;mpi=TEST DOUBLE", "mpi_thread": "funneled"})
        out.append(row)
    return out


def fake_rows(plan, cid, jobid, utc, sha, host="TEST-DOUBLE", speed=1.0):
    """TEST-DOUBLE record rows for one cell, shaped like real ones (times from the plan's cost model x speed)."""
    import p3common as C
    from run_plan import cell_seconds, model_of
    M = model_of(plan)
    c = plan["cells"][cid]
    if GP.is_graph(c):
        return fake_graph_rows(plan, cid, jobid, utc, sha, host, speed)
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
            "cell": cid, "tag": "test" + ("@" + c["placement"] if c.get("placement") else ""), "nodes": c["nodes"],
            "ranks": P, "threads": c["threads"],
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
        gpath = os.path.join(results, plan["cluster"], "TESTDOUBLE.%d%s" % (jobi, C.GRAPH_SUFFIX))
        for cid in job["cells"]:
            graph = GP.is_graph(plan["cells"][cid])
            for row in fake_rows(plan, cid, "TESTDOUBLE.%s.%d" % (plan_name, jobi), "2026-11-13T0%d:00:00Z" %
                                 (jobi % 10), FAKE_GSHA if graph else FAKE_SHA):
                if graph:
                    C.append_csv(gpath, C.GRAPH_COLUMNS, row)
                else:
                    C.append_csv(path, C.RECORD_COLUMNS, row)
    envd = os.path.join(results, plan["cluster"], "env")
    os.makedirs(envd, exist_ok=True)
    with open(os.path.join(envd, "TESTDOUBLE.0.json"), "w") as f:
        json.dump({"pbs_jobid": "TESTDOUBLE.0", "host": "TD-CPU-001", "cpu_model": "TEST DOUBLE CPU",
                   "mem_total_gb": 100.0, "sockets": 2, "cpus_visible": plan["cores_per_node"],
                   "cxx": "g++ (GCC) 0.0.0", "mpirun": "mpirun (Open MPI) 0.0.0", "modules": "TEST DOUBLE"}, f)
    with open(os.path.join(envd, "TESTDOUBLE.1.json"), "w") as f:  # a GPU node (the report names its compilers)
        json.dump({"pbs_jobid": "TESTDOUBLE.1", "host": "TD-GPU-001", "cpu_model": "TEST DOUBLE CPU",
                   "mem_total_gb": 100.0, "sockets": 2, "cpus_visible": plan["cores_per_node"],
                   "cxx": "nvc++ 0.0-0 64-bit target", "mpirun": "mpirun (Open MPI) 0.0.0", "modules": "TEST DOUBLE"}, f)
    with open(os.path.join(results, plan["cluster"], "calibration.json"), "w") as f:
        json.dump({"utc": "TESTDOUBLE", "from_jobs": ["TESTDOUBLE"], "bw_core_gbs": 10.0, "bw_node_gbs": 200.0,
                   "note": "TEST DOUBLE"}, f)
    C.append_csv(os.path.join(results, "validated_binaries.csv"), C.VALIDATED_COLUMNS, {
        "utc": "TESTDOUBLE", "cluster": plan["cluster"], "host": "TEST-DOUBLE", "binary_sha256": FAKE_SHA,
        "binary": "TEST DOUBLE", "build": "TEST DOUBLE", "validate_sha256": "-", "cases": "-",
        "bug_binaries_refused": "-", "verdict": "QUALIFIED"})
    C.append_csv(os.path.join(results, "validated_binaries.csv"), C.VALIDATED_COLUMNS, {
        "utc": "TESTDOUBLE", "cluster": plan["cluster"], "host": "TEST-DOUBLE", "binary_sha256": FAKE_GSHA,
        "binary": "TEST DOUBLE p3graph", "build": "TEST DOUBLE", "validate_sha256": "-", "cases": "G1;G2",
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
        import run_record
        src = os.path.join(REPO, "results", "local")
        for graph, cols, name in ((False, C.RECORD_COLUMNS, "smuggled_local.csv"),
                                  (True, C.GRAPH_COLUMNS, "smuggled_local" + C.GRAPH_SUFFIX)):
            files = run_record.expand([src], graph=graph) if os.path.isdir(src) else []
            local_rows = C.read_csv(files[0]) if files else []
            what = "local %s row among cluster rows" % ("graph" if graph else "Poisson")
            if not local_rows:
                print("  %s: test skipped, no results/local rows" % what)
                ok = False
                continue
            sm = os.path.join(res, "vanda", name)
            C.append_csv(sm, cols, dict((k, local_rows[0][k]) for k in cols))
            try:
                build(res, os.path.join(td, "figures2"))
                print("  %s: NOT refused" % what)
                ok = False
            except C.Refused as e:
                print("  %s: REFUSED (%s)" % (what, e))
            os.remove(sm)
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
