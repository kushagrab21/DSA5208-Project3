# DSA5208 Project 3: conjugate gradient for the Poisson equation with MPI and OpenMP

Kushagra Bhatnagar (A0351591A) and Pratyush Sinha (A0352482A)

A conjugate gradient (CG) solver for the Poisson equation in 2D and 3D, parallelised with MPI across ranks, OpenMP
threads inside each rank and OpenMP GPU offload, together with every run record from the NUS cluster Vanda and the
report built from them: [`report/DSA5208_Project3_Report.pdf`](report/DSA5208_Project3_Report.pdf). The report gives
the method and the results. This file says how to reproduce them, and
[the project in questions and answers](#the-project-in-questions-and-answers) summarises what we found.

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

**5. What was not run.** 19 com-Orkut graph configurations at 288 cores did not finish within their job's time limit.
The plan still lists them, as `vanda-graph-4node-rerun`, but they were not resubmitted, so the report compares
com-Orkut at its largest complete core count. Every Poisson configuration in the plan was run.

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

## The project in questions and answers

All numbers below come from the report, measured on Vanda with up to 288 cores (4 nodes of 72 cores). The report gives
every table and the full reasoning.

**What does the program solve?**

The Poisson equation -Δu = f on the unit square (2D, 5-point stencil) and the unit cube (3D, 7-point stencil), with the
conjugate gradient (CG) method. A known exact solution sets f, so every run can measure its own error.

As real data, the same CG code also labels communities in six SNAP networks, starting from a few labelled vertices.

**Why is it not embarrassingly parallel?**

Every CG iteration needs two things from other processes:
- the neighbours' boundary values, exchanged in a halo exchange;
- two global inner products, combined in reductions (`MPI_Allreduce`).

So every rank depends on other ranks in every iteration.

**How is it parallelised?**

Across MPI ranks: each rank owns one box of the grid, split along 1, 2 or 3 directions (domain decomposition).

Inside a rank: OpenMP threads share the loops over the box.

On a GPU: the same loops run through OpenMP GPU offload, with one rank per GPU.

Matrix-free: the matrix is never stored, because the stencil already defines it and storing it would only add memory
traffic.

**How do we know it is correct?**

Error: halving the grid spacing divides the error by four, as the discretisation predicts.

Parallel against serial: every parallel layout reproduces the one-rank result to rounding.

The tests can fail: they reject two deliberately broken halo exchanges, so they catch real bugs.

**How does the serial time grow with problem size?**

Measured: the time per iteration grows in proportion to the number of unknowns, with a fitted slope of 0.98 in 2D and
3D against a predicted 1.

Inference: a 3D iteration costs only 1.18 times a 2D one per unknown, although it has 1.4 times the nonzeros. So the
time follows the bytes read from memory, not the arithmetic, and CG is memory-bound.

**What happens when we add cores to a fixed problem (strong scaling)?**

Problem: 67 million unknowns. One core takes 28.4 s in 3D for 100 iterations.

One node (72 cores): 19.0 times as fast, against an ideal 72, so the efficiency is 0.26.

Four nodes (288 cores): 75.3 times as fast in 3D and 72.0 times in 2D, so the efficiency stays at 0.26 and 0.25.

Why the first node loses most: one socket's memory bandwidth saturates after about 18 cores, so more cores on that
socket barely help.

Why it does not drop further across nodes: two effects cancel. Communication grows to 27 % of the 3D time on four
nodes. But the computation falls faster than the cores grow, probably because each rank's vectors start to fit in its
share of the cache. We did not measure the cause directly, and hardware memory counters would settle it.

**What happens when the problem grows with the cores (weak scaling)?**

The time rises while ranks share one socket's bandwidth, stays flat when the second socket is added, and grows only a
little across nodes.

The one-rank run is anomalously fast, so we measure efficiency from two ranks, as T(2)/T(P). On 288 cores it is 0.25 in
both 2D and 3D.

**How much does communication cost?**

3D, classic CG, share of the time:
- one node: halo exchange 4.5 %, reductions 5.3 %;
- four nodes: halo exchange 12.4 %, reductions 15.0 %.

2D on four nodes: the reductions dominate, at 17.0 % against 2.9 % for the halo exchange.

**Which choices win?**

Classic against pipelined CG: classic is faster in every strong-scaling run, by about 1.4 times. Pipelined CG moves a
third more bytes per unknown, and in a memory-bound code that costs more than the reduction time it hides. The only
exceptions are the 2D weak-scaling runs with 2 and 4 ranks.

Decomposition: it matters only in 3D. Slabs are the slowest there, because each one exchanges two whole planes.

MPI and OpenMP: on one node, 8 ranks × 9 threads is fastest in 3D and 4 × 18 in 2D. On four nodes, pure MPI (72 × 1)
wins in 3D and 2 × 36 in 2D.

**What about the GPU?**

One NVIDIA A40 is 1.16 times as fast as the fastest full CPU node in 3D, and 1.12 times in 2D. That is close to the
ratio of their specified memory bandwidths, 1.13, as expected for a memory-bound code.

Two GPUs are 1.97 times as fast as one in 2D but only 1.77 times in 3D, because the 3D halos travel through the host.

**What do the real networks show?**

Accuracy: with 5 labelled vertices per community, com-Amazon, com-LiveJournal, com-Youtube and com-Orkut are labelled
2.8 to 6.8 times as accurately as guessing the most common community.

Sparsity: keeping each edge with probability 1/8 drops the accuracy on the sparse com-Amazon from 1.000 to 0.072, but
on the dense com-Orkut only from 0.835 to 0.725. Our records do not separate vertices cut off from the seeds from
vertices that only lie beyond the few CG iterations a thinned graph needs.

Cost: the iterations per system grow roughly with the square root of the largest degree, from 113 on com-Amazon to
1,024 on com-Orkut.

Scaling: unlike the grid, the graphs gain little across nodes. On four nodes com-LiveJournal is no faster than on one,
because hubs connect almost every rank to every other, so the exchange is nearly all-to-all.

**What is the main conclusion?**

For the grid on up to 288 cores, memory bandwidth inside a node sets the limit. Use classic CG, columns or blocks in
3D, and the blocking halo exchange.

The reductions' share grows with every node. The cost model says they, not memory traffic, would set the limit at larger
core counts, which is where pipelined CG could pay off.

For the graphs, communication across nodes dominates because the exchange is irregular. So the partition, fewer ranks
with more threads, and the exchange pattern matter more than the CG variant.

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
