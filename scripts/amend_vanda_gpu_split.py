#!/usr/bin/env python3
"""Amendment gpu-split-2026-11-12 of the FROZEN Vanda plan: the 1-GPU cells move to a new job, vanda-gpu1.

  python3 scripts/amend_vanda_gpu_split.py            apply (idempotent: a second run changes nothing)
  python3 scripts/amend_vanda_gpu_split.py --check    refuse unless the plan is in the amended state

Why: vanda-gpu (1546583, 1 x 72 cores + 2 GPUs, place=excl) stayed queued for over 4 hours with the PBS comment
"Placement set is too small: Insufficient amount of resource: ngpus (R: 2 A: 1 T: 70)"; only single GPUs come free.
vanda-gpu1 asks for half a GPU node in the `hpc gpu` sample shape (select=1:ncpus=36:mpiprocs=1:ompthreads=36:ngpus=1,
no place=excl, memory by the plan's 2.9 GB per core), builds and qualifies its own offload binary on the GPU node, and
runs the two 1-GPU cells. E7 (at least one GPU run) needs only these. vanda-gpu keeps its resources and the two 2-GPU
cells; it is already queued with its old script (all four cells), so if it runs, its 1-GPU rows are reruns of
vanda-gpu1's cells: the reason is recorded here in advance. Every cell stays in exactly one job of the plan.
"""
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(os.environ.get("P3_CONFIG") or os.path.join(REPO, "config"), "run_plan.vanda.json")
AMENDMENT = "gpu-split-2026-11-12"
QSTAT = ("Placement set is too small: Insufficient amount of resource: ngpus (R: 2 A: 1 T: 70)")
REASON = ("vanda-gpu (PBS 1546583: select=1:ncpus=72:mpiprocs=72:ompthreads=1:ngpus=2, place=excl) stayed queued for "
          "over 4 hours with the qstat comment \"%s\": a whole GPU node with both GPUs free never came. Its two 1-GPU "
          "cells move to a new job vanda-gpu1 in the `hpc gpu` sample shape (1 GPU, 36 cores, half a node, no "
          "place=excl), with its own offload build and validate.py qualification on the GPU node; E7 needs only the "
          "1-GPU cells. vanda-gpu keeps its resources and the two 2-GPU cells (12 Nov 2026)." % QSTAT)


def main(argv):
    check = "--check" in argv
    with open(PLAN) as f:
        plan = json.load(f)
    jobs = dict((j["id"], j) for j in plan["jobs"])
    g = jobs.get("vanda-gpu")
    if g is None:
        print("REFUSED: no vanda-gpu job in %s" % PLAN)
        return 1
    gcells = plan["groups"]["gpu"]["cells"]
    one = [c for c in gcells if plan["cells"][c].get("gpus") == 1]
    two = [c for c in gcells if plan["cells"][c].get("gpus") == 2]
    new = {"id": "vanda-gpu1", "nodes": 1, "ncpus_per_node": 36, "gpus_per_node": 1, "binary": "offload",
           "validate_first": True, "place": "pack", "mpiprocs": 1, "ompthreads": 36, "cells": one,
           "note": "half a GPU node (`hpc gpu` sample: 1 GPU, 36 cores): offload build + its own validate.py "
                   "qualification on the GPU node, then the 1-GPU cells", "amendment": AMENDMENT}
    done = ("vanda-gpu1" in jobs and jobs["vanda-gpu1"] == new and g["cells"] == two and
            AMENDMENT in g.get("changed_by", []) and any(a.get("id") == AMENDMENT for a in plan.get("amendments", [])))
    if check:
        print("CHECK %s: %s" % (os.path.relpath(PLAN, REPO), "amendment %s applied" % AMENDMENT if done else
                                "amendment %s NOT applied" % AMENDMENT))
        return 0 if done else 1
    if done:
        print("%s: amendment %s already applied, unchanged" % (os.path.relpath(PLAN, REPO), AMENDMENT))
        return 0
    if "vanda-gpu1" in jobs or set(g["cells"]) != set(gcells):
        print("REFUSED: the plan is neither in the original nor in the amended state (vanda-gpu1 present, or vanda-gpu "
              "does not hold every GPU cell); look at it by hand")
        return 1
    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    g["cells"] = two
    g.setdefault("changed_by", []).append(AMENDMENT)
    plan["jobs"].insert(plan["jobs"].index(g) + 1, new)
    for c in one:
        plan["reruns"].append({"cell": c, "reason": "amendment %s: vanda-gpu 1546583 was queued with its pre-split "
                               "script (all four GPU cells); if it runs, its rows for this 1-GPU cell duplicate "
                               "vanda-gpu1's" % AMENDMENT})
    plan.setdefault("amendments", []).append({
        "id": AMENDMENT, "by": "scripts/amend_vanda_gpu_split.py", "utc": utc,
        "plan_frozen_when_added": bool(plan.get("frozen")), "reason": REASON,
        "adds": {"jobs": ["vanda-gpu1"], "cells": 0},
        "changes": {"vanda-gpu": {"cells_before": gcells, "cells_after": two}}})
    with open(PLAN, "w") as f:
        json.dump(plan, f, indent=1, sort_keys=False)
        f.write("\n")
    print("%s: amendment %s applied: vanda-gpu1 (1 x 36 cores, 1 GPU) holds %s; vanda-gpu keeps %s" %
          (os.path.relpath(PLAN, REPO), AMENDMENT, ", ".join(one), ", ".join(two)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
