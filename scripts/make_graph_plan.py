#!/usr/bin/env python3
"""Adds the graph extension (SNAP community labelling) to the run plans config/run_plan.<cluster>.json.

  python3 scripts/make_graph_plan.py               # vanda, atlas and local
  python3 scripts/make_graph_plan.py vanda         # one plan
  python3 scripts/make_graph_plan.py --check       # refuse if a plan's graph part differs from what this script makes

It ADDS groups graph-serial, graph-strong, graph-variants, graph-sweep, their cells and their jobs, and changes
nothing that is already in the plan: no existing group, cell or job is edited, the budget, pbs, model, unplanned and
reruns entries stay as they are. Every added item carries "amendment": AMENDMENT, and plan["amendments"] records the
date, the reason and what was added, so the addition is legal in a frozen plan (checks/run_plan.py check refuses an
item that names an amendment without a reason). Running it again is a no-op if the graph part is already as it would
write it; a different graph part already in a FROZEN plan is refused (record a new amendment instead).
If a git merge of a plan file conflicts, take the other side's file and run this script again.
"""
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
import graph_plan as GP  # noqa: E402

AMENDMENT = "graph-2026-11-12"
REASON = ("Data-science extension decided on 12 Nov 2026 (parent and user, circuit d7): semi-supervised community "
          "labelling on SNAP graphs with the same classic/pipelined CG on a distributed CSR operator. Adds the "
          "graph groups, cells and jobs only; no Poisson group, cell or job is changed.")
A_VALUES = (0.01, 0.1, 1.0, 10.0, 100.0)
S_VALUES = (1, 2, 5, 10, 20)
KEEP_VALUES = (1.0, 0.5, 0.25, 0.125)
VARIANT_PARTS = (("natural", "rows"), ("natural", "nnz"), ("bfs", "nnz"))
EXCHANGES = ("alltoallv", "neighbor", "overlap")
STRONG_RHS = 2       # strong and variant cells time 2 of the K solves (time per solve is the unit)
SERIAL_ITERS = 100   # serial ladder: fixed iterations on one right-hand side (time per CG iteration)
LONG_REPEAT_S = 600  # a cell whose single repeat is estimated above this runs once (its timing noise is far below
                     # 1%; three repeats would triple the 1-core com-Orkut baseline to about an hour)
BIG = ("com-lj", "com-orkut")  # a = 0.01 is left out on these two: ~9000 iterations per solve (sqrt(cond) law); the
                               # 1/sqrt(a) growth of the iterations is shown on the four smaller graphs


class G:
    def __init__(self, plan):
        self.plan = plan
        self.groups, self.cells, self.jobs = {}, {}, []

    def group(self, gid, req, desc):
        self.groups[gid] = {"requirement": req, "description": desc, "graded": True, "cells": [],
                            "amendment": AMENDMENT}

    def cell(self, gid, c):
        c = dict(c, amendment=AMENDMENT)
        if c.get("repeats", 1) > 1:
            # the plan's own model, never the calibrated one: the rule must give the same plan every time it runs
            one = GP.cell_seconds(self.plan, dict(c, repeats=1), self.plan["model"])
            if one > LONG_REPEAT_S:
                c["repeats"] = 1
        cid = GP.cell_id(c)
        self.cells.setdefault(cid, c)
        if cid not in self.groups[gid]["cells"]:
            self.groups[gid]["cells"].append(cid)
        return cid

    def job(self, jid, nodes, ncpus, cells, note, place="excl", **kw):
        j = {"id": jid, "nodes": nodes, "ncpus_per_node": ncpus, "gpus_per_node": 0, "binary": "graph",
             "validate_first": False, "place": place, "cells": list(cells), "note": note, "amendment": AMENDMENT}
        j.update(kw)
        self.jobs.append(j)


def build(plan):
    cl = plan["cluster"]
    g = G(plan)
    if cl == "vanda":
        cpn, counts, var_cores, top_nodes = 72, [1, 2, 4, 9, 18, 36, 72, 144, 288], (72, 288), 4
        layouts = ((8, 9), (2, 36))
        serial_queue = None
    elif cl == "atlas":
        cpn, counts, var_cores, top_nodes = 96, [1, 2, 4, 6, 12, 24, 48, 96], (48, 96), 1
        layouts = ((8, 12), (2, 48))
        serial_queue = "serial"
    else:
        cpn, counts, var_cores, top_nodes = 10, [1, 2, 4, 8], (4,), 1
        layouts = ((2, 2),)
        serial_queue = None
    local = cl == "local"
    ladder = GP.ORDER[:2] if local else GP.ORDER
    strong_ds = ("com-amazon",) if local else GP.STRONG_DATASETS
    sweep_ds = GP.ORDER[:2] if local else GP.ORDER
    sweep_ranks = 4 if local else cpn

    def nodes_for(cores):
        return max(1, -(-cores // cpn))

    g.group("graph-serial", "E2,E12", "graph: serial time per CG iteration vs edges and vertices (dataset ladder), "
            "natural and BFS vertex order")
    for d in ladder:
        for order in ("natural", "bfs"):
            g.cell("graph-serial", GP.make_cell(d, 1, order=order, mode="fixed", iters=SERIAL_ITERS, rhs=1,
                                                queue=serial_queue))
    g.group("graph-strong", "E3,E5", "graph: strong scaling, time per solve (%d of the K systems), %s, classic and "
            "pipelined CG, 1..%d cores" % (STRONG_RHS, " and ".join(GP.DATASETS[d]["display"] for d in strong_ds),
                                           counts[-1]))
    for d in strong_ds:
        for cg in ("classic", "pipelined"):
            for r in counts:
                g.cell("graph-strong", GP.make_cell(d, r, nodes=nodes_for(r), cg=cg, rhs=STRONG_RHS))
    g.group("graph-variants", "E8,E5", "graph: partition (rows, nnz, BFS order + nnz) x ghost exchange (alltoallv, "
            "neighbor, overlap) x CG at %s cores; ranks x threads" % " and ".join(str(x) for x in var_cores))
    for d in strong_ds:
        for n in var_cores:
            for (order, part) in VARIANT_PARTS:
                for ex in EXCHANGES:
                    for cg in ("classic", "pipelined"):
                        g.cell("graph-variants", GP.make_cell(d, n, nodes=nodes_for(n), order=order, part=part,
                                                              exchange=ex, cg=cg, rhs=STRONG_RHS))
            for (rpn, th) in layouts:
                nn = nodes_for(n)
                if rpn * th * nn == n:
                    g.cell("graph-variants", GP.make_cell(d, rpn * nn, threads=th, nodes=nn, rhs=STRONG_RHS))
    g.group("graph-sweep", "E11,E12", "graph: accuracy and iterations of the full labelling (K=10 systems) vs a, s "
            "and edge keep fraction (sparsity), every dataset")
    for d in sweep_ds:
        r = 8 if d == "email-Eu-core" else sweep_ranks
        r = min(r, sweep_ranks)
        for a in A_VALUES:
            if a < 0.1 and d in BIG and not local:
                continue
            g.cell("graph-sweep", GP.make_cell(d, r, a=a, repeats=1))
        for s in S_VALUES:
            g.cell("graph-sweep", GP.make_cell(d, r, s=s, repeats=1))
        for k in KEEP_VALUES:
            g.cell("graph-sweep", GP.make_cell(d, r, keep=k, repeats=1))

    cells = g.cells
    one_core = [cid for cid, c in cells.items() if c["ranks"] * c["threads"] == 1]
    ser = list(g.groups["graph-serial"]["cells"])
    strong1 = [cid for cid in g.groups["graph-strong"]["cells"] if cid in one_core]
    by_nodes = {}
    for cid in sorted(set(g.groups["graph-strong"]["cells"] + g.groups["graph-variants"]["cells"]) - set(one_core)):
        by_nodes.setdefault(cells[cid]["nodes"], []).append(cid)
    sweep = sorted(g.groups["graph-sweep"]["cells"])
    if local:
        g.job("local-graph", 1, cpn, ser + sorted(set(strong1) - set(ser)) + by_nodes.get(1, []) + sweep,
              "development: every local graph cell (rows never reach the report)")
        return g
    allds = list(GP.ORDER)
    prep_ncpus = 8 if cl == "vanda" else 12
    g.job("%s-graph-prep" % cl, 1, prep_ncpus, [], "build bin/p3graph (+ planted-bug build, p3convert), convert the "
          "six fetched SNAP datasets in $P3_DATA, qualify validate_graph.py (G1, G2; planted bug refused), write the "
          "seed lists", place="pack", validate_first=True, convert=allds, mem_gb=48)
    strong_n1 = [cid for cid in by_nodes.get(1, []) if cid in g.groups["graph-strong"]["cells"]]
    var_n1 = [cid for cid in by_nodes.get(1, []) if cid not in strong_n1]
    if cl == "atlas":
        g.job("atlas-graph-serial", 1, 1, ser, "graph serial ladder in queue serial (1 core, 12 GB)", place="pack",
              queue="serial", mem_gb=12)
        g.job("atlas-graph-strong", 1, cpn, strong1 + strong_n1, "graph strong 1-96 cores (the 1-core baselines on "
              "the same node type as the curve)")
        g.job("atlas-graph-variants", 1, cpn, var_n1, "graph variants at 48 and 96 cores; ranks x threads")
    else:
        g.job("vanda-graph-serial", 1, cpn, ser + strong1, "graph serial ladder and the 1-core strong baselines, on "
              "an otherwise idle node")
        g.job("vanda-graph-strong", 1, cpn, strong_n1, "graph strong 2-72 cores")
        g.job("vanda-graph-variants", 1, cpn, var_n1, "graph variants and ranks x threads at 72 cores")
        for nn in sorted(k for k in by_nodes if k > 1):
            g.job("vanda-graph-%dnode" % nn, nn, cpn, by_nodes[nn], "graph strong%s at %d cores" %
                  (" + variants + layouts" if nn == top_nodes else "", nn * cpn))
    g.job("%s-graph-sweep" % cl, 1, cpn, sweep, "graph labelling sweeps: a, s, keep on every dataset")
    return g


def merge(plan, g, check):
    """Adds g to plan. Returns (changed, problems)."""
    problems, changed = [], False
    have_jobs = dict((j["id"], j) for j in plan["jobs"])
    def own(kind, item):
        """The item as this amendment made it: later amendments may add cells to a graph group (recorded in its
        changed_by), which is not a difference."""
        if kind != "group":
            return item
        x = dict(item)
        x.pop("changed_by", None)
        x["cells"] = [c for c in x["cells"] if plan["cells"].get(c, {}).get("amendment", AMENDMENT) == AMENDMENT]
        return x
    for kind, new, old in (("group", g.groups, plan["groups"]), ("cell", g.cells, plan["cells"])):
        for k, v in new.items():
            if k in old:
                if own(kind, old[k]) != v:
                    problems.append("%s %s exists and differs" % (kind, k))
            else:
                changed = True
                if not check:
                    old[k] = v
    for j in g.jobs:
        if j["id"] in have_jobs:
            if have_jobs[j["id"]] != j:
                problems.append("job %s exists and differs" % j["id"])
        else:
            changed = True
            if not check:
                plan["jobs"].append(j)
    if "graph_model" not in plan:
        changed = True
        if not check:
            plan["graph_model"] = dict(GP.DEFAULT_MODEL)
    if not any(a.get("id") == AMENDMENT for a in plan.get("amendments", [])):
        changed = True
        if not check:
            plan.setdefault("amendments", []).append({
                "id": AMENDMENT, "by": "scripts/make_graph_plan.py",
                "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "plan_frozen_when_added": bool(plan.get("frozen")), "reason": REASON,
                "adds": {"groups": sorted(g.groups), "jobs": [j["id"] for j in g.jobs], "cells": len(g.cells)}})
    return changed, problems


def main(argv):
    check = "--check" in argv
    names = [a for a in argv if not a.startswith("--")] or ["vanda", "atlas", "local"]
    rc = 0
    for name in names:
        path = os.path.join(REPO, "config", "run_plan.%s.json" % name)
        with open(path) as f:
            plan = json.load(f)
        g = build(plan)
        changed, problems = merge(plan, g, check)
        if problems:
            print("REFUSED %s: the graph part already in the plan differs from what this script makes%s:" %
                  (os.path.relpath(path, REPO), " (frozen: add a new amendment instead)" if plan.get("frozen") else
                   " (delete the graph items, or change this script)"))
            for p in problems[:10]:
                print("  - %s" % p)
            rc = 1
            continue
        if check:
            print("%s %s: graph part %s" % ("CHECK", os.path.relpath(path, REPO),
                                           "MISSING (run without --check)" if changed else "as generated"))
            rc = rc or (1 if changed else 0)
            continue
        if not changed:
            print("%s: graph part already present, unchanged" % os.path.relpath(path, REPO))
            continue
        with open(path, "w") as f:
            json.dump(plan, f, indent=1, sort_keys=False)
            f.write("\n")
        print("%s: added %d graph groups, %d cells, %d jobs (amendment %s%s)" %
              (os.path.relpath(path, REPO), len(g.groups), len(g.cells), len(g.jobs), AMENDMENT,
               ", plan is frozen" if plan.get("frozen") else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
