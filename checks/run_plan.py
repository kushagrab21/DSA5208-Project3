#!/usr/bin/env python3
"""Run plan check: which graded cells are filled, what the plan costs, and no job outside the plan.

  python3 checks/run_plan.py status  [--plan vanda] [--require-complete]
        graded cells filled/total per group (from the run records), reruns, unplanned rows, core-hours
        (estimated per job, used so far from results/<cluster>/jobs.csv) against the budget.
        --require-complete exits 1 while any graded cell is empty or a rerun/unplanned job has no recorded reason.
  python3 checks/run_plan.py check   [--plan vanda]      the plan covers every graded requirement (E2-E8)
  python3 checks/run_plan.py pbs     --plan vanda --job ID   write cluster/generated/<plan>/<ID>.pbs
  python3 checks/run_plan.py run     --plan local --job ID   run a job of the LOCAL plan here (cluster plans: refused)
  python3 checks/run_plan.py job-start|job-end --plan P --job ID   called by generated PBS scripts
  python3 checks/run_plan.py selftest                     qualify `check` (complete plan passes; a copy without
                                                          the >=256-core weak cells is refused)

A job id that is not in the plan is refused unless plan["unplanned"] has {"job": ID, "reason": "..."}; a cell run in
more than one PBS job counts as a rerun and needs {"cell": ID, "reason": "..."} in plan["reruns"].
Standard library only, Python >= 3.6.
"""
import argparse
import copy
import datetime
import json
import math
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph_plan as GP  # noqa: E402
import p3common as C  # noqa: E402
import run_record  # noqa: E402

# One append-only ledger per cluster, results/<cluster>/jobs.csv. Events:
#   submit  written locally by cluster/ops/submit.sh (job, cells, commit, resources, estimate)
#   start, end  written on the cluster by the job itself (job-start / job-end below)
#   final   written locally by cluster/ops/poll.sh from qstat -xf (exit status, walltime and core-hours used, flags)
# cluster/ops/fetch.sh merges the cluster's rows into the local file; no row is ever rewritten.
JOBS_COLUMNS = ["pbs_jobid", "plan", "job", "event", "utc", "nodes", "ncpus_per_node", "gpus_per_node", "host",
                "commit", "cells", "select", "walltime", "est_core_hours", "state", "exit_status", "walltime_used",
                "core_hours_used", "note"]


def plan_path(name):
    return os.path.join(C.CONFIG, "run_plan.%s.json" % name)


def model_of(plan):
    """The plan's cost model, with bandwidths replaced by results/<cluster>/calibration.json when fetch.sh has
    measured them (the plan file itself is never rewritten by calibration)."""
    M = dict(plan["model"])
    p = os.path.join(C.RESULTS, plan["cluster"], "calibration.json")
    if os.path.exists(p):
        with open(p) as f:
            cal = json.load(f)
        for k in ("bw_core_gbs", "bw_node_gbs"):
            if cal.get(k):
                M[k] = cal[k]
        M["calibrated_from"] = cal.get("from_jobs", [])
    return M


def load_plan(name):
    with open(plan_path(name)) as f:
        return json.load(f)


def job_of(plan, jid):
    for j in plan["jobs"]:
        if j["id"] == jid:
            return j
    for u in plan.get("unplanned", []):
        if u.get("job") == jid and u.get("reason"):
            return u.get("spec")  # an unplanned job must carry its own spec and reason
    return None


# ----------------------------------------------------------------------------------------------------------------
# Cost model
# ----------------------------------------------------------------------------------------------------------------
def cell_seconds(plan, c):
    """Estimated seconds for one cell (all repeats), from the plan's model. Rough by design; see plan['model']."""
    M = model_of(plan)
    if GP.is_graph(c):
        return GP.cell_seconds(plan, c, M)
    N = c["n"] ** c["dim"]
    P = c["ranks"]
    local = N / float(P) * 1.02
    rpn = -(-P // c["nodes"])
    B = M["bytes_per_point_iter"][c["cg"]]
    if c.get("gpus", 0):
        t_it = local * B / (M["bw_gpu_gbs"] * 1e9)
        if P > 1:  # halos through host buffers
            t_it += 4 * local ** ((c["dim"] - 1.0) / c["dim"]) * 8 / (M["net_gbs"] * 1e9) + 20e-6
    else:
        active = rpn * c["threads"]
        per_core = min(M["bw_core_gbs"], M["bw_node_gbs"] / active)
        t_it = local * B / (per_core * c["threads"] * 1e9)
    if P > 1:
        faces = 2 * c["decomp"]
        t_it += faces * M["latency_s"] + faces * local ** ((c["dim"] - 1.0) / c["dim"]) * 8 / (M["net_gbs"] * 1e9)
        nred = 2 if c["cg"] == "classic" else 1
        t_it += nred * 2 * math.log(P, 2) * M["latency_s"]
    iters = c["iters"] if c["mode"] == "fixed" else M["tol_iters_per_n"] * (c["n"] + 1)
    reps = c.get("repeats", 1)
    return M["launch_s"] + M["setup_s_per_point"] * local + reps * iters * t_it


def job_estimate(plan, j):
    M = model_of(plan)
    secs = sum(cell_seconds(plan, plan["cells"][cid]) for cid in j["cells"]) + M["job_overhead_s"]
    if j.get("est_seconds"):  # an estimate from measured runs, recorded with its derivation in the amendment
        secs = float(j["est_seconds"])
    if j.get("validate_first"):
        secs += 600.0
    if j.get("convert"):
        secs += GP.prep_seconds(plan, j["convert"])
    # A job that reserves whole nodes (place=excl) is charged for them; otherwise for the cores it asks for.
    if j.get("place", plan.get("pbs", {}).get("place", "excl")) == "excl" and j.get("binary", "cpu") != "offload":
        cores = j["nodes"] * max(plan["cores_per_node"], j["ncpus_per_node"])
    else:
        cores = j["nodes"] * j["ncpus_per_node"]
    return secs, cores


def job_queue(plan, j):
    pbs = plan.get("pbs", {})
    if j.get("binary") == "offload":
        return pbs.get("queue_gpu")
    if j.get("queue") == "serial":
        return pbs.get("queue_serial")
    return pbs.get("queue_cpu")


def job_select(plan, j):
    """PBS select string: chunks, cores, MPI ranks, GPUs, memory (per job, or per core from the discovery)."""
    pbs = plan.get("pbs", {})
    n = j["ncpus_per_node"]
    # a job may give its own MPI processes and threads per chunk (the `hpc gpu` sample: mpiprocs=1:ompthreads=36)
    select = "select=%d:ncpus=%d:mpiprocs=%d" % (j["nodes"], n, j.get("mpiprocs", n))
    if pbs.get("select_ompthreads") or "ompthreads" in j:
        select += ":ompthreads=%d" % j.get("ompthreads", 1)  # the site's samples carry it; runs set OMP_NUM_THREADS
    if j.get("gpus_per_node"):
        select += ":ngpus=%d" % j["gpus_per_node"] + pbs.get("select_extra_gpu", "")
    else:
        select += pbs.get("select_extra", "")
    if j.get("mem_gb"):
        select += ":mem=%dgb" % j["mem_gb"]
    elif pbs.get("mem_per_cpu_gb"):
        select += ":mem=%dgb" % max(2, int(math.ceil(n * float(pbs["mem_per_cpu_gb"]))))
    return select


def job_binaries(j):
    """The programs a job runs: "cpu", "graph", "offload", or a mix such as "cpu+graph"."""
    return set(j.get("binary", "cpu").split("+"))


def job_safety(plan, j):
    """Walltime safety factor: the plan's, or the graph model's (larger: iteration counts are uncertain); a job whose
    estimate comes from measured runs (est_seconds) takes the plan's."""
    if j.get("est_seconds"):
        return plan["model"]["safety"]
    if "graph" in job_binaries(j):
        return max(plan["model"]["safety"], GP.model(plan)["safety"])
    return plan["model"]["safety"]


def walltime(secs, safety):
    s = int(math.ceil(secs * safety / 300.0) * 300)
    return "%02d:%02d:00" % (s // 3600, (s % 3600) // 60)


# ----------------------------------------------------------------------------------------------------------------
# Records -> cells
# ----------------------------------------------------------------------------------------------------------------
def matches(c, r):
    if GP.is_graph(c):
        return GP.matches(c, r)
    # a cell with a placement (e.g. shared-8x32) is recorded with the tag <group>@<placement>
    if c.get("placement") and "@" + c["placement"] not in r.get("tag", ""):
        return False
    try:
        same = (int(r["dim"]) == c["dim"] and int(r["n"]) == c["n"] and int(r["ranks"]) == c["ranks"] and
                int(r["threads"]) == c["threads"] and int(r["nodes"]) == c["nodes"] and
                r["decomp"] == "%dD" % c["decomp"] and r["cg"] == c["cg"] and r["halo"] == c["halo"] and
                r["mode"] == c["mode"])
        if c["mode"] == "fixed":
            same = same and int(r["iters_req"]) == c["iters"]
        if c.get("gpus", 0):
            same = same and int(r["gpus"]) >= 1
        return same
    except (KeyError, ValueError):
        return False


def gather(plan):
    """Returns (cell -> {job -> rows}, problems list, unplanned rows, invalid rows)."""
    cl = plan["cluster"]
    d = os.path.join(C.RESULTS, cl)
    rows = run_record.load_rows([d]) if os.path.isdir(d) else []
    rows = [r for r in rows if os.path.basename(r["_file"]) != "jobs.csv"]
    grows = run_record.load_graph_rows([d]) if os.path.isdir(d) else []
    validated = set((e["binary_sha256"], e["cluster"]) for e in C.validated_entries())
    gvalidated = set((e["binary_sha256"], e["cluster"]) for e in C.validated_entries()
                     if set(run_record.GRAPH_CASES) <= set(e.get("cases", "").split(";")))
    per = {}
    problems, unplanned, invalid = [], [], []
    for r in rows + grows:
        ok = gvalidated if r.get("schema") == C.GRAPH_SCHEMA else validated
        if (r["binary_sha256"], r["cluster"]) not in ok or "bug=0" not in r["build"]:
            invalid.append(r)
            continue
        cid = r["cell"]
        if cid not in plan["cells"]:
            unplanned.append(r)
            continue
        if not matches(plan["cells"][cid], r):
            problems.append("row in %s labelled %s does not match that cell's parameters" % (r["_file"], cid))
            continue
        per.setdefault(cid, {}).setdefault(r["pbs_jobid"], []).append(r)
    return per, problems, unplanned, invalid


def filled(plan, cid, per):
    need = plan["cells"][cid].get("repeats", 1)
    for job, rs in per.get(cid, {}).items():
        if len(set(r["repeat"] for r in rs)) >= need and all(r["breakdown"] == "0" for r in rs):
            return True
    return False


def read_jobs(plan):
    p = os.path.join(C.RESULTS, plan["cluster"], "jobs.csv")
    return C.read_csv(p) if os.path.exists(p) else []


def used_core_hours(jobs):
    """Core-hours charged so far: from the 'final' rows (qstat), else from the job's own start/end rows."""
    used, finals, starts = 0.0, set(), {}
    for r in jobs:
        if r["event"] == "final" and r.get("core_hours_used"):
            used += float(r["core_hours_used"])
            finals.add(r["pbs_jobid"])
    for r in jobs:
        if r["pbs_jobid"] in finals:
            continue
        if r["event"] == "start":
            starts[r["pbs_jobid"]] = r
        elif r["event"] == "end" and r["pbs_jobid"] in starts:
            s = starts[r["pbs_jobid"]]
            t0 = datetime.datetime.strptime(s["utc"], "%Y-%m-%dT%H:%M:%SZ")
            t1 = datetime.datetime.strptime(r["utc"], "%Y-%m-%dT%H:%M:%SZ")
            used += (t1 - t0).total_seconds() * int(s["nodes"]) * int(s["ncpus_per_node"]) / 3600.0
    return used


# ----------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------
def cmd_status(plan, require_complete):
    per, problems, unplanned, invalid = gather(plan)
    out = []
    out.append("RUN PLAN %s (cluster=%s, frozen=%s, %d cells, %d jobs)" %
               (plan["plan"], plan["cluster"], plan.get("frozen"), len(plan["cells"]), len(plan["jobs"])))
    tot_f = tot_n = 0
    for gid, g in plan["groups"].items():
        f = sum(1 for cid in g["cells"] if filled(plan, cid, per))
        n = len(g["cells"])
        if g.get("graded", True):
            tot_f += f
            tot_n += n
        out.append("  %-11s %-6s filled %3d/%-3d  %s" % (gid, g["requirement"], f, n, g["description"]))
    uniq = [cid for cid in plan["cells"] if any(cid in g["cells"] for g in plan["groups"].values()
                                                if g.get("graded", True))]
    uf = sum(1 for cid in uniq if filled(plan, cid, per))
    out.append("  GRADED CELLS FILLED: %d/%d unique cells (%d/%d counted per group)" % (uf, len(uniq), tot_f, tot_n))

    reasons = set(x.get("cell") for x in plan.get("reruns", []) if x.get("reason"))
    for x in plan.get("reruns", []):  # a job-level rerun reason covers every cell of that job
        if x.get("job") and x.get("reason") and job_of(plan, x["job"]):
            reasons |= set(job_of(plan, x["job"])["cells"])
    reruns = [cid for cid, jobs in per.items() if len(jobs) > 1]
    unexplained = [cid for cid in reruns if cid not in reasons]
    out.append("  reruns (cell run in >1 job): %d, without a recorded reason: %d%s" %
               (len(reruns), len(unexplained), (" -> " + ", ".join(unexplained[:5])) if unexplained else ""))
    ujobs = set(x.get("job") for x in plan.get("unplanned", []) if x.get("reason"))
    planned_jobs = set(j["id"] for j in plan["jobs"])
    jobs = read_jobs(plan)
    pbs_to_job = dict((r["pbs_jobid"], r["job"]) for r in jobs)
    bad_unplanned = [r for r in unplanned if pbs_to_job.get(r["pbs_jobid"]) not in ujobs]
    out.append("  rows outside the plan: %d, without a recorded reason: %d" % (len(unplanned), len(bad_unplanned)))
    out.append("  rows from binaries not qualified on %s (ignored): %d" % (plan["cluster"], len(invalid)))
    for p in problems[:5]:
        out.append("  PROBLEM: %s" % p)
    off_plan_jobs = sorted(set(r["job"] for r in jobs if r["job"] not in planned_jobs and r["job"] not in ujobs))
    if off_plan_jobs:
        out.append("  PBS jobs not in the plan and without a reason: %s" % ", ".join(off_plan_jobs))

    # core-hours
    safety = plan["model"]["safety"]
    est_total = est_hi = 0.0
    out.append("  core-hours by job (estimate x1 / with safety x%.0f; walltime requested):" % safety)
    for j in plan["jobs"]:
        secs, cores = job_estimate(plan, j)
        ch = secs * cores / 3600.0
        sf = job_safety(plan, j)
        est_total += ch
        est_hi += ch * sf
        out.append("    %-30s %d node%s x %3d cores  %6.1f / %6.1f core-h  walltime %s  (%d cells)" %
                   (j["id"], j["nodes"], "s" if j["nodes"] > 1 else " ", cores // j["nodes"], ch, ch * sf,
                    walltime(secs, sf), len(j["cells"])))
    used = used_core_hours(jobs)
    budget = plan.get("core_hour_budget")
    if isinstance(budget, (int, float)):
        btxt = "%.0f" % budget
    elif budget:
        btxt = "%s (%s)" % (budget, plan.get("budget_source", ""))
    else:
        btxt = "UNKNOWN (%s)" % plan.get("budget_source", "")
    out.append("  CORE-HOURS: estimated %.0f (up to %.0f with the walltime safety factors, x%.0f Poisson, x%.0f graph); "
               "used so far %.1f; budget %s" % (est_total, est_hi, safety, GP.model(plan)["safety"], used, btxt))
    if isinstance(budget, (int, float)) and est_hi > budget:
        out.append("  WARNING: the plan may exceed the budget")
    print("\n".join(out))
    complete = uf == len(uniq) and not unexplained and not bad_unplanned and not problems and not off_plan_jobs
    if require_complete and not complete:
        print("RUN PLAN: INCOMPLETE (release refused)")
        return 1
    return 0


def coverage(plan):
    """Problems that stop this plan from answering the graded requirements. Empty list = covers them."""
    P = plan
    cells = P["cells"]
    bad = []
    g = P["groups"]

    def cores(c):
        return c["ranks"] * c["threads"]

    dev = P["cluster"] == "local"  # the local plan is development-only: job structure is checked, coverage is not
    not_met = []  # requirements a FALLBACK plan states it cannot meet (printed, never hidden)
    for need in (() if dev else ("serial", "strong", "weak", "layout", "variants")):
        if need not in g or not g[need]["cells"]:
            bad.append("group %s missing or empty" % need)
    if bad:
        return bad
    for d in (() if dev else (2, 3)):
        ser = [cells[x] for x in g["serial"]["cells"] if cells[x]["dim"] == d and cores(cells[x]) == 1]
        ns = sorted(set(c["n"] for c in ser))
        if len(ns) < 4:
            bad.append("serial %dD: fewer than 4 sizes" % d)
        elif ns[-1] ** d / float(ns[0] ** d) < 100:
            bad.append("serial %dD: sizes span less than 2 decades of N" % d)
        for grp in ("strong", "weak"):
            cs = [cells[x] for x in g[grp]["cells"] if cells[x]["dim"] == d]
            if not cs or max(cores(c) for c in cs) < 256:
                msg = "%s %dD: no run on >= 256 cores (largest %d)" % (grp, d, max([cores(c) for c in cs] or [0]))
                (not_met if P.get("fallback") else bad).append(msg)
            for v in set((c["cg"], c["halo"]) for c in cs):
                series = [c for c in cs if (c["cg"], c["halo"]) == v]
                if not any(cores(c) == 1 for c in series):
                    bad.append("%s %dD %s/%s: no 1-core baseline" % (grp, d, v[0], v[1]))
                if grp == "weak" and series:
                    per = [c["n"] ** d / float(c["ranks"]) for c in series]
                    if max(per) / min(per) > 1.1:
                        bad.append("weak %dD %s/%s: unknowns per rank vary by more than 10%%" % (d, v[0], v[1]))
        var = [cells[x] for x in g["variants"]["cells"] if cells[x]["dim"] == d]
        if set(c["decomp"] for c in var) != set(range(1, d + 1)):
            bad.append("variants %dD: not every decomposition 1..%d" % (d, d))
        if set(c["halo"] for c in var) != {"blocking", "overlap"} or set(c["cg"] for c in var) != {"classic",
                                                                                                   "pipelined"}:
            bad.append("variants %dD: halo or CG variant missing" % d)
    cpn = P["cores_per_node"]
    want = {72: [(1, 72), (2, 36), (4, 18), (8, 9), (72, 1)], 24: [(1, 24), (2, 12), (4, 6), (24, 1)],
            96: [(1, 96), (2, 48), (4, 24), (8, 12), (96, 1)]}.get(cpn, [])
    got = set((cells[x]["ranks"] // cells[x]["nodes"], cells[x]["threads"]) for x in g.get("layout", {}).get(
        "cells", []))
    if dev:
        want = []
    for w in want:
        if w not in got:
            bad.append("layout %dx%d per node missing" % w)
    if P["cluster"] == "vanda" and ("gpu" not in g or not any(cells[x].get("gpus", 0) >= 1
                                                              for x in g["gpu"]["cells"])):
        bad.append("no GPU run (X=OpenMP requires at least one GPU test)")
    # jobs
    seen = {}
    for j in P["jobs"]:
        for cid in j["cells"]:
            if cid not in cells:
                bad.append("job %s lists unknown cell %s" % (j["id"], cid))
                continue
            seen[cid] = seen.get(cid, 0) + 1
            c = cells[cid]
            if c["nodes"] != j["nodes"]:
                bad.append("cell %s needs %d nodes, job %s has %d" % (cid, c["nodes"], j["id"], j["nodes"]))
            if c.get("binary", "cpu") not in job_binaries(j):
                bad.append("cell %s binary %s in job %s (%s)" % (cid, c.get("binary"), j["id"], j.get("binary")))
            if c["ranks"] * c["threads"] > j["nodes"] * j["ncpus_per_node"]:
                bad.append("cell %s needs %d cores, job %s has %d" % (cid, c["ranks"] * c["threads"], j["id"],
                                                                       j["nodes"] * j["ncpus_per_node"]))
            if (c.get("queue") or "cpu") != (j.get("queue") or "cpu"):
                bad.append("cell %s is for queue %s but job %s goes to %s" % (cid, c.get("queue") or "cpu",
                                                                             j["id"], j.get("queue") or "cpu"))
        lim = P.get("limits", {}).get("serial" if j.get("queue") == "serial" else
                                       "gpu" if j.get("binary") == "offload" and "gpu" in P.get("limits", {})
                                       else "parallel")
        if lim:
            tot = j["nodes"] * j["ncpus_per_node"]
            if tot < lim.get("min_cpus", 1) or tot > lim.get("max_cpus", tot):
                bad.append("job %s asks for %d cores; its queue takes %d-%d (%s)" % (
                    j["id"], tot, lim.get("min_cpus", 1), lim.get("max_cpus", tot), P.get("limits_source", "")))
            if j["nodes"] > lim.get("max_nodes", j["nodes"]):
                bad.append("job %s asks for %d nodes; its queue takes %d" % (j["id"], j["nodes"], lim["max_nodes"]))
            g = j["nodes"] * j.get("gpus_per_node", 0)
            if g and not lim.get("min_gpus", 0) <= g <= lim.get("max_gpus", g):
                bad.append("job %s asks for %d GPUs; its queue takes %d-%d" % (j["id"], g, lim.get("min_gpus", 0),
                                                                             lim.get("max_gpus", g)))
    for cid in cells:
        if seen.get(cid, 0) != 1:
            bad.append("cell %s is in %d jobs (must be exactly 1)" % (cid, seen.get(cid, 0)))
    for u in P.get("unplanned", []):
        if not u.get("reason"):
            bad.append("unplanned entry without a reason: %s" % u)
    if not dev:  # the graph extension (E11, E12 and the graph rows of E2/E3/E8)
        gbad, gnot = GP.coverage(P)
        bad += gbad
        not_met += gnot
    P["_not_met"] = not_met
    return bad


def cmd_check(plan):
    bad = coverage(plan)
    if bad:
        print("RUN PLAN CHECK %s: REFUSED" % plan["plan"])
        for b in bad:
            print("  - %s" % b)
        return 1
    if plan["cluster"] == "local":
        print("RUN PLAN CHECK local: PASS (development plan: job structure only; its rows never reach the report)")
        return 0
    if plan.get("fallback"):
        print("RUN PLAN CHECK %s: PASS AS A FALLBACK PLAN (serial 2D+3D sizes, strong and weak with 1-core baselines, "
              "variants, layouts; every cell in exactly one job; every job inside its queue's limits)" % plan["plan"])
        print("  NOT MET on %s, by design:" % plan["plan"])
        for x in plan.get("_not_met", []):
            print("    - %s" % x)
        for x in plan.get("not_met", []):
            print("    - %s" % x)
        print("  The >=256-core strong and weak cells exist only in the Vanda plan.")
        return 0
    print("RUN PLAN CHECK %s: PASS (serial 2D+3D sizes, strong and weak to >=256 cores with 1-core baselines, "
          "variants, layouts%s; every cell in exactly one job)" %
          (plan["plan"], ", GPU" if plan["cluster"] == "vanda" else ""))
    return 0


def cmd_selftest():
    plan = load_plan("vanda")
    a = coverage(plan)
    broken = copy.deepcopy(plan)
    drop = [cid for cid in broken["groups"]["weak"]["cells"]
            if broken["cells"][cid]["ranks"] * broken["cells"][cid]["threads"] >= 256]
    broken["groups"]["weak"]["cells"] = [c for c in broken["groups"]["weak"]["cells"] if c not in drop]
    b = coverage(broken)
    ok = (not a) and any("weak" in x and "256" in x for x in b)
    print("  complete vanda plan:                         expected PASS     got %s" % ("PASS" if not a else
                                                                                     "REFUSED: %s" % a[:2]))
    print("  same plan without the >=256-core weak cells: expected REFUSED  got %s" %
          (("REFUSED: " + "; ".join(x for x in b if "weak" in x)) if b else "PASS"))
    at = load_plan("atlas")
    c0 = coverage(copy.deepcopy(at))
    big = copy.deepcopy(at)
    big["jobs"].append(dict(big["jobs"][-1], id="atlas-too-big", nodes=2, ncpus_per_node=96, cells=[]))
    big["jobs"].append(dict(big["jobs"][-1], id="atlas-too-small", nodes=1, ncpus_per_node=8, cells=[]))
    c1 = coverage(big)
    lim_ok = (not c0) and sum(1 for x in c1 if "its queue takes" in x) == 2
    ok = ok and lim_ok
    print("  atlas plan (fallback, real queue limits):    expected PASS     got %s" % ("PASS" if not c0 else c0[:2]))
    print("  atlas + a 192-core and an 8-core job:        expected REFUSED  got %s" %
          ("REFUSED: " + "; ".join(x for x in c1 if "its queue takes" in x)[:200] if c1 else "PASS"))
    # the graph part: no >=256-core graph-strong cells, and no BFS-order variant cells
    g1 = copy.deepcopy(plan)
    g1["groups"]["graph-strong"]["cells"] = [c for c in g1["groups"]["graph-strong"]["cells"]
                                             if g1["cells"][c]["ranks"] * g1["cells"][c]["threads"] < 256]
    r1 = coverage(g1)
    g2 = copy.deepcopy(plan)
    g2["groups"]["graph-variants"]["cells"] = [c for c in g2["groups"]["graph-variants"]["cells"]
                                               if g2["cells"][c].get("order") != "bfs"]
    r2 = coverage(g2)
    gok = any("graph-strong" in x and "256" in x for x in r1) and any("graph-variants" in x for x in r2)
    ok = ok and gok
    print("  vanda without the >=256-core graph-strong cells: expected REFUSED  got %s" %
          (("REFUSED: " + "; ".join(x for x in r1 if "graph-strong" in x))[:160] if r1 else "PASS"))
    print("  vanda without the BFS-order graph variants:      expected REFUSED  got %s" %
          (("REFUSED: " + "; ".join(x for x in r2 if "graph-variants" in x))[:160] if r2 else "PASS"))
    print("SELFTEST run_plan check: %s" % ("QUALIFIED" if ok else "FAILED"))
    return 0 if ok else 1


def cell_args(c):
    if GP.is_graph(c):
        return GP.cell_args(c)
    a = ["--dim", str(c["dim"]), "--n", str(c["n"]), "--decomp", str(c["decomp"]), "--cg", c["cg"],
         "--halo", c["halo"]]
    if c["mode"] == "fixed":
        a += ["--iters", str(c["iters"]), "--repeats", str(c.get("repeats", 1))]
    else:
        a += ["--tol", repr(c["tol"]), "--maxit", "1000000", "--repeats", str(c.get("repeats", 1))]
    return a


def cmd_pbs(plan, jid):
    j = job_of(plan, jid)
    if j is None:
        print("RUN PLAN: REFUSED job %s is not in plan %s (add it to \"unplanned\" with a reason and a spec)" %
              (jid, plan["plan"]))
        return 1
    if not plan.get("frozen"):
        print("note: plan %s is not frozen yet (set \"frozen\": true before the first timed job)" % plan["plan"])
    cl = plan["cluster"]
    tpl_path = os.path.join(C.REPO, "cluster", cl, "job.pbs.in")
    with open(tpl_path) as f:
        tpl = f.read()
    secs, cores = job_estimate(plan, j)
    pbs = plan.get("pbs", {})
    jb = job_binaries(j)
    graph = "graph" in jb
    binary = "bin/p3cg_offload" if j.get("binary") == "offload" else "bin/p3graph" if graph else "bin/p3cg"
    path_of = {"cpu": "bin/p3cg", "graph": "bin/p3graph", "offload": "bin/p3cg_offload"}
    ncpus = j["ncpus_per_node"]
    select = job_select(plan, j)
    body = []
    if j.get("bind") == "none":
        # shared nodes (place=scatter): the job sees every core of a node, so binding ranks to cores could collide with
        # other users' jobs; p3_launch maps ranks per node and leaves the placement to the OS (cluster/vanda/env.sh)
        body.append("export P3_BIND=none")
    if graph:
        body += ['export P3_DATA="${P3_DATA:-$HOME/p3data}"   # SNAP data, outside the repository (fetch_snap.sh)',
                 'GREC="${REC%.csv}.graph.csv"']
        if j.get("validate_first"):
            # builds only bin/p3graph, bin/p3graph_bug1, bin/p3convert: the qualified bin/p3cg is not touched
            body += ["scripts/build.sh graph"]
            for dset in j.get("convert", []):
                body.append("scripts/convert_snap.sh %s \"$P3_DATA\"" % dset)
            body += ["python3 checks/validate_graph.py --qualify --binary bin/p3graph --bug-binary bin/p3graph_bug1"]
            for dset in j.get("convert", []):  # the seed lists (largest s of the sweep; smaller s use a prefix)
                body.append("p3_launch 1 1 1 bin/p3graph --graph \"$P3_DATA/csr/%s\" --s 20 --iters 1 --rhs 1 "
                            "--no-record --quiet --write-seeds \"results/%s/graph-seeds/%s-s20.txt\"" %
                            (dset, plan["cluster"], dset))
            if j.get("convert"):
                body.insert(len(body) - len(j["convert"]), "mkdir -p results/%s/graph-seeds" % plan["cluster"])
    elif j.get("validate_first"):
        flavor = "offload" if j.get("binary") == "offload" else "cpu"
        sfx = "_offload" if flavor == "offload" else ""
        body += ["scripts/build.sh %s" % flavor,
                 "python3 checks/validate.py --qualify --binary bin/p3cg%s --bug-binary bin/p3cg%s_bug1 "
                 "--bug-binary bin/p3cg%s_bug2" % (sfx, sfx, sfx)]
    if j["cells"]:
        for b in sorted(jb):  # one gate per program the job runs
            body.append("python3 checks/timing_gate.py --binary %s%s" % (path_of[b], " --require-cases G1,G2"
                                                                          if b == "graph" else ""))
    for i, cid in enumerate(j["cells"]):
        c = plan["cells"][cid]
        group = [g for g, v in plan["groups"].items() if cid in v["cells"]][0]
        rpn = -(-c["ranks"] // c["nodes"])
        rb = "P3_REPORT_BINDINGS=1 " if i == 0 else ""
        if c.get("placement"):
            group = "%s@%s" % (group, c["placement"])  # the row records where it ran (tag column)
        if GP.is_graph(c):
            # a graph cell that fails (data-dependent, e.g. memory) is reported and the job goes on to the next
            body.append("%sp3_launch %d %d %d %s --graph \"$P3_DATA/csr/%s\" %s --cell %s --tag %s --record "
                        "\"$GREC\" || echo \"p3: graph cell %s FAILED (exit $?)\" >&2" %
                        (rb, c["ranks"], rpn, c["threads"], path_of["graph"], c["dataset"],
                         " ".join(shlex.quote(x) for x in cell_args(c)), cid, group, cid))
            continue
        body.append("%sp3_launch %d %d %d %s %s --cell %s --tag %s --record \"$REC\"" %
                    (rb, c["ranks"], rpn, c["threads"], path_of[c.get("binary", "cpu")],
                     " ".join(shlex.quote(x) for x in cell_args(c)), cid, group))
    repl = {
        "{{JOBNAME}}": (("p3g-" + jid.split("-graph-", 1)[1]) if graph and "-graph-" in jid else ("p3-" + jid))[:15],
        "{{PLANJOB}}": jid,
        "{{PLAN}}": plan["plan"],
        "{{SELECT}}": select,
        "{{PLACE}}": j.get("place", pbs.get("place", "excl")),
        "{{WALLTIME}}": walltime(secs, job_safety(plan, j)),
        "{{QUEUE_LINE}}": ("#PBS -q %s" % job_queue(plan, j)) if job_queue(plan, j) else
        "# queue: cluster default (set pbs.queue_cpu / queue_serial / queue_gpu in the plan from the discovery)",
        "{{PROJECT_LINE}}": ("#PBS -P %s" % pbs["project"]) if pbs.get("project") else
        "# project: none set (set pbs.project in the plan if the cluster requires one)",
        "{{ESTIMATE}}": "%.0f s, %.1f core-hours (x%.0f safety in walltime)" %
                        (secs, secs * cores / 3600.0, job_safety(plan, j)),
        "{{BODY}}": "\n".join(body) if body else "true",
        "{{CPN}}": str(ncpus),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    outd = os.path.join(C.GENERATED, plan["plan"])
    if not os.path.isdir(outd):
        os.makedirs(outd)
    outp = os.path.join(outd, "%s.pbs" % jid)
    with open(outp, "w") as f:
        f.write(tpl)
    shown = os.path.relpath(outp, C.REPO) if outp.startswith(C.REPO) else outp
    print("wrote %s (%d cells, walltime %s)" % (shown, len(j["cells"]), repl["{{WALLTIME}}"]))
    return 0


def jobs_event(plan, jid, event):
    j = job_of(plan, jid)
    if j is None:
        print("RUN PLAN: REFUSED job %s is not in plan %s and has no recorded reason" % (jid, plan["plan"]))
        return 1
    import socket
    C.append_csv(os.path.join(C.RESULTS, plan["cluster"], "jobs.csv"), JOBS_COLUMNS, {
        "pbs_jobid": os.environ.get("PBS_JOBID", "none"), "plan": plan["plan"], "job": jid, "event": event,
        "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nodes": j["nodes"], "ncpus_per_node": j["ncpus_per_node"], "gpus_per_node": j.get("gpus_per_node", 0),
        "host": socket.gethostname()})
    if event == "start":
        write_job_env(plan, jid)
    print("RUN PLAN: job %s %s recorded" % (jid, event))
    return 0


def write_job_env(plan, jid):
    """The machine a job ran on, for the report's environment table: results/<cluster>/env/<PBS_JOBID>.json."""
    import platform
    import socket
    env = {"pbs_jobid": os.environ.get("PBS_JOBID", "none"), "plan": plan["plan"], "job": jid,
           "host": socket.gethostname(), "os": platform.platform(), "cpus_visible": os.cpu_count(),
           "modules": os.environ.get("LOADEDMODULES", ""), "cpu_model": "", "sockets": None, "mem_total_gb": None}
    try:
        with open("/proc/cpuinfo") as f:
            phys = set()
            for line in f:
                if line.startswith("model name") and not env["cpu_model"]:
                    env["cpu_model"] = line.split(":", 1)[1].strip()
                if line.startswith("physical id"):
                    phys.add(line.split(":", 1)[1].strip())
            env["sockets"] = len(phys) or None
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    env["mem_total_gb"] = round(int(line.split()[1]) / 1048576.0, 1)
    except OSError:
        pass
    for tool, cmd in (("mpirun", ["mpirun", "--version"]), ("cxx", [os.environ.get("CXX_MPI", "mpicxx"), "--version"])):
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                                 timeout=60).stdout
            env[tool] = out.strip().splitlines()[0] if out.strip() else ""
        except Exception:
            env[tool] = ""
    d = os.path.join(C.RESULTS, plan["cluster"], "env")
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(os.path.join(d, "%s.json" % env["pbs_jobid"].replace("/", "_")), "w") as f:
        json.dump(env, f, indent=1)


def cmd_run_local(plan, jid):
    if plan["cluster"] != "local":
        print("RUN PLAN: REFUSED `run` executes only the local plan; cluster jobs go through `pbs` + qsub")
        return 1
    j = job_of(plan, jid)
    if j is None:
        print("RUN PLAN: REFUSED job %s is not in plan local" % jid)
        return 1
    graph = j.get("binary") == "graph"
    binary = os.path.join(C.REPO, "bin", "p3graph" if graph else "p3cg")
    gate = subprocess.run([sys.executable, os.path.join(C.REPO, "checks", "timing_gate.py"), "--binary", binary] +
                          (["--require-cases", "G1,G2"] if graph else []))
    if gate.returncode != 0:
        return 1
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = os.path.join(C.RESULTS, "local", ("graph-%s" + C.GRAPH_SUFFIX if graph else "smoke-%s.csv") % stamp)
    launcher = C.default_launcher()
    for cid in j["cells"]:
        c = plan["cells"][cid]
        group = [g for g, v in plan["groups"].items() if cid in v["cells"]][0]
        env = dict(os.environ)
        env["OMP_NUM_THREADS"] = str(c["threads"])
        pre = ["--graph", os.path.join(C.DATA, "csr", c["dataset"])] if graph else []
        cmd = launcher + ["-np", str(c["ranks"]), binary] + pre + cell_args(c) + \
            ["--cell", cid, "--tag", group, "--record", rec, "--quiet"]
        p = subprocess.run(cmd, env=env, cwd=C.REPO, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            print("cell %s failed (exit %d)" % (cid, p.returncode))
            return 1
        print("  ran %s" % cid)
        sys.stdout.flush()
    print("RUN PLAN: local job %s done -> %s" % (jid, os.path.relpath(rec, C.REPO)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "check", "pbs", "run", "job-start", "job-end", "selftest"])
    ap.add_argument("--plan", default="vanda")
    ap.add_argument("--job")
    ap.add_argument("--require-complete", action="store_true")
    a = ap.parse_args()
    if a.command == "selftest":
        return cmd_selftest()
    plan = load_plan(a.plan)
    if a.command == "status":
        return cmd_status(plan, a.require_complete)
    if a.command == "check":
        return cmd_check(plan)
    if not a.job:
        ap.error("--job is required")
    if a.command == "pbs":
        return cmd_pbs(plan, a.job)
    if a.command == "run":
        return cmd_run_local(plan, a.job)
    return jobs_event(plan, a.job, "start" if a.command == "job-start" else "end")


if __name__ == "__main__":
    sys.exit(main())
