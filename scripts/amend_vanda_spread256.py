#!/usr/bin/env python3
"""Amendment spread256-2026-11-12 of the FROZEN Vanda plan: a 256-core insurance job on shared nodes.

  python3 scripts/amend_vanda_spread256.py            apply (idempotent: a second run changes nothing)
  python3 scripts/amend_vanda_spread256.py --check    refuse unless the plan is in the amended state

Why (user decision, 12 Nov ~22:30 IST, "ya just do insuurance run"): vanda-4node 1546582 and vanda-graph-4node 1546819
need four whole nodes (place=excl) and have waited about 8 hours. 19 cpu_node nodes were free, but batch_cpu had 993
jobs queued: the wait is queue position, not hardware; 20 nodes had at least 32 free cores. So a job that takes 32
cores on each of 8 nodes, shared with other jobs (place=scatter), in the normal queue (project route; not autox, no
ticket), runs the >= 256-core points of the strong and weak series (Poisson 2D and 3D, classic+blocking and
pipelined+overlap) and of the graph strong series (com-LiveJournal, com-Orkut, classic and pipelined). The whole-node
288-core jobs stay queued; if they also run, the report shows both placements.

New cells: the 288-rank cells of those series with 256 ranks on 8 nodes and "placement": "shared-8x32" (their own
cell ids), each naming the 288-rank cell it insures ("insurance_for"); added to the same groups so the points sit on
the same curves (speedups from the same 1-core baselines). The job runs unbound (P3_BIND=none): on shared nodes a job
sees all 72 cores (cpuset 0-71, test 1547726), so binding to cores could collide with other users.
The walltime comes from measured runs (the graph cost model is far off once calibrated): each new cell is timed as its
144-rank sibling, times a factor (Poisson strong 1.0, weak 1.2, graph 2.0: the graph runs slowed down from one node to
two), plus its recorded setup time; the derivation is stored in the amendment.
"""
import datetime
import json
import os
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import graph_plan as GP  # noqa: E402
import make_plan as MP  # noqa: E402

PLAN = os.path.join(os.environ.get("P3_CONFIG") or os.path.join(REPO, "config"), "run_plan.vanda.json")
AMENDMENT = "spread256-2026-11-12"
JOB = "vanda-256spread"
PLACEMENT = "shared-8x32"
NODES, PER_NODE = 8, 32
FACTOR = {"strong": 1.0, "weak": 1.2, "graph-strong": 2.0}
REASON = ("User decision (12 Nov, ~22:30 IST, \"ya just do insuurance run\"): vanda-4node 1546582 and vanda-graph-4node "
          "1546819 (4 whole nodes, place=excl) had waited about 8 hours; 19 cpu_node nodes were free but batch_cpu had "
          "993 jobs queued, so the wait is queue position, not hardware, and 20 nodes had >= 32 free cores. An "
          "insurance job, vanda-256spread, takes 8 x 32 cores on shared nodes (place=scatter) in the normal queue "
          "(project route; not autox, no ticket) and runs 256-rank cells of the strong and weak Poisson series and of "
          "the graph strong series (placement shared-8x32, unbound: a shared-node job sees all 72 cores). The "
          "whole-node 288-core jobs stay queued; if they run too, the report shows both placements.")


def measured(results, cl, cells, sib):
    """Seconds of a recorded cell (all repeats) and its setup, from results/<cluster>/ (None if not recorded)."""
    import run_record
    d = os.path.join(results, cl)
    rows = run_record.load_rows([d]) + run_record.load_graph_rows([d])
    rs = [r for r in rows if r["cell"] == sib]
    if not rs:
        return None
    reps = cells[sib].get("repeats", 1)
    return reps * statistics.median(float(r["t_total"]) for r in rs) + \
        statistics.median(float(r["t_setup"]) for r in rs)


def build(plan):
    cells, groups, est = {}, {}, {}
    cpn = plan["cores_per_node"]
    top = 4 * cpn
    for gid in ("strong", "weak", "graph-strong"):
        for cid in plan["groups"][gid]["cells"]:
            c = plan["cells"][cid]
            if c["ranks"] != top or c.get("threads", 1) != 1 or c.get("placement"):
                continue
            n = dict(c, ranks=NODES * PER_NODE, nodes=NODES, placement=PLACEMENT, insurance_for=cid,
                     amendment=AMENDMENT)
            if gid == "weak":
                n["n"] = MP.weak_n(c["dim"], NODES * PER_NODE)
            nid = GP.cell_id(n) if GP.is_graph(n) else MP.cell_id(n)
            cells[nid] = n
            groups.setdefault(gid, []).append(nid)
            # the measured sibling on two nodes, same series
            sib = [x for x in plan["groups"][gid]["cells"] if plan["cells"][x]["ranks"] == 2 * cpn and
                   all(plan["cells"][x].get(k) == c.get(k) for k in ("dim", "dataset", "cg", "halo", "threads"))
                   and not plan["cells"][x].get("placement")]
            m = measured(os.path.join(REPO, "results"), plan["cluster"], plan["cells"], sib[0]) if sib else None
            est[nid] = {"from": sib[0] if sib else None, "measured_s": round(m, 1) if m else None,
                        "factor": FACTOR[gid], "estimate_s": round(FACTOR[gid] * m + 10, 1) if m else 600.0}
    return cells, groups, est


def main(argv):
    check = "--check" in argv
    with open(PLAN) as f:
        plan = json.load(f)
    jobs = dict((j["id"], j) for j in plan["jobs"])
    am = [a for a in plan.get("amendments", []) if a.get("id") == AMENDMENT]
    if check or JOB in jobs:
        ok = (JOB in jobs and am and all(c in plan["cells"] for c in jobs[JOB]["cells"]) and
              all(c in plan["groups"][g]["cells"] for g, cs in am[0]["changes"]["groups"].items() for c in cs))
        print("CHECK %s: amendment %s %s" % (os.path.relpath(PLAN, REPO), AMENDMENT,
                                              "applied" if ok else "NOT applied"))
        if not check and JOB in jobs:
            print("  (already applied, unchanged)" if ok else "  REFUSED: %s exists but the amendment is incomplete" % JOB)
        return 0 if ok else 1
    cells, groups, est = build(plan)
    clash = [c for c in cells if c in plan["cells"]]
    if clash:
        print("REFUSED: cells already in the plan: %s" % clash[:3])
        return 1
    secs = sum(e["estimate_s"] for e in est.values()) + plan["model"]["job_overhead_s"]
    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan["cells"].update(cells)
    for gid, cs in groups.items():
        plan["groups"][gid]["cells"] += cs
        plan["groups"][gid].setdefault("changed_by", []).append(AMENDMENT)
    plan["jobs"].append({
        "id": JOB, "nodes": NODES, "ncpus_per_node": PER_NODE, "gpus_per_node": 0, "binary": "cpu+graph",
        "validate_first": False, "place": "scatter", "bind": "none", "cells": sorted(cells),
        "est_seconds": round(secs), "amendment": AMENDMENT,
        "note": "insurance for the >=256-core points: 8 x 32 cores on shared nodes (place=scatter), unbound; the "
                "whole-node 288-core jobs stay queued"})
    plan.setdefault("amendments", []).append({
        "id": AMENDMENT, "by": "scripts/amend_vanda_spread256.py", "utc": utc,
        "plan_frozen_when_added": bool(plan.get("frozen")), "reason": REASON,
        "adds": {"jobs": [JOB], "cells": len(cells)},
        "changes": {"groups": groups},
        "estimate": {"rule": "each cell = factor x its measured 144-rank sibling (all repeats + setup) + 10 s; job = sum "
                             "+ job overhead; walltime = plan safety x estimate",
                     "cells": est, "job_seconds": round(secs)}})
    with open(PLAN, "w") as f:
        json.dump(plan, f, indent=1, sort_keys=False)
        f.write("\n")
    print("%s: amendment %s applied: %s with %d cells (%s), estimate %.0f s" %
          (os.path.relpath(PLAN, REPO), AMENDMENT, JOB, len(cells),
           ", ".join("%s +%d" % (g, len(c)) for g, c in groups.items()), secs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
