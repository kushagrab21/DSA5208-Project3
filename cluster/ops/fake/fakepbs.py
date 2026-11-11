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
    env = {"HOME": home, "USER": "fakeuser", "LANG": "C", "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "PATH": os.path.join(HERE, "bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
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
            print("FAKE (test double)\nQueue              Max   Tot Ena Str   Que   Run   Hld\n"
                  "parallel             0     2 yes yes     1     1     0\ngpu                  0     0 yes yes     0     0     0")
            return 0
        for q, ncpus, wall, nodes in (("parallel", 576, "24:00:00", 8), ("gpu", 32, "12:00:00", 2)):
            print("Queue: %s\n    queue_type = Execution\n    resources_max.ncpus = %d\n    resources_max.nodect = %d\n"
                  "    resources_max.walltime = %s\n    resources_default.walltime = 01:00:00\n    enabled = True\n"
                  "    started = True\n    comment = FAKE (test double)\n" % (q, ncpus, nodes, wall))
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
