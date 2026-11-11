#!/usr/bin/env python3
"""Turns a discovery file (cluster/ops/discover.sh) into PROPOSED changes, shown as a diff. Writes nothing unless
--apply is given.

  python3 scripts/apply_discovery.py results/atlas/env/discover-<utc>.txt [--user NAME]           proposal + diff
  python3 scripts/apply_discovery.py results/atlas/env/discover-<utc>.txt [--user NAME] --apply   write that diff

Queues. A queue is usable only if it is an Execution queue, enabled and started, not "from_route_only", and either
not ACL-restricted or with the user in its acl_users (the user comes from the discovery's "user" section, --user, or
P3_CLUSTER_USER; with no user, ACL queues count as unusable). For a usable queue the per-job core range is
[resources_min.ncpus, min(resources_max.ncpus, max_run_res.ncpus for this user or PBS_GENERIC)]. queue_cpu is the
usable multi-core queue that holds the plan's largest parallel job (else the largest range), queue_serial the usable
1-core queue. Every job in the plan is then checked against its queue's range; a job outside it is a WARNING.

Also proposes: project code and extra select resources from the Vanda sample scripts (`hpc cpu`, `hpc gpu`), memory
per core (from the nodes of the queue's node pool, or the sample), core_hour_budget, and module names in
cluster/<cluster>/env.sh. Checks without writing: cores per node of the pool against the plan, walltime limits, the
GPU node shape, the Python version. Every value prints the discovery lines it came from.
"""
import argparse
import difflib
import json
import math
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
import run_plan as RP  # noqa: E402

CLUSTER_DIR = os.environ.get("P3_CLUSTER_DIR") or os.path.join(REPO, "cluster")


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^=== (.+?) ===\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return dict((k, "\n".join(v)) for k, v in out.items())


def directives(sample):
    d = {}
    for line in sample.splitlines():
        m = re.match(r"^#PBS\s+-(\w)\s+(.*)$", line.strip())
        if m:
            d.setdefault(m.group(1), []).append(m.group(2).strip())
    return d


def select_extra(sel, drop=("ncpus", "mpiprocs", "ngpus", "ompthreads", "mem")):
    """'select=1:ncpus=72:mpiprocs=72:mem=200gb:host=x' -> ':host=x' (memory is handled per core)"""
    parts = sel.split("=", 1)[1].split(":")[1:] if sel.startswith("select=") else []
    return "".join(":" + p for p in parts if p.split("=")[0] not in drop)


def parse_blocks(text, head):
    """`qstat -Qf` / `pbsnodes -a` style blocks; tab-indented lines continue the previous value."""
    out, cur, last = {}, None, None
    for line in text.splitlines():
        m = re.match(head, line)
        if m:
            cur = out.setdefault(m.group(1), {})
            last = None
            continue
        if cur is None:
            continue
        m = re.match(r"^\s+([\w.]+)\s=\s(.*)$", line)
        if m and not line.startswith("\t"):
            last = m.group(1)
            cur[last] = m.group(2).strip()
        elif line.startswith("\t") and last:
            cur[last] += line.strip()
    return out


def gb(s):
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgt]?b)$", (s or "").strip().lower())
    if not m:
        return None
    return float(m.group(1)) * {"kb": 1 / 1048576.0, "mb": 1 / 1024.0, "gb": 1.0, "tb": 1024.0, "b": 1e-9}[m.group(2)]


def hms(s):
    try:
        p = [int(x) for x in s.split(":")]
        return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)
    except (ValueError, AttributeError, IndexError):
        return None


def per_user(field, user):
    """'[u:PBS_GENERIC=96]' or '[u:alice=200]' -> the limit that applies to user."""
    if not field:
        return None
    ent = dict((k, int(v)) for k, v in re.findall(r"u:([^=\],]+)=(\d+)", field))
    if user and user in ent:
        return ent[user]
    return ent.get("PBS_GENERIC")


def acl_has(acl, user):
    if not user:
        return False
    for a in acl.split(","):
        a = a.strip()
        if a and (a == user or a.split("@")[0] == user):
            return True
    return False


def queue_verdicts(qs, user):
    """{queue: (usable, reason, min_cpus, max_cpus_per_job, max_run_per_user)}"""
    out = {}
    for q, v in qs.items():
        reason = None
        if v.get("queue_type", "Execution") != "Execution":
            reason = "%s queue" % v.get("queue_type")
        elif v.get("enabled", "True") != "True":
            reason = "disabled"
        elif v.get("started", "True") != "True":
            reason = "not started"
        elif v.get("from_route_only") == "True":
            reason = "accepts jobs only from a routing queue"
        elif v.get("acl_user_enable") == "True" and not acl_has(v.get("acl_users", ""), user):
            reason = "restricted to named users (ACL)%s" % ("" if user else "; user unknown")
        mn = int(v.get("resources_min.ncpus", "1") or 1)
        mx = v.get("resources_max.ncpus")
        cap = per_user(v.get("max_run_res.ncpus"), user)
        caps = [int(x) for x in (mx, cap) if x not in (None, "")]
        out[q] = (reason is None, reason or "usable", mn, min(caps) if caps else None,
                  per_user(v.get("max_run"), user))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("discovery")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--user", default=os.environ.get("P3_CLUSTER_USER"))
    a = ap.parse_args()
    text = open(a.discovery).read()
    S = sections(text)
    cl = "vanda" if ("hpc_cpu" in S or "/vanda/" in a.discovery) else "atlas"
    m = re.search(r"^user:\s*(\S+)", S.get("user", ""), re.M)
    user = m.group(1) if m else a.user
    plan_p = RP.plan_path(cl)
    plan = RP.load_plan(cl)
    new = json.loads(json.dumps(plan))
    pbs = new.setdefault("pbs", {})
    notes, warn = [], []
    print("DISCOVERY PROPOSAL for %s from %s (user: %s)" % (
        cl, os.path.relpath(a.discovery, REPO) if a.discovery.startswith(REPO) else a.discovery,
        user or "unknown"))

    # --- queues ----------------------------------------------------------------------------------------------
    qs = parse_blocks(S.get("qstat_Qf", ""), r"^Queue:\s*(\S+)")
    V = queue_verdicts(qs, user)
    if V:
        print("  queues (usable or why not; cores per job; jobs at once per user):")
        for q in sorted(V, key=lambda k: (not V[k][0], k)):
            ok, why, mn, mx, mr = V[q]
            print("    %-16s %-46s cores %s-%s%s" % (q, why, mn, mx if mx is not None else "?",
                                                    ("; max %d running" % mr) if mr else ""))
    dc, dg = directives(S.get("hpc_cpu", "")), directives(S.get("hpc_gpu", ""))
    par_jobs = [j for j in plan["jobs"] if j.get("queue", "cpu") == "cpu" and j.get("binary", "cpu") == "cpu"]
    need = max([j["nodes"] * j["ncpus_per_node"] for j in par_jobs] or [1])
    if dc.get("q"):
        q = dc["q"][0]
        pbs["queue_cpu"] = q
        notes.append("queue_cpu = %s   <- `hpc cpu` sample: #PBS -q %s" % (q, q))
        if q in V and not V[q][0]:
            warn.append("the sample's queue %s is not usable: %s" % (q, V[q][1]))
    else:
        multi = [(q, v) for q, v in V.items() if v[0] and v[3] is not None and v[3] > 1]
        fits = [x for x in multi if x[1][3] >= need]
        pick = sorted(fits or multi, key=lambda x: (-int(qs[x[0]].get("Priority", "0") or 0), -x[1][3]))[:1] \
            if (fits or multi) else []
        if pick:
            q, v = pick[0]
            pbs["queue_cpu"] = q
            notes.append("queue_cpu = %s   <- usable, cores %d-%d per job%s" % (
                q, v[2], v[3], "" if fits else "; NOTE: below the plan's largest job (%d cores)" % need))
        else:
            warn.append("no usable multi-core queue found")
    ser = [q for q, v in V.items() if v[0] and v[3] == 1]
    if ser:
        pbs["queue_serial"] = sorted(ser)[0]
        notes.append("queue_serial = %s   <- usable 1-core queue" % pbs["queue_serial"])
    if dg.get("q"):
        pbs["queue_gpu"] = dg["q"][0]
        notes.append("queue_gpu = %s   <- `hpc gpu` sample: #PBS -q %s" % (dg["q"][0], dg["q"][0]))
    proj = (dc.get("P") or dg.get("P") or [None])[0]
    if proj:
        pbs["project"] = proj
        notes.append("project = %s   <- #PBS -P in the sample script" % proj)
    for key, dd in (("select_extra", dc), ("select_extra_gpu", dg)):
        sel = [x for x in dd.get("l", []) if x.startswith("select=")]
        if sel and select_extra(sel[0]):
            pbs[key] = select_extra(sel[0])
            notes.append("%s = %s   <- sample `%s`" % (key, pbs[key], sel[0]))

    # --- nodes of the queue's pool: cores and memory per node ------------------------------------------------
    nodes = parse_blocks(S.get("pbsnodes", ""), r"^(\S+)\s*$")
    qc = pbs.get("queue_cpu")
    pool = qs.get(qc, {}).get("default_chunk.node_pool") if qc else None
    in_pool = [n for n in nodes.values() if pool and n.get("resources_available.node_pool") == pool]
    if in_pool:
        src = "the %d nodes of pool %s" % (len(in_pool), pool)
        cand = in_pool
    else:
        cand = [n for n in nodes.values() if n.get("resources_available.ncpus")]
        src = ("the most common node type (pool %s membership is not in this discovery file: CHECK)" % pool
               if pool else "the most common node type")
    cpn = mem_gb = None
    if cand:
        cpn = Counter(int(n["resources_available.ncpus"]) for n in cand).most_common(1)[0][0]
        mems = [gb(n.get("resources_available.mem")) for n in cand if int(n["resources_available.ncpus"]) == cpn]
        mems = [x for x in mems if x]
        mem_gb = min(mems) if mems else None
    sc = [int(x) for x in re.findall(r"ncpus=(\d+)", " ".join(dc.get("l", [])))]
    sm = [gb(x) for x in re.findall(r"mem=(\w+)", " ".join(dc.get("l", [])))]
    if sc:
        cpn = sc[0]
        src = "the `hpc cpu` sample"
        mem_gb = sm[0] if sm and sm[0] else mem_gb
    if cpn:
        if cpn != plan["cores_per_node"]:
            warn.append("cores per node %d (%s) != %d in the plan: regenerate the plan (scripts/make_plan.py) before "
                        "freezing it" % (cpn, src, plan["cores_per_node"]))
        else:
            notes.append("cores per node: %d (%s), as the plan assumes" % (cpn, src))
    if cpn and mem_gb:
        per = math.floor(mem_gb / cpn * 0.85 * 10) / 10.0
        pbs["mem_per_cpu_gb"] = per
        notes.append("mem_per_cpu_gb = %.1f   <- %.0f GB per %d-core node (%s), 85%% of it per core" %
                     (per, mem_gb, cpn, src))
    qmin_mem = gb(qs.get(qc, {}).get("resources_min.mem")) if qc else None
    if qmin_mem:
        notes.append("queue %s requires at least %.0f GB per job: every job script requests mem" % (qc, qmin_mem))

    # --- every planned job against its queue -------------------------------------------------------------------
    for j in new["jobs"]:
        kind = j.get("queue", "cpu")
        q = pbs.get("queue_serial") if kind == "serial" else pbs.get("queue_gpu") if j.get("binary") == "offload" \
            else pbs.get("queue_cpu")
        if not q or q not in V:
            continue
        ok, why, mn, mx, mr = V[q]
        tot = j["nodes"] * j["ncpus_per_node"]
        if not ok:
            warn.append("job %s: queue %s is not usable (%s)" % (j["id"], q, why))
        elif tot < mn or (mx is not None and tot > mx):
            warn.append("job %s needs %d cores; queue %s allows %s-%s per job" % (j["id"], tot, q, mn, mx))
        w = hms(qs[q].get("resources_max.walltime", ""))
        est = RP.job_estimate(plan, j)[0] * RP.model_of(plan)["safety"]
        if w and est > w:
            warn.append("job %s may need %.0f s; queue %s allows %d s" % (j["id"], est, q, w))
    bad = [w for w in warn if w.startswith("job ")]
    if not bad and V:
        notes.append("every planned job fits its queue's core range and walltime")

    # --- budget ----------------------------------------------------------------------------------------------
    hp = S.get("hpc_project", "") + "\n" + S.get("hpc_quota", "")
    m = (re.search(r"core[- ]?hours?[^\n]*?balance\s*:?\s*([\d,.]+)", hp, re.I) or
         re.search(r"balance\s*:?\s*([\d,.]+)", hp, re.I) or re.search(r"remaining\s*:?\s*([\d,.]+)", hp, re.I))
    if m:
        new["core_hour_budget"] = float(m.group(1).replace(",", ""))
        new["budget_source"] = "`hpc project` balance (%s)" % os.path.basename(a.discovery)
        notes.append("core_hour_budget = %s   <- `hpc project`: %s" % (new["core_hour_budget"], m.group(0).strip()[:80]))
    elif cl == "atlas":
        new["core_hour_budget"] = "unlimited"
        new["budget_source"] = "Lecture 8: Atlas is CPU only, slow, unlimited use (no allocation shown by hpc)"
        notes.append("core_hour_budget = unlimited   <- no allocation reported; Lecture 8: Atlas use is unlimited")
    else:
        warn.append("no core-hour balance found in `hpc project`/`hpc quota`; set core_hour_budget by hand")

    # --- GPU shape, Python -----------------------------------------------------------------------------------
    g = [x for x in dg.get("l", []) if x.startswith("select=")]
    gj = [j for j in new["jobs"] if j.get("binary") == "offload"]
    if g and gj:
        ng, nc = re.search(r"ngpus=(\d+)", g[0]), re.search(r"ncpus=(\d+)", g[0])
        if ng and nc:
            if int(ng.group(1)) < gj[0]["gpus_per_node"]:
                warn.append("GPU nodes offer %s GPUs per job chunk; the plan's 2-GPU cells need 2" % ng.group(1))
            gj[0]["ncpus_per_node"] = int(nc.group(1))
            notes.append("GPU job shape: ncpus=%s, ngpus=%s per node   <- `hpc gpu` sample" % (nc.group(1),
                                                                                        ng.group(1)))
    py = re.search(r"Python (\d+)\.(\d+)", S.get("tools", ""))
    if py and (int(py.group(1)), int(py.group(2))) < (3, 5):
        warn.append("python3 is %s.%s; the checks need >= 3.5" % py.groups())
    elif py:
        notes.append("python3 %s.%s on the login node (checks need >= 3.5)" % py.groups())

    # --- modules -----------------------------------------------------------------------------------------------
    env_txt = S.get("module_env", "")
    if "ebenv: sourced" in env_txt:
        notes.append("EasyBuild environment: /app1/ebenv sourced before listing modules")
    elif cl == "atlas":
        warn.append("this discovery comes from the old discover.sh: its module list was cut at 300 lines (A-B "
                    "only, so no OpenMPI/foss/CMake) and it does not record whether /app1/ebenv was sourced; re-run "
                    "cluster/ops/discover.sh atlas8")
    mods = [l.strip() for l in S.get("module_avail", "").splitlines() if l.strip() and "/" in l
            and not l.strip().endswith(":")]
    env_p = os.path.join(CLUSTER_DIR, cl, "env.sh")
    env_old = open(env_p).read()
    env_new = env_old

    def set_default(text, var, value):
        return re.sub(r'(: "\$\{%s:=)([^}]*)(\}")' % var, lambda mm: mm.group(1) + value + mm.group(3), text)

    def newest(prefix, pat=None):
        c = [x for x in mods if x.startswith(prefix + "/") and (pat is None or re.search(pat, x))]
        return sorted(c, key=lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)])[-1] if c else None

    if cl == "vanda":
        want = "nvhpc-hpcx-cuda12/26.1"
        if want in mods:
            notes.append("module %s is available (Lecture 12's recommendation); env.sh keeps it" % want)
        else:
            alt = newest("nvhpc-hpcx-cuda12") or newest("nvhpc-hpcx") or newest("nvhpc")
            if alt:
                env_new = set_default(set_default(env_new, "P3_MODULES_CPU", alt), "P3_MODULES_GPU", alt)
                notes.append("modules: %s not listed; proposing %s" % (want, alt))
            else:
                warn.append("no nvhpc module listed; choose the MPI and compiler modules by hand")
    else:
        tc = newest("foss", r"^foss/20\d\d[ab]$") or newest("OpenMPI")
        if tc:
            env_new = set_default(env_new, "P3_MODULES", tc)
            notes.append("modules: P3_MODULES = %s   <- newest %s in `module avail` after ebenv" %
                         (tc, "foss toolchain (GCC + OpenMPI)" if tc.startswith("foss") else "OpenMPI"))
        else:
            notes.append("modules: no foss/OpenMPI in this discovery; env.sh picks the newest foss at job time "
                         "(and refuses the 2013 mvapich2 mpicxx)")

    for n in notes:
        print("  " + n)
    for w in warn:
        print("  WARNING: " + w)
    old_txt = open(plan_p).read()
    new_txt = json.dumps(new, indent=1) + "\n"
    shown = lambda p: os.path.relpath(p, REPO) if p.startswith(REPO) else p  # noqa: E731
    diff = list(difflib.unified_diff(old_txt.splitlines(True), new_txt.splitlines(True), shown(plan_p),
                                     "(proposed)", n=1))
    diff += list(difflib.unified_diff(env_old.splitlines(True), env_new.splitlines(True), shown(env_p),
                                      "(proposed)", n=1))
    print("PROPOSED DIFF (%d lines):" % len(diff))
    sys.stdout.write("".join(diff) or "  (no change)\n")
    if plan.get("frozen") and diff:
        print("  note: the plan is frozen; these fields (queues, memory, budget, job shape) do not change its cells")
    if a.apply:
        with open(plan_p, "w") as f:
            f.write(new_txt)
        with open(env_p, "w") as f:
            f.write(env_new)
        print("APPLIED to %s and %s. Next: review, commit, then cluster/ops/sync.sh" % (shown(plan_p), shown(env_p)))
    else:
        print("nothing written (re-run with --apply to write exactly this diff)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
