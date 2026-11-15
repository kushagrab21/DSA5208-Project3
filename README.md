# DSA5208 Project 3: conjugate gradient for the Poisson equation with MPI and OpenMP

Kushagra Bhatnagar (A0351591A) and Pratyush Sinha (A0352482A)

A conjugate gradient (CG) solver for the Poisson equation in 2D and 3D, parallelised with MPI across ranks, OpenMP
threads inside each rank and OpenMP GPU offload, together with every run record from the NUS cluster Vanda and the
report built from them: [`report/DSA5208_Project3_Report.pdf`](report/DSA5208_Project3_Report.pdf). The report gives
the method and the results. This file says how to reproduce them.

## Reproduce

You need an MPI library (MPI 3), a C++17 compiler with OpenMP, Python 3 (the checks use only its standard library),
matplotlib for the figures and tectonic for the PDF. On macOS the compiler also needs Homebrew's `libomp`.

**1. Build the solver and run the validation tests.** The tests must pass, and the two deliberately broken builds must
fail them, before any timing means anything.

```bash
scripts/build.sh                     # bin/p3cg and the broken builds bin/p3cg_bug1, bin/p3cg_bug2
python3 checks/validate.py --qualify --binary bin/p3cg --bug-binary bin/p3cg_bug1 --bug-binary bin/p3cg_bug2
OMP_NUM_THREADS=2 mpirun -np 4 bin/p3cg --dim 3 --n 128 --decomp 3 --halo overlap --cg pipelined --iters 100
```

**2. Rebuild the report from the recorded runs.** This needs no cluster. Every number, table and figure is
recomputed from `results/`.

```bash
scripts/make_report.sh               # figures, generated values and tables, the PDF, then the report check
```

**3. Run the experiments on Vanda.** This needs an NUS HPC account, the NUS VPN and an SSH host alias `vanda` with a
key that works without a password. The jobs are charged to the PBS project in the `"pbs"` block of
`config/run_plan.vanda.json`, so change that entry for another account.

```bash
cluster/ops/sync.sh vanda                    # copy the committed tree to ~/p3 on Vanda
cluster/ops/submit.sh vanda vanda-validate   # build and validate on a compute node
cluster/ops/submit.sh vanda <job>            # a timed job from the plan
cluster/ops/poll.sh vanda                    # job states
cluster/ops/fetch.sh vanda                   # bring the run records back into results/vanda/
scripts/make_report.sh
```

`python3 checks/run_plan.py status --plan vanda` lists the jobs in the plan and which have been recorded.
`cluster/RUNBOOK.md` covers failed jobs.

**4. The graph experiments.** They use SNAP graphs, which are downloaded into `data/` and not tracked.

```bash
scripts/fetch_snap.sh email-Eu-core "$PWD/data"
scripts/build.sh graph               # bin/p3graph, its broken build bin/p3graph_bug1, and bin/p3convert
scripts/convert_snap.sh email-Eu-core "$PWD/data"
python3 checks/validate_graph.py --qualify --binary bin/p3graph --bug-binary bin/p3graph_bug1
```

**5. Add the runs still outstanding.** The jobs with 256 cores or more had not run when this was written, and the
report marks the values that wait for them. When they finish, run `fetch.sh` and `make_report.sh` as in step 3 and
commit `results`, `figures` and `report`. The values fill in by themselves. The orange "To write once the cluster runs
are in" boxes and the Summary are then written by hand.

## Architecture

```
  src/  C++ solver (p3cg) and graph solver (p3graph)
    |
    |  scripts/build.sh
    v
  bin/p3cg ------------------> checks/validate.py
    |                          tests V1-V5, and the broken builds must fail
    |
    |  cluster/ops/submit.sh   only jobs listed in config/run_plan.vanda.json
    v
  Vanda batch jobs (PBS)
    validation job   build on a compute node, run the tests, record the binary's hash
    timed jobs       checks/timing_gate.py: this exact binary passed validation here
                     then the runs, one CSV row each: where, what, how long, binary hash
    |
    |  cluster/ops/fetch.sh
    v
  results/vanda/*.csv
    |
    |  scripts/figures.py, scripts/report_macros.py
    v
  figures/*.pdf, report/generated/*.tex
    |
    |  scripts/make_report.sh   (tectonic, then checks/requirements_check.py)
    v
  report/DSA5208_Project3_Report.pdf
```

Inside one run, each MPI rank owns a box of the grid. Every iteration it exchanges the layer of values next to each
shared face with its neighbours (the halo exchange), applies the stencil to its box, and joins the reductions
(`MPI_Allreduce`) for the inner products. The OpenMP threads of a rank share the loops over its box. The run-time
switches `--decomp 1|2|3`, `--halo blocking|overlap` and `--cg classic|pipelined` choose how many directions the grid
is split along, whether the halo exchange overlaps the stencil, and whether CG uses two blocking reductions per
iteration or one non-blocking one. The same program therefore produces every comparison in the report.

## Where things are

| Folder | What it holds |
|---|---|
| `src/` | the C++ solver (`p3cg`), the graph solver and converter (`p3graph`, `p3convert`) |
| `checks/` | the validation tests, the timing gate, the plan tools and the report check |
| `config/` | the plan: every configuration to be timed, fixed before timing |
| `cluster/` | the batch-job environment, the scripts that submit and fetch jobs, and the runbook |
| `results/` | every run record and validation record |
| `scripts/` | build, plan generation, SNAP download and conversion, figures and report generation |
| `figures/` | the report's figures, each with a `.meta.json` file naming the records it was drawn from |
| `report/` | the report source, its generated values and tables, and the PDF |
| `process/` | our planning notes: the decision map, the assumption drills and the decision log |
| `.application/` | the build session's working notes |

## Why the results can be trusted

- **No number in the report is typed.** The source refers to each number by name (`\val{...}`), and
  `scripts/report_macros.py` computes it from the run records, so the text cannot drift from the data. To change a
  number, change the records or the script and rerun `scripts/make_report.sh`. Never edit it in the `.tex`.
- **Every timed run was decided before timing.** `config/run_plan.vanda.json` was frozen before the first timed job,
  and `submit.sh` refuses a job that is not in it. Later additions and reruns are recorded in the plan with their
  reasons, so no result was chosen after it was seen.
- **Only validated programs were timed.** A halo error does not show on one rank, so the validation tests run on the
  cluster that does the timing. A program that passes is recorded by its SHA-256 hash in
  `results/validated_binaries.csv`, and each run record carries the hash of the program that produced it. Section 11
  of the report lists each program with its validation run.

## Declaration of AI use

We used Claude Code (Anthropic, Claude Opus 5.5), in one session that planned and checked the work and one that wrote
the code and the report, to plan the work, write and test the C++ solver and its checks, run the experiments on the
NUS HPC clusters, and draft and revise this report, including a paragraph-by-paragraph language revision done by the
AI under our direction. We directed the work and are responsible for the content and quality of this submission.
