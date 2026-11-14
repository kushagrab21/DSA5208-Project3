#!/usr/bin/env python3
"""Amendment graph-rerun-2026-11-14 of the FROZEN Vanda plan: the graph cells that vanda-graph-4node did not reach move
to a new job, vanda-graph-4node-rerun, on the same 4 whole nodes.

  python3 scripts/amend_vanda_graph_rerun.py            apply (idempotent: a second run changes nothing)
  python3 scripts/amend_vanda_graph_rerun.py --check    refuse unless the plan is in the amended state

Why: vanda-graph-4node (PBS 1546819) ran on 14 Nov after Vanda's PBS outage and exceeded its walltime (1:10:22 of
1:10:00) with 21 of its 40 cells recorded: every com-LiveJournal cell and one com-Orkut cell. The 19 com-Orkut cells it
did not reach move to vanda-graph-4node-rerun, so that every cell stays in exactly one job. Each moved cell gets the
rerun reason in plan["reruns"]. Nothing is added to the groups and no cell changes.

Walltime, from measured runs: each moved cell is estimated as its com-LiveJournal sibling at 288 cores in 1546819 (all
repeats plus setup and read time) times the com-Orkut / com-LiveJournal ratio of the same method at 72 cores on one node
(graph-variants, all repeats plus setup and read), plus 10 s. The job is the sum plus the plan's job overhead, and the
walltime is the plan's safety factor times that (the rule for estimates from measured runs, run_plan.job_safety).
The cells are ordered so that the two graph-strong cells come first, then the hybrid layouts, then the rest by
estimated cost: a second overrun would then lose the costliest breadth-first cells, not the strong-scaling points.
"""
import datetime
import json
import os
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

PLAN = os.path.join(os.environ.get("P3_CONFIG") or os.path.join(REPO, "config"), "run_plan.vanda.json")
RESULTS = os.environ.get("P3_RESULTS") or os.path.join(REPO, "results")
AMENDMENT = "graph-rerun-2026-11-14"
OLD, NEW = "vanda-graph-4node", "vanda-graph-4node-rerun"
FAILED_JOB = "1546819.stdct-mgmt-02"
REASON = "walltime exceeded on 1546819 (1:10:22 of 1:10:00); missing cells only"
METHOD_KEYS = ("order", "part", "exchange", "cg", "threads", "a", "s", "keep")


def cost(D, cid):
    """Seconds a recorded cell took in its job: every repeat's solve plus the median setup and read time."""
    rs = D.cell_rows.get(cid)
    if not rs:
        return None
    return (sum(float(r["t_total"]) for r in rs) + statistics.median(float(r["t_setup"]) for r in rs) +
            statistics.median(float(r.get("t_read") or 0) for r in rs))


def one_node_twin(plan, D, c, dataset):
    """The recorded cell of `dataset` with the same method at one full node (72 cores, same threads per rank)."""
    cpn = plan["cores_per_node"]
    for cid, x in plan["cells"].items():
        if (x.get("dataset") == dataset and all(x.get(k) == c.get(k) for k in METHOD_KEYS) and x["nodes"] == 1 and
                x["ranks"] * x["threads"] == cpn and cid in D.cell_rows):
            return cid
    return None


def estimate(plan, D, cid):
    c = plan["cells"][cid]
    lj288 = cid.replace("com-orkut", "com-lj")
    o72, l72 = one_node_twin(plan, D, c, "com-orkut"), one_node_twin(plan, D, c, "com-lj")
    parts = (cost(D, lj288), cost(D, o72) if o72 else None, cost(D, l72) if l72 else None)
    if None in parts:
        return None, {"cell": cid, "error": "no measured sibling"}
    secs = parts[0] * parts[1] / parts[2] + 10.0
    return secs, {"cell": cid, "com_lj_288_s": round(parts[0], 1), "com_orkut_72_s": round(parts[1], 1),
                  "com_lj_72_s": round(parts[2], 1), "estimate_s": round(secs, 1)}


def main(argv):
    check = "--check" in argv
    with open(PLAN) as f:
        plan = json.load(f)
    jobs = dict((j["id"], j) for j in plan["jobs"])
    am = [a for a in plan.get("amendments", []) if a.get("id") == AMENDMENT]
    if check or NEW in jobs:
        ok = bool(am) and NEW in jobs and not (set(jobs[NEW]["cells"]) & set(jobs[OLD]["cells"])) and \
            sorted(jobs[NEW]["cells"]) == sorted(am[0]["changes"][OLD]["moved"])
        print("CHECK %s: amendment %s %s" % (os.path.relpath(PLAN, REPO), AMENDMENT, "applied" if ok else
                                             "NOT applied"))
        if not check and ok:
            print("  (already applied, unchanged)")
        return 0 if ok else 1
    import reportdata as RD
    D = RD.data(RESULTS, "vanda")
    old = jobs.get(OLD)
    if old is None:
        print("REFUSED: no %s job in the plan" % OLD)
        return 1
    missing = [c for c in old["cells"] if c not in D.cell_rows]
    if not missing:
        print("REFUSED: every cell of %s is recorded; nothing to rerun" % OLD)
        return 1
    est, rows = {}, []
    for cid in missing:
        secs, row = estimate(plan, D, cid)
        if secs is None:
            print("REFUSED: no measured basis for %s (%s)" % (cid, row["error"]))
            return 1
        est[cid] = secs
        rows.append(row)
    strong = set(plan["groups"]["graph-strong"]["cells"])
    order = sorted(missing, key=lambda c: (0 if c in strong else 1 if plan["cells"][c]["threads"] > 1 else 2,
                                           est[c]))
    secs = sum(est.values()) + plan["model"]["job_overhead_s"]
    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = [c for c in old["cells"] if c not in missing]
    old["cells"] = kept
    old.setdefault("changed_by", []).append(AMENDMENT)
    new = {"id": NEW, "nodes": old["nodes"], "ncpus_per_node": old["ncpus_per_node"], "gpus_per_node": 0,
           "binary": old.get("binary", "graph"), "validate_first": False, "place": old.get("place", "excl"),
           "cells": order, "est_seconds": round(secs), "amendment": AMENDMENT,
           "note": "the com-Orkut cells at 288 cores that %s did not reach (walltime exceeded); strong-scaling cells "
                   "first, breadth-first cells last" % OLD}
    plan["jobs"].insert(plan["jobs"].index(old) + 1, new)
    for c in missing:
        plan["reruns"].append({"cell": c, "reason": REASON})
    plan.setdefault("amendments", []).append({
        "id": AMENDMENT, "by": "scripts/amend_vanda_graph_rerun.py", "utc": utc,
        "plan_frozen_when_added": bool(plan.get("frozen")),
        "reason": "%s: PBS %s ran on 14 Nov after the Vanda PBS outage and exceeded its walltime with %d of %d cells "
                  "recorded. The %d cells it did not reach move to %s; every cell stays in exactly one job." %
                  (REASON, FAILED_JOB, len(kept), len(kept) + len(missing), len(missing), NEW),
        "adds": {"jobs": [NEW], "cells": 0},
        "changes": {OLD: {"moved": missing, "kept": kept}},
        "estimate": {"rule": "each cell = its com-LiveJournal sibling at 288 cores in %s (all repeats + setup + read) "
                             "x the com-Orkut/com-LiveJournal ratio of the same method on one 72-core node + 10 s; "
                             "job = sum + job overhead; walltime = plan safety x job" % FAILED_JOB,
                     "cells": rows, "job_seconds": round(secs), "safety": plan["model"]["safety"]}})
    with open(PLAN, "w") as f:
        json.dump(plan, f, indent=1, sort_keys=False)
        f.write("\n")
    print("%s: amendment %s applied: %s holds %d cells, estimate %.0f s (safety x%.0f in the walltime)" %
          (os.path.relpath(PLAN, REPO), AMENDMENT, NEW, len(order), secs, plan["model"]["safety"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
