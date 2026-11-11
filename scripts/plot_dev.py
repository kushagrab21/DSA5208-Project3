#!/usr/bin/env python3
"""DEVELOPMENT plot from local run records: proves the record -> check -> figure path. Not a report figure.

  python3 scripts/plot_dev.py [results/local] [-o figures/dev/local_strong.png]

Loads rows only through checks/run_record.figure_rows(..., allow_local=True) and stamps the figure as local
development data. Report figures will call figure_rows(paths) without allow_local, which refuses local rows.
"""
import argparse
import os
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
import run_record  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator  # noqa: E402

# Reference palette (dataviz skill), validated light mode: slots 1 and 2.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
SERIES = {("classic", "blocking"): ("#2a78d6", "classic CG, blocking halo"),
          ("pipelined", "overlap"): ("#eb6834", "pipelined CG, overlapped halo")}


def median_by(rows, key):
    out = {}
    for r in rows:
        out.setdefault(key(r), []).append(float(r["t_total"]))
    return {k: statistics.median(v) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=[os.path.join(REPO, "results", "local")])
    ap.add_argument("-o", "--out", default=os.path.join(REPO, "figures", "dev", "local_strong.png"))
    a = ap.parse_args()
    rows = run_record.figure_rows(a.paths, allow_local=True)
    rows = [r for r in rows if r["tag"] == "strong" and r["threads"] == "1"]
    if not rows:
        print("no local strong-scaling rows")
        return 1
    dev = any(r["_dev"] for r in rows)

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK})
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), sharey=True, facecolor=SURFACE)
    for ax, dim in zip(axes, ("2", "3")):
        ax.set_facecolor(SURFACE)
        sub = [r for r in rows if r["dim"] == dim]
        n = sub[0]["n"]
        med = median_by(sub, lambda r: (r["cg"], r["halo"], int(r["ranks"])))
        ranks_all = sorted(set(k[2] for k in med))
        for (cg, halo), (color, label) in SERIES.items():
            pts = sorted((k[2], v) for k, v in med.items() if k[:2] == (cg, halo))
            if not pts:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            ax.plot(xs, ys, color=color, lw=2, marker="o", ms=6, mec=SURFACE, mew=1.5, label=label, zorder=3)
            ax.annotate("%.2f s" % ys[-1], (xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=8, color=INK2)
            if (cg, halo) == ("classic", "blocking"):
                ideal = [ys[0] / x for x in xs]
                ax.plot(xs, ideal, color=MUTED, lw=1, ls="--", label="ideal T(1)/P (classic)", zorder=2)
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.xaxis.set_major_locator(FixedLocator(ranks_all))
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: "%d" % v))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlim(ranks_all[0] / 1.3, ranks_all[-1] * 1.9)
        ax.grid(True, which="major", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_title("%sD, n=%s (%.2fM unknowns)" % (dim, n, int(sub[0]["unknowns"]) / 1e6), fontsize=9,
                     color=INK, loc="left")
        ax.set_xlabel("MPI ranks (1 thread each)")
    axes[0].set_ylabel("time for 100 CG iterations,\nmedian of 3 repeats (s)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=8, loc="lower center", ncol=3)
    if dev:
        fig.suptitle("LOCAL DEVELOPMENT DATA (Apple M5 laptop) - not a report figure; cluster=local rows",
                     fontsize=9, color="#b3261e", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 0.94))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    fig.savefig(a.out, dpi=200, facecolor=SURFACE)
    print("wrote %s from %d rows (%s)" % (os.path.relpath(a.out, REPO), len(rows),
                                          "LOCAL development rows" if dev else "cluster rows"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
