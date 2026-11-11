# Cluster runbook: submitting, watching and recovering the Project 3 runs on Vanda and Atlas

This is the procedure the coordinating session runs (Lecture 13, Demo 2, step 2). It is written to become a skill:
the "Generic" parts are independent of this project; the "Project" parts name what Project 3 plugs in.

## What the scripts guarantee

| Script | Does | Refuses |
|---|---|---|
| `cluster/ops/discover.sh <alias>` | read-only probes of the login node → `results/<cluster>/env/discover-<utc>.txt` | nothing; prints the VPN/key hint if the cluster cannot be reached |
| `scripts/apply_discovery.py <file> [--apply]` | proposes the plan's `pbs` block, `core_hour_budget`, module names in `env.sh`; checks cores per node, queue limits, GPU node shape, Python | writes nothing without `--apply`; prints the evidence line for every value |
| `cluster/ops/sync.sh <alias>` | copies the committed tree to `~/p3`, writes the commit and plan hash there (`SYNCED`) and in `results/<cluster>/sync.csv` | a dirty working tree |
| `cluster/ops/submit.sh <alias> <job>` | the only route to `qsub`: generates the PBS script from the plan, submits it, records the PBS id in `results/<cluster>/jobs.csv`, prints the budget left | a job not in the plan; a cluster without the local commit and plan; a second submission without a recorded rerun reason; any timed job before a binary is qualified **on that cluster**; timed jobs while the plan is not frozen (except `<cluster>-calibrate`); a worst case above the budget |
| `cluster/ops/poll.sh <alias>` | state of every job in flight; for finished jobs exit status, walltime and core-hours used, rows recorded | — (exit 2 and flags: nonzero exit, walltime exceeded, missing records, no qualified binary) |
| `cluster/ops/fetch.sh <alias>` | brings back records, job events, machine files, validation output, PBS logs; merges without rewriting; checks rows; prints plan status; recalibrates the cost model | rows that fail `run_record.py` are reported, not imported into figures |

Transport is `ssh`/`rsync` through the aliases in `~/.ssh/config` (`atlas8`, `vanda`). `P3_SSH`, `P3_RSYNC`,
`P3_RESULTS`, `P3_CONFIG`, `P3_GENERATED`, `P3_LOGS` replace them; `cluster/ops/test_fake_cluster.sh` uses that to run
the whole procedure against a fake cluster.

The NUS VPN is needed for every script call, not while jobs run. A dropped VPN makes a script stop with the hint
"connect the NUS VPN ..."; reconnect and run `poll.sh`, then `fetch.sh`.

## First session, in order

Prerequisite: the key works without a password, on the VPN:

```bash
ssh -o BatchMode=yes vanda true && ssh -o BatchMode=yes atlas8 true && echo ok
git -C ~/Desktop/final_assignment/build status --short        # must be empty
```

1. **Discover both clusters** (read-only):
   ```bash
   cluster/ops/discover.sh vanda
   cluster/ops/discover.sh atlas8
   ```
2. **Review and apply the proposals.** Read the diff first; `--apply` writes exactly that diff:
   ```bash
   python3 scripts/apply_discovery.py results/vanda/env/discover-<utc>.txt
   python3 scripts/apply_discovery.py results/vanda/env/discover-<utc>.txt --apply
   python3 scripts/apply_discovery.py results/atlas/env/discover-<utc>.txt --apply
   ```
   If it warns that cores per node differ from the plan (Atlas's 24 is unverified), change `scripts/make_plan.py`
   and regenerate (`python3 scripts/make_plan.py atlas`) now, before anything is frozen. If a queue's limits are
   below the plan's largest job, choose another queue or stop and report (the D5 decision is the user's).
   ```bash
   python3 checks/run_plan.py check --plan vanda && python3 checks/run_plan.py check --plan atlas
   git commit -am "Plans and cluster env from discovery on <date>"
   ```
3. **Sync** the committed tree: `cluster/ops/sync.sh vanda` and `cluster/ops/sync.sh atlas8`.
4. **Validate on each cluster** (builds on a compute node, qualifies `validate.py` there; Atlas use is free, so its
   validation is insurance for the fallback):
   ```bash
   cluster/ops/submit.sh vanda vanda-validate
   cluster/ops/submit.sh atlas8 atlas-validate
   cluster/ops/poll.sh vanda        # every few minutes until finished; exit 2 means a flag to read
   cluster/ops/fetch.sh vanda       # brings back the qualified binary entry
   ```
   Read the job log in `cluster/logs/vanda/` once: the build lines, and that `validate.py` printed QUALIFIED.
5. **Calibrate** (the only timed job allowed before the freeze; four graded cells):
   ```bash
   cluster/ops/submit.sh vanda vanda-calibrate
   cluster/ops/poll.sh vanda; cluster/ops/fetch.sh vanda     # prints the measured bandwidths and new estimates
   ```
   Check the first job's `--report-bindings` lines in its log: each rank on its own cores.
6. **Freeze the plan**: set `"frozen": true` in `config/run_plan.vanda.json`, commit, `cluster/ops/sync.sh vanda`.
7. **Submit the rest, the riskiest graded cells first.** The 288-core cells need four free nodes and are the ones
   a late Vanda outage would cost most; the GPU run is required (E7) and uses another queue:
   ```bash
   cluster/ops/submit.sh vanda vanda-4node                    # strong/weak at 288 cores, variants, layouts x4 nodes
   cluster/ops/submit.sh vanda vanda-gpu                      # E7
   cluster/ops/submit.sh vanda vanda-1node-scaling            # strong/weak 1..72 cores incl. 1-core baselines
   cluster/ops/submit.sh vanda vanda-serial                   # E2 sizes
   cluster/ops/submit.sh vanda vanda-2node                    # 144 cores
   cluster/ops/submit.sh vanda vanda-1node-variants-layouts   # 72-core variants and layouts
   ```
   Each prints the worst-case budget left; submit refuses before the budget would be overrun.
8. **Watch and collect**: `poll.sh` every 10–20 minutes while jobs run; `fetch.sh` after each finishes;
   `python3 checks/run_plan.py status --plan vanda` shows cells filled and core-hours used. When every graded cell is
   filled, `scripts/make_report.sh`.

## Atlas (fallback and early start)

What the first real discovery (11 Nov, 18:33 UTC) established, and what the plan does about it:

- **Queues.** This user can use `parallel` (12–96 cores per job, 96 cores per user at once, at most 4 running jobs,
  pool `par12`) and `serial` (1 core, 2–15 GB, 40 running). `hpc6a` (192 cores) is restricted to named users;
  `normal` is a disabled routing queue.
  - Atlas can never reach 256 cores, so the ≥256-core strong and weak cells exist only in the Vanda plan.
  - `run_plan.py check --plan atlas` prints "PASS AS A FALLBACK PLAN" and lists what is NOT MET.
- **Nodes.** The compute nodes listed are 96-core (`cnode-33-*`, about 358 GB). The new `discover.sh` prints
  `node_pool`, so the next discovery confirms which nodes form `par12`.
- **Jobs.** Each parallel job is one whole 96-core node. Because of the per-user cap, only one runs at a time.
  - The 1-core baselines of every speedup run inside those jobs, on the same node type and binary.
  - The serial sweep runs in `serial`, one core of a shared node; the report says so.
- **Modules.** `source /app1/ebenv` must come first (Lecture 8). Without it, `PATH` has the 2013 `mvapich2-1.9`
  `mpicxx`. `cluster/atlas/env.sh` sources it, loads the newest `foss` toolchain (or the module `apply_discovery.py`
  wrote), prints what it loaded into the job log, and stops if the old `mpicxx` is still first.
- **CMake.** CentOS 7's `/usr/bin/cmake` is older than 3.16, so `scripts/build.sh` compiles with `mpicxx` directly
  unless a newer CMake is loaded.
- **Queue load.** `gstat` showed the parallel queue busy (887 waiting). Submit early; poll every 20–30 minutes.

**Tonight's sequence (from a working key to the calibration job):**
```bash
cd ~/Desktop/final_assignment/build && git status --short            # must print nothing
ssh -o BatchMode=yes atlas8 true && echo key-ok
cluster/ops/discover.sh atlas8                                        # sources ebenv; full module list; user; node pools
python3 scripts/apply_discovery.py results/atlas/env/discover-<utc>.txt          # READ: queues, pool, modules, warnings
python3 scripts/apply_discovery.py results/atlas/env/discover-<utc>.txt --apply  # writes exactly that diff
python3 checks/run_plan.py check --plan atlas                         # PASS AS A FALLBACK PLAN + the NOT MET list
git add config/run_plan.atlas.json cluster/atlas/env.sh && git commit -m "Atlas queues, memory and modules from discovery"
cluster/ops/sync.sh atlas8
cluster/ops/submit.sh atlas8 atlas-validate
cluster/ops/poll.sh atlas8          # repeat until finished; then read cluster/logs/atlas/ after fetch:
cluster/ops/fetch.sh atlas8         #   "p3 env (atlas): loaded foss/..." and validate.py's QUALIFICATION line
cluster/ops/submit.sh atlas8 atlas-calibrate
cluster/ops/poll.sh atlas8; cluster/ops/fetch.sh atlas8              # prints the measured bandwidths
```

If `apply_discovery.py` warns that the `par12` nodes are not 96-core, fix the plan before going on: change `cpn`/`top`
and the limits in `build_atlas_plan()` in `scripts/make_plan.py`, run `python3 scripts/make_plan.py atlas`, run the
check, then commit. Then freeze `config/run_plan.atlas.json`, commit, `sync.sh atlas8`, and submit `atlas-serial`
(serial queue, runs alongside), `atlas-1node-scaling`, `atlas-variants-layouts`.

`cluster/ops/test_fake_atlas.sh` rehearses exactly this sequence on a fake Atlas.

## Failures

**Job killed at the walltime.** poll shows `FAILED (exit 271)` (or `-29`), `walltime exceeded`, `missing records k/n`.
`fetch.sh` keeps the rows it did write; finished cells count. The walltimes of later jobs come from the recalibrated
model already. Rerun only what is missing:
```bash
python3 cluster/ops/opslib.py missing-cells --cluster vanda --job vanda-4node   # prints an "unplanned" entry
# paste it into config/run_plan.vanda.json "unplanned", write the reason, commit, sync.sh, then:
cluster/ops/submit.sh vanda vanda-4node-rest
```
(A full rerun instead needs `{"job": "vanda-4node", "reason": "..."}` in `"reruns"`; the cells filled twice are then
reported as reruns with that reason.)

**A module is missing or renamed.** The validation job fails at the build; its log in `cluster/logs/<cluster>/`
shows `module: ... not found` or a missing `mpicxx`/`cmake`. Run `discover.sh` again, set `P3_MODULES_CPU/GPU`
(Vanda) or `P3_MODULES` (Atlas) in `cluster/<cluster>/env.sh`, commit, sync, add a rerun reason for the validation
job, resubmit it.

**The queue rejects the select syntax.** `submit.sh` prints qsub's message and records nothing. Compare the header of
`cluster/generated/<cluster>/<job>.pbs` with the `hpc cpu` / `hpc gpu` sample in the discovery file; fix the plan's
`pbs` block (`queue_cpu`, `project`, `select_extra`, `place`), commit, sync, submit again (no rerun reason is
needed: nothing was submitted).

**Vanda is down.** Scripts stop with an ssh error, or poll later shows jobs killed. Jobs queued before an outage may
or may not survive; poll tells which. The CPU sections move to Atlas as a whole (figures never mix clusters; the
report uses the cluster with the most graded cells filled): `atlas-validate` should already be done (step 4), then
freeze `config/run_plan.atlas.json`, commit, sync, and submit the Atlas jobs (see "Atlas" above). Atlas reaches only
96 cores: the report then says that the 256-core requirement is not met, and `requirements_check.py` shows E3/E4 as NOT
MET instead of filled.
The GPU run (E7) exists only on Vanda: if Vanda stays down too long for it, that is the user's decision (wait for an
extension or write to the instructor; circuit D5).

**VPN dropped mid-session.** Nothing is lost: the jobs run on the cluster. Reconnect; if ssh hangs on a stale shared
connection, `ssh -O exit vanda`; then `poll.sh`, `fetch.sh`.

**Finished with exit 0 but records are missing.** Read the job log: the usual causes are the timing gate refusing a
binary that changed after validation (validate again), or `python3` missing on compute nodes (load a Python module
in `env.sh`).

**Budget refusal.** submit refuses when the worst case (walltime × cores) would overrun the remaining core-hours.
Trimming the plan is the user's decision; do not lower walltimes by hand.

## Making it a skill

Generic: discover → proposal diff → commit → sync by commit → a plan-gated submit with a ledger → poll with
failure flags → fetch with merge, record check and recalibration → failure playbook; transport behind environment
variables, and a fake cluster that exercises the same scripts. Project-specific inputs: the plan file and its job
kinds (validate, calibration, timed), the validation job, the run-record schema, the aliases and modules.
