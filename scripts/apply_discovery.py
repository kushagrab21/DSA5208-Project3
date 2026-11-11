#!/usr/bin/env python3
"""Turns a discovery file (cluster/ops/discover.sh) into PROPOSED changes, shown as a diff. Writes nothing unless
--apply is given.

  python3 scripts/apply_discovery.py results/vanda/env/discover-<utc>.txt            print the proposal and the diff
  python3 scripts/apply_discovery.py results/vanda/env/discover-<utc>.txt --apply    write it (then commit and sync)

Proposes: the plan's "pbs" block (queues, project code, extra select resources such as mem=), core_hour_budget and
its source, and the module names in cluster/<cluster>/env.sh. Checks, without changing: cores per node against the
plan, queue limits (cores, nodes, walltime) against the plan's largest job, the GPU node shape, the Python version.
Every proposal prints the discovery lines it came from; a value it cannot find is left as it is and reported.
"""
import argparse
import difflib
import json
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
import p3common as C  # noqa: E402
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


def select_extra(sel, drop=("ncpus", "mpiprocs", "ngpus", "ompthreads")):
    """'select=1:ncpus=72:mpiprocs=72:mem=200gb' -> ':mem=200gb'"""
    parts = sel.split("=", 1)[1].split(":")[1:] if sel.startswith("select=") else []
    keep = [p for p in parts if p.split("=")[0] not in drop]
    return "".join(":" + p for p in keep)


def queue_limits(qf):
    qs, cur = {}, None
    for line in qf.splitlines():
        m = re.match(r"^Queue:\s*(\S+)", line)
        if m:
            cur = qs.setdefault(m.group(1), {})
            continue
        m = re.match(r"^\s+([\w.]+)\s=\s(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip()
    return qs


def hms(s):
    try:
        p = [int(x) for x in s.split(":")]
        return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)
    except (ValueError, AttributeError, IndexError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("discovery")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    text = open(a.discovery).read()
    S = sections(text)
    cl = "vanda" if "hpc_cpu" in S or "vanda" in a.discovery else "atlas"
    plan_p = RP.plan_path(cl)
    plan = RP.load_plan(cl)
    new = json.loads(json.dumps(plan))
    pbs = new.setdefault("pbs", {})
    notes, warn = [], []
    print("DISCOVERY PROPOSAL for %s from %s" % (cl, os.path.relpath(a.discovery, REPO)
                                               if a.discovery.startswith(REPO) else a.discovery))

    # --- queues, project, select syntax (Vanda prints sample scripts; Atlas does not) --------------------------
    dc, dg = directives(S.get("hpc_cpu", "")), directives(S.get("hpc_gpu", ""))
    qlim = queue_limits(S.get("qstat_Qf", ""))
    if dc.get("q"):
        pbs["queue_cpu"] = dc["q"][0]
        notes.append("queue_cpu = %s   <- `hpc cpu` sample: #PBS -q %s" % (dc["q"][0], dc["q"][0]))
    elif qlim:
        cand = sorted(((int(v.get("resources_max.ncpus", "0") or 0), q) for q, v in qlim.items()
                       if v.get("enabled", "True") == "True" and v.get("started", "True") == "True"
                       and not re.search(r"gpu|debug|interactive|test", q, re.I)), reverse=True)
        if cand:
            pbs["queue_cpu"] = cand[0][1]
            notes.append("queue_cpu = %s   <- qstat -Qf: the enabled CPU queue with the most cores (%d); CHECK" %
                         (cand[0][1], cand[0][0]))
    if dg.get("q"):
        pbs["queue_gpu"] = dg["q"][0]
        notes.append("queue_gpu = %s   <- `hpc gpu` sample: #PBS -q %s" % (dg["q"][0], dg["q"][0]))
    proj = (dc.get("P") or dg.get("P") or [None])[0]
    if not proj:
        m = re.search(r"Project\s*:?\s*(\S+)", S.get("hpc_project", ""))
        proj = m.group(1) if m else None
    if proj:
        pbs["project"] = proj
        notes.append("project   = %s   <- #PBS -P in the sample script / `hpc project`" % proj)
    for key, dd, gpu in (("select_extra", dc, False), ("select_extra_gpu", dg, True)):
        sel = [x for x in dd.get("l", []) if x.startswith("select=")]
        if sel:
            extra = select_extra(sel[0])
            if extra:
                pbs[key] = extra
                notes.append("%-9s = %s   <- sample `%s` asks for these per chunk" % (key, extra, sel[0]))

    # --- budget ----------------------------------------------------------------------------------------------
    hp = S.get("hpc_project", "") + "\n" + S.get("hpc_quota", "")
    m = (re.search(r"core[- ]?hours?[^\n]*?balance\s*:?\s*([\d,.]+)", hp, re.I) or
         re.search(r"balance\s*:?\s*([\d,.]+)", hp, re.I) or re.search(r"remaining\s*:?\s*([\d,.]+)", hp, re.I))
    if m:
        new["core_hour_budget"] = float(m.group(1).replace(",", ""))
        new["budget_source"] = "`hpc project` balance on %s (%s)" % (
            os.path.basename(a.discovery)[9:25], os.path.basename(a.discovery))
        notes.append("core_hour_budget = %s   <- `hpc project`: %s" % (new["core_hour_budget"],
                                                                      m.group(0).strip()[:80]))
    elif cl == "atlas":
        new["core_hour_budget"] = "unlimited"
        new["budget_source"] = "Lecture 8: Atlas is CPU only, slow, unlimited use"
        notes.append("core_hour_budget = unlimited   <- no allocation reported; Lecture 8 says Atlas use is unlimited")
    else:
        warn.append("no core-hour balance found in `hpc project`/`hpc quota`; set core_hour_budget by hand")

    # --- checks that do not write ------------------------------------------------------------------------------
    cpn_s = [int(x) for x in re.findall(r"resources_available\.ncpus = (\d+)", S.get("pbsnodes", ""))]
    cpn_sample = [int(x) for x in re.findall(r"ncpus=(\d+)", " ".join(dc.get("l", [])))]
    cpn = cpn_sample[0] if cpn_sample else (Counter(cpn_s).most_common(1)[0][0] if cpn_s else None)
    if cpn and cpn != plan["cores_per_node"]:
        warn.append("cores per CPU node %d (discovery) != %d (plan): edit scripts/make_plan.py and regenerate the "
                    "plan BEFORE freezing it" % (cpn, plan["cores_per_node"]))
    elif cpn:
        notes.append("cores per CPU node: %d, as the plan assumes" % cpn)
    q = pbs.get("queue_cpu")
    if q and q in qlim:
        L = qlim[q]
        maxc = max(j["nodes"] * j["ncpus_per_node"] for j in plan["jobs"] if j.get("binary", "cpu") == "cpu")
        maxw = max(RP.job_estimate(plan, j)[0] * RP.model_of(plan)["safety"] for j in plan["jobs"])
        lc, ln, lw = L.get("resources_max.ncpus"), L.get("resources_max.nodect"), hms(L.get("resources_max.walltime", ""))
        for what, lim, need in (("cores", lc, maxc), ("nodes", ln, max(j["nodes"] for j in plan["jobs"])),
                                ("walltime (s)", lw, maxw)):
            if lim in (None, ""):
                notes.append("queue %s: no maximum for %s reported" % (q, what))
            elif float(lim) < need:
                warn.append("queue %s allows %s %s but the plan's largest job needs %.0f" % (q, what, lim, need))
            else:
                notes.append("queue %s: max %s %s >= %.0f needed" % (q, what, lim, need))
    if dg.get("l"):
        g = [x for x in dg["l"] if x.startswith("select=")]
        if g:
            ng = re.search(r"ngpus=(\d+)", g[0])
            nc = re.search(r"ncpus=(\d+)", g[0])
            gj = [j for j in plan["jobs"] if j.get("binary") == "offload"]
            if gj and ng and nc:
                j = gj[0]
                if int(ng.group(1)) < j["gpus_per_node"]:
                    warn.append("GPU sample asks for %s GPUs per node; the plan's GPU job uses %d (its 2-GPU cells "
                                "need a node with 2 GPUs)" % (ng.group(1), j["gpus_per_node"]))
                gpu_job = next(x for x in new["jobs"] if x["id"] == j["id"])
                gpu_job["ncpus_per_node"] = int(nc.group(1))
                gpu_job["gpus_per_node"] = min(j["gpus_per_node"], int(ng.group(1))) or j["gpus_per_node"]
                notes.append("GPU job shape: ncpus=%s, ngpus=%s per node   <- `hpc gpu` sample" % (nc.group(1),
                                                                                            ng.group(1)))
    py = re.search(r"Python (\d+)\.(\d+)", S.get("tools", ""))
    if py and (int(py.group(1)), int(py.group(2))) < (3, 5):
        warn.append("python3 on the login node is %s.%s; the checks need >= 3.5 (load a Python module in env.sh)" %
                    py.groups())
    elif py:
        notes.append("python3 %s.%s on the login node (checks need >= 3.5)" % py.groups())

    # --- modules -----------------------------------------------------------------------------------------------
    mods = [l.strip() for l in S.get("module_avail", "").splitlines() if l.strip() and not l.startswith("(")]
    env_p = os.path.join(CLUSTER_DIR, cl, "env.sh")
    env_old = open(env_p).read()
    env_new = env_old

    def set_default(text, var, value):
        return re.sub(r'(: "\$\{%s:=)([^}]*)(\}")' % var, lambda m: m.group(1) + value + m.group(3), text)

    if cl == "vanda":
        want = "nvhpc-hpcx-cuda12/26.1"
        if want in mods:
            notes.append("module %s is available (Lecture 12's recommendation); env.sh keeps it" % want)
        else:
            alt = sorted(m for m in mods if "nvhpc-hpcx" in m) or sorted(m for m in mods if m.startswith("nvhpc"))
            if alt:
                env_new = set_default(env_new, "P3_MODULES_CPU", alt[-1])
                env_new = set_default(env_new, "P3_MODULES_GPU", alt[-1])
                notes.append("modules: %s not listed; proposing %s" % (want, alt[-1]))
            else:
                warn.append("no nvhpc module found; choose the MPI and compiler modules by hand")
    else:
        ompi = sorted(m for m in mods if m.lower().startswith("openmpi/"))
        cmk = sorted(m for m in mods if m.lower().startswith("cmake/"))
        if ompi:
            val = ompi[-1] + ((" " + cmk[-1]) if cmk else "")
            env_new = set_default(env_new, "P3_MODULES", val)
            notes.append("modules: P3_MODULES = %s   <- newest OpenMPI%s in `module avail`" %
                         (val, " and CMake" if cmk else ""))
        else:
            warn.append("no OpenMPI module listed; set P3_MODULES in cluster/atlas/env.sh by hand")

    for n in notes:
        print("  " + n)
    for w in warn:
        print("  WARNING: " + w)
    old_txt = open(plan_p).read()
    new_txt = json.dumps(new, indent=1) + "\n"
    diff = list(difflib.unified_diff(old_txt.splitlines(True), new_txt.splitlines(True),
                                     os.path.relpath(plan_p, REPO) if plan_p.startswith(REPO) else plan_p,
                                     "(proposed)", n=1))
    diff += list(difflib.unified_diff(env_old.splitlines(True), env_new.splitlines(True),
                                      os.path.relpath(env_p, REPO) if env_p.startswith(REPO) else env_p,
                                      "(proposed)", n=1))
    print("PROPOSED DIFF (%d lines):" % len(diff))
    sys.stdout.write("".join(diff) or "  (no change)\n")
    if plan.get("frozen") and diff:
        print("  note: the plan is frozen; these fields (pbs, budget, job shape) do not change its cells")
    if a.apply:
        with open(plan_p, "w") as f:
            f.write(new_txt)
        with open(env_p, "w") as f:
            f.write(env_new)
        print("APPLIED to %s and %s. Next: review, commit, then cluster/ops/sync.sh" % (plan_p, env_p))
    else:
        print("nothing written (re-run with --apply to write exactly this diff)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
