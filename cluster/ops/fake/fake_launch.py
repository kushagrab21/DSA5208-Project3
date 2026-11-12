#!/usr/bin/env python3
"""FAKE launcher (tests only): stands in for `p3_launch RANKS RPN THREADS bin/p3cg|bin/p3graph ARGS...` in a fake job.

Writes TEST-DOUBLE rows for the cell named by --cell into the --record file, labelled with the job's PBS_JOBID and
the sha256 of the binary on the fake cluster, with times from the plan's cost model x FAKE_SPEED. Adds the simulated
time to .fake/<PBS_JOBID>.secs (the fake walltime). If the current plan job is in FAKE_FAIL_JOBS, it exits with
143 (SIGTERM) on the first cell past the half, as a walltime kill would.
"""
import hashlib
import json
import os
import sys

wd = os.environ["PBS_O_WORKDIR"]
sys.path.insert(0, os.path.join(wd, "scripts"))
sys.path.insert(0, os.path.join(wd, "checks"))
import figures  # noqa: E402  (the synced copy on the fake cluster)
import p3common as C  # noqa: E402

args = sys.argv[4:]  # drop RANKS RPN THREADS
binary = args[0]
if "--cell" not in args:
    # not a timed cell (e.g. the graph-prep job writing the seed lists): run the real program, one process
    import subprocess
    sys.exit(subprocess.run([os.path.join(wd, binary)] + args[1:], cwd=wd).returncode)
opts = dict(zip(args[1::2], args[2::2]))
cell, record = opts["--cell"], opts["--record"]
job = os.environ.get("P3_FAKE_JOB", "")
jid = os.environ["PBS_JOBID"]
plan_name = job.split("-")[0]
with open(os.path.join(wd, "config", "run_plan.%s.json" % plan_name)) as f:
    plan = json.load(f)
cells = next(j["cells"] for j in plan["jobs"] if j["id"] == job)
os.makedirs(os.path.join(wd, ".fake"), exist_ok=True)
cnt = os.path.join(wd, ".fake", jid + ".count")
k = int(open(cnt).read()) if os.path.exists(cnt) else 0
open(cnt, "w").write(str(k + 1))
if job in os.environ.get("FAKE_FAIL_JOBS", "").split(",") and k >= len(cells) // 2:
    sys.exit(143)
h = hashlib.sha256(open(os.path.join(wd, binary), "rb").read()).hexdigest()
speed = float(os.environ.get("FAKE_SPEED") or 1)
rows = figures.fake_rows(plan, cell, jid, "2026-11-12T10:%02d:00Z" % (k % 60), h, host="FAKE-NODE", speed=speed)
cols = C.GRAPH_COLUMNS if os.path.basename(binary).startswith("p3graph") else C.RECORD_COLUMNS
for r in rows:
    C.append_csv(os.path.join(wd, record), cols, r)
secs = os.path.join(wd, ".fake", jid + ".secs")
prev = float(open(secs).read()) if os.path.exists(secs) else 0.0
open(secs, "w").write(str(prev + sum(float(r["t_total"]) for r in rows) + 5))
