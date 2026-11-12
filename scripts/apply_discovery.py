#!/usr/bin/env python3
"""Turns a discovery file (cluster/ops/discover.sh) into PROPOSED changes, shown as a diff. Writes nothing unless
--apply is given.

  python3 scripts/apply_discovery.py results/<cluster>/env/discover-<utc>.txt [options]           proposal + diff
  python3 scripts/apply_discovery.py results/<cluster>/env/discover-<utc>.txt [options] --apply   write that diff

Options for what discovery cannot read non-interactively (each is noted as "given on the command line"):
  --project NAME         PBS project (-P). Vanda's `hpc project` needs `amgr login` (NUS password).
  --budget-cpu H / --budget-gpu H / --budget-source TEXT   allocation in CPU- and GPU-hours and where it was read.
  --mem-per-cpu-gb G     memory per requested core, overriding the value derived from the nodes.
  --user NAME            for discovery files without a "user" section (ACL checks).

Queues. Execution queues are usable if enabled, started, ACL-free or listing the user, and either accept direct
submission or are reached through a usable routing queue (route_destinations). Vanda's own sample scripts submit with
`-P <project>` and no `-q`: the server's default queue (qstat -Bf default_queue, else the routing queue `auto` the
samples imply) routes CPU jobs to batch_cpu and GPU jobs (ngpus >= 1) to batch_gpu. Then queue_cpu/queue_gpu stay
empty (no -q line), and every planned job is checked against the execution queue it lands in: cores, nodes, GPUs,
walltime, per-user caps.

Colour codes in the `hpc` output (Vanda prints the samples in ANSI colour) are stripped before parsing.
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
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def sections(text):
    out, cur = {}, None
    for line in ANSI.sub("", text).splitlines():
        m = re.match(r"^=== (.+?) ===\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return dict((k, "\n".join(v)) for k, v in out.items())


def directives(sample):
    """Active #PBS lines only (a commented '##PBS -q auto_free' is not a directive)."""
    d = {}
    for line in ANSI.sub("", sample).splitlines():
        m = re.match(r"^#PBS\s+-(\w)\s+(.*?)\s*$", line.strip())
        if m:
            d.setdefault(m.group(1), []).append(m.group(2).strip())
    return d


def select_extra(sel, drop=("ncpus", "mpiprocs", "ngpus", "ompthreads", "mem")):
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
        m = re.match(r"^\s+([\w.-]+)\s=\s(.*)$", line)
        if m and not line.startswith("\t"):
            last = m.group(1)
            if last in cur and last.startswith("max_run"):  # repeated per-user entries
                cur[last] += "," + m.group(2).strip()
            else:
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
    if not field:
        return None
    ent = dict((k, int(v)) for k, v in re.findall(r"u:([^=\],]+)=(\d+)", field))
    if user and user in ent:
        return ent[user]
    return ent.get("PBS_GENERIC")


def acl_has(acl, user):
    if not user:
        return False
    return any(a.strip() and (a.strip() == user or a.strip().split("@")[0] == user) for a in acl.split(","))


def queue_verdicts(qs, user):
    """{queue: (usable, reason, min_cpus, max_cpus_per_job, max_run_per_user)} with routing resolved."""
    def own(v):
        if v.get("enabled", "True") != "True":
            return "disabled"
        if v.get("started", "True") != "True":
            return "not started"
        if v.get("acl_user_enable") == "True" and not acl_has(v.get("acl_users", ""), user):
            return "restricted to named users (ACL)%s" % ("" if user else "; user unknown")
        return None
    routes = {}
    for q, v in qs.items():
        if v.get("queue_type") == "Route" and own(v) is None:
            for d in [x.strip() for x in v.get("route_destinations", "").split(",") if x.strip()]:
                routes.setdefault(d, []).append(q)
    out = {}
    for q, v in qs.items():
        reason = own(v)
        if reason is None and v.get("queue_type") == "Route":
            reason = "routing queue -> %s" % v.get("route_destinations", "?")
        elif reason is None and v.get("from_route_only") == "True":
            reason = ("via route %s" % "/".join(routes[q])) if q in routes else "only from a routing queue (none usable)"
        usable = reason is None or reason.startswith("via route")
        mn = int(v.get("resources_min.ncpus", "1") or 1)
        caps = [int(x) for x in (v.get("resources_max.ncpus"), per_user(v.get("max_run_res.ncpus"), user))
                if x not in (None, "")]
        out[q] = (usable, reason or "usable", mn, min(caps) if caps else None, per_user(v.get("max_run"), user))
    return out, routes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("discovery")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--user", default=os.environ.get("P3_CLUSTER_USER"))
    ap.add_argument("--project")
    ap.add_argument("--budget-cpu", type=float)
    ap.add_argument("--budget-gpu", type=float)
    ap.add_argument("--budget-source")
    ap.add_argument("--mem-per-cpu-gb", type=float)
    a = ap.parse_args()
    S = sections(open(a.discovery).read())
    cl = "vanda" if ("hpc_cpu" in S or "/vanda/" in a.discovery) else "atlas"
    m = re.search(r"^user:\s*(\S+)", S.get("user", ""), re.M)
    user = m.group(1) if m else a.user
    plan_p = RP.plan_path(cl)
    plan = RP.load_plan(cl)
    new = json.loads(json.dumps(plan))
    pbs = new.setdefault("pbs", {})
    notes, warn = [], []
    shown = lambda p: os.path.relpath(p, REPO) if p.startswith(REPO) else p  # noqa: E731
    print("DISCOVERY PROPOSAL for %s from %s (user: %s)" % (cl, shown(a.discovery), user or "unknown"))

    # --- queues and routes -----------------------------------------------------------------------------------
    qs = parse_blocks(S.get("qstat_Qf", ""), r"^Queue:\s*(\S+)")
    V, routes = queue_verdicts(qs, user)
    if V:
        print("  queues (usable or why not; cores per job; jobs at once per user):")
        for q in sorted(V, key=lambda k: (not V[k][0], k)):
            ok, why, mn, mx, mr = V[q]
            print("    %-16s %-46s cores %s-%s%s" % (q, why[:46], mn, mx if mx is not None else "?",
                                                    ("; max %d running" % mr) if mr else ""))
    dc, dg = directives(S.get("hpc_cpu", "")), directives(S.get("hpc_gpu", ""))
    m = re.search(r"default_queue\s*=\s*(\S+)", S.get("qstat_Bf", ""))
    default_q = m.group(1) if m else None
    project_route = bool(dc.get("P")) and not dc.get("q")
    if project_route and not default_q and qs.get("auto", {}).get("queue_type") == "Route":
        default_q = "auto"
        notes.append("default queue: auto   <- assumed: the `hpc cpu`/`hpc gpu` samples submit with -P and no -q, and "
                     "`auto` is the routing queue to batch_cpu/batch_gpu (qstat -Bf not in this discovery)")
    elif default_q:
        notes.append("default queue: %s   <- qstat -Bf" % default_q)

    def dest(route, gpu):
        for d in [x.strip() for x in qs.get(route, {}).get("route_destinations", "").split(",") if x.strip()]:
            v = qs.get(d, {})
            needs_gpu = int(v.get("resources_min.ngpus", "0") or 0) >= 1
            no_gpu = v.get("resources_max.ngpus") == "0"
            if V.get(d, (False,))[0] and ((gpu and needs_gpu) or (not gpu and (no_gpu or not needs_gpu))):
                return d
        return None

    target = {}  # job kind -> execution queue the job lands in
    if project_route and default_q in qs and qs[default_q].get("queue_type") == "Route":
        pbs["queue_cpu"] = ""
        pbs["queue_gpu"] = ""
        target["cpu"], target["gpu"] = dest(default_q, False), dest(default_q, True)
        notes.append("queue_cpu = \"\", queue_gpu = \"\"   <- jobs carry -P and no -q; route %s sends CPU jobs to %s and "
                     "GPU jobs (ngpus >= 1) to %s" % (default_q, target["cpu"], target["gpu"]))
        for r in sorted(qs):
            if qs[r].get("queue_type") == "Route" and r != default_q and V[r][1].startswith("routing"):
                ds = qs[r].get("route_destinations", "")
                notes.append("other route, not used: -q %s -> %s" % (r, ", ".join(
                    "%s (cores %s-%s)" % (d.strip(), V[d.strip()][2], V[d.strip()][3]) for d in ds.split(",")
                    if d.strip() in V)))
    else:
        par = [j for j in plan["jobs"] if j.get("queue", "cpu") == "cpu" and j.get("binary", "cpu") == "cpu"]
        need = max([j["nodes"] * j["ncpus_per_node"] for j in par] or [1])
        if dc.get("q"):
            pbs["queue_cpu"] = dc["q"][0]
            notes.append("queue_cpu = %s   <- `hpc cpu` sample: #PBS -q %s" % (dc["q"][0], dc["q"][0]))
        else:
            multi = [(q, v) for q, v in V.items() if v[0] and v[3] is not None and v[3] > 1
                     and qs[q].get("queue_type") != "Route" and qs[q].get("from_route_only") != "True"]
            fits = [x for x in multi if x[1][3] >= need]
            pick = sorted(fits or multi, key=lambda x: (-int(qs[x[0]].get("Priority", "0") or 0), -x[1][3]))[:1]
            if pick:
                q, v = pick[0]
                pbs["queue_cpu"] = q
                notes.append("queue_cpu = %s   <- usable, cores %d-%d per job%s" % (
                    q, v[2], v[3], "" if fits else "; NOTE: below the plan's largest job (%d cores)" % need))
            else:
                warn.append("no usable multi-core queue found")
        target["cpu"] = pbs.get("queue_cpu")
        if dg.get("q"):
            pbs["queue_gpu"] = dg["q"][0]
            notes.append("queue_gpu = %s   <- `hpc gpu` sample" % dg["q"][0])
        target["gpu"] = pbs.get("queue_gpu")
        ser = [q for q, v in V.items() if v[0] and v[3] == 1 and qs[q].get("from_route_only") != "True"]
        if ser:
            pbs["queue_serial"] = sorted(ser)[0]
            notes.append("queue_serial = %s   <- usable 1-core queue" % pbs["queue_serial"])
    target["serial"] = pbs.get("queue_serial")

    # --- project ---------------------------------------------------------------------------------------------
    sample_p = (dc.get("P") or dg.get("P") or [None])[0]
    placeholder = sample_p and re.search(r"project[-_ ]?name", sample_p, re.I)
    if a.project:
        pbs["project"] = a.project
        notes.append("project = %s   <- given on the command line" % a.project)
        if user and a.project != "personal-%s" % user and "personal-" in S.get("hpc_gpu", ""):
            notes.append("  (the personal project would be personal-%s)" % user)
    elif sample_p and not placeholder:
        pbs["project"] = sample_p
        notes.append("project = %s   <- #PBS -P in the sample script" % sample_p)
    elif sample_p and user and "personal-" in S.get("hpc_gpu", "") + S.get("hpc_cpu", ""):
        pbs["project"] = "personal-%s" % user
        notes.append("project = personal-%s   <- inferred (the samples' text: '-P ... personal-<username>'); CHECK "
                     "with `hpc project` after `amgr login`, or pass --project" % user)
    elif sample_p:
        warn.append("the samples need a project (-P %s) and none could be read: pass --project" % sample_p)

    # --- select syntax ---------------------------------------------------------------------------------------
    for key, dd in (("select_extra", dc), ("select_extra_gpu", dg)):
        sel = [x for x in dd.get("l", []) if x.startswith("select=")]
        if sel and select_extra(sel[0]):
            pbs[key] = select_extra(sel[0])
            notes.append("%s = %s   <- sample `%s`" % (key, pbs[key], sel[0]))
    if any("ompthreads=" in x for x in dc.get("l", []) + dg.get("l", [])):
        pbs["select_ompthreads"] = True
        notes.append("select_ompthreads = true   <- the samples put ompthreads in every chunk (we request 1; each run "
                     "sets OMP_NUM_THREADS itself)")

    # --- nodes of the CPU pool: cores and memory per node ----------------------------------------------------
    nodes = parse_blocks(S.get("pbsnodes", ""), r"^(\S+)\s*$")
    tq = target.get("cpu")
    pool = qs.get(tq, {}).get("default_chunk.node_pool") if tq else None
    in_pool = [n for n in nodes.values() if pool and n.get("resources_available.node_pool") == pool
               and n.get("resources_available.ncpus")]
    if in_pool:
        cand, src = in_pool, "the %d nodes of pool %s" % (len(in_pool), pool)
    else:
        cand = [n for n in nodes.values() if n.get("resources_available.ncpus")]
        src = ("the most common node type (pool %s membership is not in this discovery file: CHECK)" % pool
               if pool else "the most common node type")
    cpn = mem_gb = None
    if cand:
        cpn = Counter(int(n["resources_available.ncpus"]) for n in cand).most_common(1)[0][0]
        mems = [gb(n.get("resources_available.mem")) for n in cand if int(n["resources_available.ncpus"]) == cpn]
        mems = [x for x in mems if x]
        mem_gb = Counter(round(x) for x in mems).most_common(1)[0][0] if mems else None
    if cpn:
        if cpn != plan["cores_per_node"]:
            warn.append("cores per node %d (%s) != %d in the plan: regenerate the plan before freezing it" %
                        (cpn, src, plan["cores_per_node"]))
        else:
            notes.append("cores per node: %d (%s), as the plan assumes; %s GB each" % (cpn, src, mem_gb))
    if a.mem_per_cpu_gb:
        pbs["mem_per_cpu_gb"] = a.mem_per_cpu_gb
        notes.append("mem_per_cpu_gb = %.1f   <- given on the command line (%d GB for %d cores; the nodes have %s GB)"
                     % (a.mem_per_cpu_gb, int(math.ceil(a.mem_per_cpu_gb * (cpn or 1))), cpn or 1, mem_gb))
    elif cpn and mem_gb:
        per = math.floor(mem_gb / cpn * 0.85 * 10) / 10.0
        pbs["mem_per_cpu_gb"] = per
        notes.append("mem_per_cpu_gb = %.1f   <- %.0f GB per %d-core node (%s), 85%% of it per core" %
                     (per, mem_gb, cpn, src))

    # --- GPU job shape from the GPU sample -----------------------------------------------------------------------
    g = [x for x in dg.get("l", []) if x.startswith("select=")]
    gj = [j for j in new["jobs"] if j.get("binary") == "offload"]
    if g and gj:
        ng, nc = re.search(r"ngpus=(\d+)", g[0]), re.search(r"ncpus=(\d+)", g[0])
        if ng and nc:
            per_gpu = int(nc.group(1)) // max(1, int(ng.group(1)))
            want = per_gpu * gj[0]["gpus_per_node"]
            gq = qs.get(target.get("gpu") or "", {})
            gmax = int(gq.get("resources_max.ngpus", "0") or 0)
            if gmax and gj[0]["gpus_per_node"] > gmax:
                warn.append("the GPU job asks for %d GPUs; %s allows %d" % (gj[0]["gpus_per_node"], target["gpu"], gmax))
            gj[0]["ncpus_per_node"] = want
            notes.append("GPU job: %d GPUs x %d cores = ncpus %d per node   <- `hpc gpu` sample `%s`" %
                         (gj[0]["gpus_per_node"], per_gpu, want, g[0]))

    # --- every planned job against the execution queue it lands in -----------------------------------------------
    for j in new["jobs"]:
        kind = "gpu" if j.get("binary") == "offload" else "serial" if j.get("queue") == "serial" else "cpu"
        q = target.get(kind)
        if not q or q not in V:
            continue
        ok, why, mn, mx, mr = V[q]
        v = qs[q]
        tot = j["nodes"] * j["ncpus_per_node"]
        if not ok:
            warn.append("job %s: queue %s is not usable (%s)" % (j["id"], q, why))
            continue
        if tot < mn or (mx is not None and tot > mx):
            warn.append("job %s needs %d cores; %s allows %s-%s per job" % (j["id"], tot, q, mn, mx))
        nmax = v.get("resources_max.nodect")
        if nmax and j["nodes"] > int(nmax):
            warn.append("job %s needs %d nodes; %s allows %s" % (j["id"], j["nodes"], q, nmax))
        if kind == "gpu":
            gmin, gmax = int(v.get("resources_min.ngpus", "0") or 0), int(v.get("resources_max.ngpus", "99") or 99)
            gtot = j["nodes"] * j.get("gpus_per_node", 0)
            if gtot < gmin or gtot > gmax:
                warn.append("job %s asks for %d GPUs; %s allows %d-%d" % (j["id"], gtot, q, gmin, gmax))
        w = hms(v.get("resources_max.walltime", ""))
        est = RP.job_estimate(plan, j)[0] * RP.model_of(plan)["safety"]
        if w and est > w:
            warn.append("job %s may need %.0f s; %s allows %d s" % (j["id"], est, q, w))
    if V and not [x for x in warn if x.startswith("job ")]:
        notes.append("every planned job fits the queue it lands in (%s)" %
                     ", ".join("%s -> %s" % (k, v) for k, v in sorted(target.items()) if v))

    # --- budget ----------------------------------------------------------------------------------------------
    hp = S.get("hpc_project", "") + "\n" + S.get("hpc_quota", "")
    m = (re.search(r"core[- ]?hours?[^\n]*?balance\s*:?\s*([\d,.]+)", hp, re.I) or
         re.search(r"balance\s*:?\s*([\d,.]+)", hp, re.I) or re.search(r"remaining\s*:?\s*([\d,.]+)", hp, re.I))
    if a.budget_cpu is not None:
        new["core_hour_budget"] = a.budget_cpu
        if a.budget_gpu is not None:
            new["gpu_hour_budget"] = a.budget_gpu
        new["budget_source"] = a.budget_source or "given on the command line"
        notes.append("core_hour_budget = %s%s   <- given on the command line (%s)" % (
            a.budget_cpu, (", gpu_hour_budget = %s" % a.budget_gpu) if a.budget_gpu is not None else "",
            new["budget_source"]))
    elif m:
        new["core_hour_budget"] = float(m.group(1).replace(",", ""))
        new["budget_source"] = "`hpc project` balance (%s)" % os.path.basename(a.discovery)
        notes.append("core_hour_budget = %s   <- `hpc project`: %s" % (new["core_hour_budget"], m.group(0).strip()[:80]))
    elif cl == "atlas":
        new["core_hour_budget"] = "unlimited"
        new["budget_source"] = "Lecture 8: Atlas is CPU only, slow, unlimited use (no allocation shown by hpc)"
        notes.append("core_hour_budget = unlimited   <- no allocation reported; Lecture 8: Atlas use is unlimited")
    elif "amgr login" in hp:
        warn.append("`hpc project` needs `amgr login` (interactive, NUS password): pass --budget-cpu/--budget-gpu "
                    "and --budget-source")
    else:
        warn.append("no core-hour balance found; pass --budget-cpu (and --budget-gpu)")

    # --- Python ------------------------------------------------------------------------------------------------
    py = re.search(r"Python (\d+)\.(\d+)", S.get("tools", ""))
    if py and (int(py.group(1)), int(py.group(2))) < (3, 5):
        warn.append("python3 is %s.%s; the checks need >= 3.5" % py.groups())
    elif py:
        notes.append("python3 %s.%s on the login node (compute nodes may differ: env.sh loads or checks one)" %
                     py.groups())

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

    def key(s):
        return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]

    def newest(prefix, pat=None):
        c = [x for x in mods if x.startswith(prefix + "/") and (pat is None or re.search(pat, x))]
        return sorted(c, key=key)[-1] if c else None

    tc = newest("foss", r"^foss/20\d\d[ab]$")
    pymod = None
    if tc:
        gcc = {"2025b": "14.3.0", "2025a": "14.2.0", "2024a": "13.3.0", "2023b": "13.2.0", "2023a": "12.3.0"}.get(
            tc.split("/")[1])
        pymod = newest("Python", r"^Python/3\.[\d.]+-GCCcore-%s$" % re.escape(gcc)) if gcc else None
    if cl == "vanda":
        want = "nvhpc-hpcx-cuda12/26.1"
        if want in mods:
            notes.append("GPU modules: %s is available (Lecture 12's recommendation)" % want)
        else:
            alt = newest("nvhpc-hpcx-cuda12") or newest("nvhpc-hpcx") or newest("nvhpc")
            if alt:
                env_new = set_default(env_new, "P3_MODULES_GPU", alt)
                notes.append("GPU modules: %s not listed; proposing %s" % (want, alt))
            else:
                warn.append("no nvhpc module listed; the GPU job cannot build")
        if tc:
            val = tc + ((" " + pymod) if pymod else "")
            env_new = set_default(env_new, "P3_MODULES_CPU", val)
            notes.append("CPU modules: P3_MODULES_CPU = %s   <- the same EasyBuild family as Atlas (foss + its Python)"
                         % val)
    else:
        tc = tc or newest("OpenMPI")
        if tc:
            val = tc + ((" " + pymod) if pymod else "")
            env_new = set_default(env_new, "P3_MODULES", val)
            notes.append("modules: P3_MODULES = %s   <- newest foss toolchain and its Python after ebenv" % val)
        else:
            notes.append("modules: no foss/OpenMPI in this discovery; env.sh picks the newest foss at job time")

    for n in notes:
        print("  " + n)
    for w in warn:
        print("  WARNING: " + w)
    old_txt = open(plan_p).read()
    new_txt = json.dumps(new, indent=1) + "\n"
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
