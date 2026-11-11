#!/usr/bin/env python3
"""FAKE PBS Pro for the cluster-operation tests. Never used on a real cluster.

State lives in $P3_FAKE_ROOT/<alias>/pbs/. `qsub SCRIPT` records the job and runs it at once (FAKE_QUEUE_ONLY=1 leaves
it queued; `fakepbs.py run-queued ALIAS` runs queued jobs later). A job runs the generated PBS script itself with
bash, in a clean environment that looks like a PBS job (PBS_JOBID, PBS_O_WORKDIR). Validation jobs run for real
(build + validate.py on this machine); in timed jobs the fake launcher (fake_launch.py) replaces mpirun and writes
TEST-DOUBLE rows. FAKE_FAIL_JOBS=<plan job,...> makes the launcher stop halfway, as a walltime kill would: PBS
reports Exit_status 271 and the walltime used equals the walltime requested. FAKE_FORGET=1 hides finished jobs from
`qstat -x` (history purged), so poll.sh must fall back to the job's own record.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Fake queue tables. "atlas8" mirrors the real Atlas discovery of 11 Nov 2026 in the parts that matter: a route queue,
# `parallel` (12-96 cores per job and per user, pool par12), `serial` (1 core), an ACL queue with more cores that the
# user may not use (hpc6a), an ACL queue that does list the user, and a routing-only queue.
Q = lambda **k: k  # noqa: E731
QUEUES = {
    "vanda": [Q(name="parallel", ncpus_max=576, nodect_max=8, wall="24:00:00"),
              Q(name="gpu", ncpus_max=32, nodect_max=2, wall="12:00:00")],
    "atlas8": [Q(name="normal", qtype="Route", enabled=False, started=False),
               Q(name="parallel", ncpus_min=12, ncpus_max=96, run_res="[u:PBS_GENERIC=96]", max_run="[u:PBS_GENERIC=4]",
                 pool="par12", wall="720:00:00", prio=100, mem_min="2gb"),
               Q(name="serial", ncpus_min=1, ncpus_max=1, max_run="[u:PBS_GENERIC=40]", pool="horse",
                 wall="720:00:00", prio=151, mem_min="2gb", mem_max="15gb"),
               Q(name="hpc6a", acl=["someone@*", "other.user@*", "e0123456@*", "e0234567@*", "e0345678@*",
                                    "e0456789@*", "e0567890@*"], ncpus_max=192, run_res="[u:PBS_GENERIC=192]",
                 wall="72:00:00"),
               Q(name="labq", acl=["colleague@*", "fakeuser@*"], ncpus_max=48, wall="24:00:00"),
               Q(name="routed", from_route_only=True, ncpus_max=1000, wall="24:00:00")],
}


def queues():
    return QUEUES.get(os.environ.get("P3_FAKE_ALIAS", "vanda"), QUEUES["vanda"])


def pbsdir(alias=None):
    d = os.path.join(os.environ["P3_FAKE_ROOT"], alias or os.environ["P3_FAKE_ALIAS"], "pbs", "jobs")
    os.makedirs(d, exist_ok=True)
    return d


def load(jid, alias=None):
    with open(os.path.join(pbsdir(alias), jid + ".json")) as f:
        return json.load(f)


def save(j, alias=None):
    with open(os.path.join(pbsdir(alias), j["id"] + ".json"), "w") as f:
        json.dump(j, f, indent=1)


def hms(s):
    h, m, x = (int(v) for v in s.split(":"))
    return h * 3600 + m * 60 + x


def fmt(s):
    s = int(s)
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def qsub(args):
    script = os.path.abspath(args[-1])
    text = open(script).read()
    bad = os.environ.get("FAKE_QSUB_REJECT")
    if bad and bad in text:
        print("qsub: Unknown resource: Resource_List.%s (FAKE rejection of %r)" % (bad.strip(":=").split("=")[0], bad),
              file=sys.stderr)
        return 38
    qn = (re.search(r"^#PBS -q (\S+)", text, re.M) or [None, None])[1]
    qd = next((q for q in queues() if q["name"] == qn), None)
    sel = (re.search(r"^#PBS -l select=(\S+)", text, re.M) or [None, "1:ncpus=1"])[1]
    tot = int(sel.split(":")[0]) * int(re.search(r"ncpus=(\d+)", sel).group(1))
    if qn and qd is None and os.environ.get("P3_FAKE_ALIAS", "").startswith("atlas"):
        print("qsub: Unknown queue", file=sys.stderr)
        return 170
    if qd:
        if not qd.get("enabled", True) or qd.get("qtype", "Execution") != "Execution":
            print("qsub: Queue is not enabled", file=sys.stderr)
            return 173
        if qd.get("acl") and not any(a.split("@")[0] == "fakeuser" for a in qd["acl"]):
            print("qsub: Unauthorized Request", file=sys.stderr)
            return 159
        if tot < qd.get("ncpus_min", 1) or tot > qd.get("ncpus_max", tot):
            print("qsub: Job violates queue and/or server resource limits", file=sys.stderr)
            return 188
    name = (re.search(r"^#PBS -N (\S+)", text, re.M) or [None, "job"])[1]
    select = (re.search(r"^#PBS -l (select=\S+)", text, re.M) or [None, "select=1:ncpus=1"])[1]
    wall = (re.search(r"^#PBS -l walltime=(\S+)", text, re.M) or [None, "01:00:00"])[1]
    queue = (re.search(r"^#PBS -q (\S+)", text, re.M) or [None, "workq"])[1]
    chunks = select.split("=", 1)[1]
    n = int(chunks.split(":")[0])
    ncpus = n * int(re.search(r"ncpus=(\d+)", chunks).group(1))
    root = os.path.dirname(pbsdir())
    cnt = os.path.join(root, "next")
    nxt = int(open(cnt).read()) + 1 if os.path.exists(cnt) else 1001
    open(cnt, "w").write(str(nxt))
    jid = "%d.fake-pbs" % nxt
    plan_job = os.path.splitext(os.path.basename(script))[0]
    j = {"id": jid, "name": name, "script": script, "workdir": os.getcwd(), "select": select, "nodect": n,
         "ncpus": ncpus, "walltime": wall, "queue": queue, "state": "Q", "plan_job": plan_job,
         "env": dict((k, os.environ.get(k, "")) for k in ("FAKE_SPEED", "FAKE_FAIL_JOBS", "FAKE_FORGET"))}
    save(j)
    print(jid)
    sys.stdout.flush()
    if os.environ.get("FAKE_QUEUE_ONLY") != "1":
        run(jid)
    return 0


def run(jid, alias=None):
    j = load(jid, alias)
    alias = alias or os.environ["P3_FAKE_ALIAS"]
    home = os.path.join(os.environ["P3_FAKE_ROOT"], alias, "home")
    old = (os.path.join(os.environ["P3_FAKE_ROOT"], alias, "app1/centos6.3/gnu/mvapich2-1.9/bin") + ":"
           if alias.startswith("atlas") else "")
    env = {"HOME": home, "USER": "fakeuser", "LANG": "C", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "PATH": os.path.join(HERE, "bin") + ":" + old + "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "P3_EBENV": os.path.join(os.environ["P3_FAKE_ROOT"], alias, "app1", "ebenv") if alias.startswith("atlas")
           else "",
           "PBS_JOBID": jid, "PBS_O_WORKDIR": j["workdir"], "PBS_JOBNAME": j["name"],
           "P3_FAKE_ROOT": os.environ["P3_FAKE_ROOT"], "P3_FAKE_ALIAS": alias,
           "P3_FAKE_LAUNCH": os.path.join(HERE, "fake_launch.py"), "P3_FAKE_JOB": j["plan_job"]}
    env.update(dict((k, v) for k, v in j["env"].items() if v))
    logd = os.path.join(j["workdir"], "cluster", "logs")
    os.makedirs(logd, exist_ok=True)
    j["state"] = "R"
    save(j, alias)
    t0 = time.time()
    with open(os.path.join(logd, "%s.o%s" % (j["name"], jid.split(".")[0])), "w") as log:
        rc = subprocess.run(["bash", j["script"]], cwd=j["workdir"], env=env, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    real = time.time() - t0
    simf = os.path.join(j["workdir"], ".fake", jid + ".secs")
    used = float(open(simf).read()) if os.path.exists(simf) else real
    if rc == 143:  # the fake launcher's stand-in for SIGTERM at the walltime limit
        rc, used = 271, hms(j["walltime"])
    used = min(max(used, 1), hms(j["walltime"]))
    j.update({"state": "F", "exit": rc, "walltime_used": fmt(used)})
    save(j, alias)


def run_queued(alias):
    for f in sorted(os.listdir(pbsdir(alias))):
        j = load(f[:-5], alias)
        if j["state"] == "Q":
            run(j["id"], alias)
            print("ran %s (%s)" % (j["id"], j["plan_job"]))


def qstat(args):
    if "-Q" in args or "-Qf" in args:
        full = "-Qf" in args or ("-Q" in args and "-f" in args)
        if not full:
            print("FAKE (test double)\nQueue              Max   Tot Ena Str   Que   Run   Hld")
            for q in queues():
                yn = "yes" if q.get("enabled", True) else " no"
                print("%-18s   0     0 %s %s     0     0     0" % (q["name"], yn, yn))
            return 0
        for q in queues():
            print("Queue: %s" % q["name"])
            print("    queue_type = %s" % q.get("qtype", "Execution"))
            if q.get("prio"):
                print("    Priority = %d" % q["prio"])
            if q.get("acl"):
                print("    acl_user_enable = True")
                acl = ",".join(q["acl"]) + ","
                print("    acl_users = %s" % acl[:40])
                for i in range(40, len(acl), 40):  # PBS wraps long values on tab-indented lines
                    print("\t%s" % acl[i:i + 40])
            print("    from_route_only = %s" % q.get("from_route_only", False))
            for k, f in (("ncpus_max", "resources_max.ncpus"), ("nodect_max", "resources_max.nodect"),
                         ("ncpus_min", "resources_min.ncpus"), ("mem_min", "resources_min.mem"),
                         ("mem_max", "resources_max.mem"), ("wall", "resources_max.walltime"),
                         ("pool", "default_chunk.node_pool"), ("run_res", "max_run_res.ncpus"),
                         ("max_run", "max_run")):
                if q.get(k) is not None:
                    print("    %s = %s" % (f, q[k]))
            print("    enabled = %s" % q.get("enabled", True))
            print("    started = %s" % q.get("started", True))
            print("    comment = FAKE (test double)\n")
        return 0
    ids = [a for a in args if not a.startswith("-")]
    hist = "-x" in args or "-H" in args
    full = "-f" in args or "-xf" in args
    rc = 0
    if not ids:
        print("FAKE (test double)\nJob id            Name             User      Time Use S Queue")
        for f in sorted(os.listdir(pbsdir())):
            j = load(f[:-5])
            if j["state"] != "F" or hist:
                print("%-17s %-16s fakeuser  %8s %s %s" % (j["id"], j["name"][:16], j.get("walltime_used", "0"),
                                                         j["state"], j["queue"]))
        return 0
    for jid in ids:
        try:
            j = load(jid)
        except OSError:
            print("qstat: Unknown Job Id %s" % jid, file=sys.stderr)
            rc = 153
            continue
        if j["state"] == "F" and not hist:
            print("qstat: %s Job has finished, use -x or -H to obtain historical job information" % jid,
                  file=sys.stderr)
            rc = 35
            continue
        if j["state"] == "F" and j.get("env", {}).get("FAKE_FORGET") == "1":
            print("qstat: Unknown Job Id %s" % jid, file=sys.stderr)
            rc = 153
            continue
        if full:
            print("Job Id: %s" % j["id"])
            print("    Job_Name = %s" % j["name"])
            print("    Job_Owner = fakeuser@fake-login")
            print("    job_state = %s" % j["state"])
            print("    queue = %s" % j["queue"])
            print("    Resource_List.ncpus = %d" % j["ncpus"])
            print("    Resource_List.nodect = %d" % j["nodect"])
            print("    Resource_List.select = %s" % j["select"].split("=", 1)[1])
            print("    Resource_List.walltime = %s" % j["walltime"])
            if j["state"] in ("R", "F"):
                print("    resources_used.walltime = %s" % j.get("walltime_used", "00:00:01"))
                print("    resources_used.ncpus = %d" % j["ncpus"])
            if j["state"] == "F":
                print("    Exit_status = %d" % j["exit"])
            print("    comment = FAKE (test double)")
            print("")
    return rc


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "qsub":
        return qsub(args)
    if cmd == "qstat":
        return qstat(args)
    if cmd == "run-queued":
        return run_queued(args[0])
    raise SystemExit("unknown command " + cmd)


if __name__ == "__main__":
    sys.exit(main())
