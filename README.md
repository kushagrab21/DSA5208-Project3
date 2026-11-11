# DSA5208 Project 3: conjugate gradient for the Poisson equation with MPI + OpenMP

Kushagra Bhatnagar (A0351591A) · Pratyush Sinha (A0352482A)

`p3cg` solves −Δu = f on the unit square (2D) and the unit cube (3D) with zero boundary values. It uses the
second-order 5-point (2D) or 7-point (3D) finite-difference stencil and the conjugate gradient (CG) method. The
matrix is never stored: each CG iteration applies the stencil directly ("matrix-free").

It is parallelised with MPI across processes ("ranks") and OpenMP threads inside each rank. The same loops can also
be offloaded to a GPU with OpenMP `target` (a separate build). The parallel methods are switchable at run time so one
binary produces every comparison:

| Choice | Options | Flag |
|---|---|---|
| Domain decomposition | split the grid along 1, 2 or 3 directions (`MPI_Dims_create` + `MPI_Cart_create`) | `--decomp 1\|2\|3` |
| Halo exchange | `blocking`: `MPI_Sendrecv` per direction, then the stencil. `overlap`: `MPI_Isend`/`MPI_Irecv`, stencil on interior points while messages travel, `MPI_Waitall`, then the boundary shell | `--halo blocking\|overlap` |
| CG variant | `classic`: two blocking `MPI_Allreduce` per iteration. `pipelined` (Ghysels and Vanroose, 2014): one `MPI_Iallreduce` per iteration, overlapped with the halo exchange and stencil | `--cg classic\|pipelined` |
| Threads per rank | OpenMP | `OMP_NUM_THREADS` |

Every run times its halo exchanges, global reductions and local computation separately with `MPI_Wtime`. Each
timed run appends one CSV row (the "run record") that says where and how it ran.

## Test problem (synthetic data)

The exact solution is u(x) = ∏ᵢ xᵢ(1 − xᵢ)e^{xᵢ}, so f = Σᵢ xᵢ(xᵢ + 3)e^{xᵢ} ∏_{j≠i} xⱼ(1 − xⱼ)e^{xⱼ}. The right-hand
side is computed from this formula at every grid point, and the error against the exact solution is reported. There
are n interior points per direction, with spacing h = 1/(n+1): N = n^d unknowns and n^d + 2d(n−1)n^{d−1} nonzeros
in the matrix the stencil represents.

`--problem sine` (u = ∏ sin(πxᵢ)) is kept only to show why it was not used. That u is an eigenvector of the
discrete operator, so CG solves it in one iteration. This makes it useless both as a convergence test and as a
timing workload.

## Fixed iteration count for timing, tolerance for validation

- **Timing runs** use a fixed number of iterations (`--iters 100`). Runs of different sizes and layouts then do the
  same work per unknown, and cluster time stays bounded. CG needs O(n) iterations to reach a fixed tolerance, so
  timing to a tolerance would mix the cost per iteration with the growth in iteration count.
- **Each timed run is repeated 3 times** in one process (`--repeats 3`). Report the median.
- **Validation runs** iterate to a tolerance (`--tol`).
- The plan has one extra serial sweep to a tolerance (`serial-tol`). It shows the growth in iteration count separately.

## Build

Requirements: an MPI library with MPI-3, a C++17 compiler with OpenMP, and optionally CMake ≥ 3.16. The checks need
Python ≥ 3.5 and only the standard library. The development plot needs matplotlib.

```bash
scripts/build.sh            # bin/p3cg (correct) and bin/p3cg_bug1, bin/p3cg_bug2 (planted halo bugs, for validation)
scripts/build.sh offload    # bin/p3cg_offload* (OpenMP target offload; nvhpc on a Vanda GPU node)
```

`build.sh` uses CMake if it is installed. Otherwise it compiles with one `mpicxx` line per binary; set
`P3_NO_CMAKE=1` to force that path.

- **macOS (Apple clang)** needs Homebrew `libomp`; CMake finds it automatically. Run with
  `mpirun --oversubscribe` beyond the core count.
- **Linux** uses `P3_OMP_FLAGS` (default `-fopenmp`; nvhpc uses `-mp`).
- **Offload** uses `P3_OFFLOAD_FLAGS` (default `-mp=gpu`).

CMake options are `P3_OPENMP` (ON), `P3_OFFLOAD` (OFF), `P3_NATIVE` (OFF) and `PLANT_HALO_BUG` (0, 1 or 2).

## Run

```bash
OMP_NUM_THREADS=2 mpirun -np 4 bin/p3cg --dim 3 --n 128 --decomp 3 --halo overlap --cg pipelined --iters 100 --repeats 3
mpirun -np 1 bin/p3cg --dim 2 --n 127 --tol 1e-12      # to a tolerance; prints iterations, residuals and error
bin/p3cg --help
```

Each run prints one `RUN ...` line per repeat and appends a row to `results/<cluster>/<job>.csv`. Pass
`--record PATH` to choose the file, or `--no-record` to skip it.

| Record columns | Meaning |
|---|---|
| `cluster` | `atlas` or `vanda` only inside a PBS job (`PBS_JOBID` set) whose `P3_CLUSTER` names that cluster; otherwise `local` |
| `pbs_jobid`, `host`, `nodes`, `ranks`, `threads`, `gpus` | where it ran (nodes and GPUs counted by the program itself) |
| `dim`, `n`, `unknowns`, `nonzeros`, `decomp`, `pdims`, `local_max`, `local_min` | the problem and how it was split |
| `cg`, `halo`, `mode`, `iters`, `repeat` | the method |
| `t_total` | wall time of the solve, slowest rank |
| `t_halo`, `t_reduce`, `t_compute` | mean over ranks (the `_max` columns give the slowest rank) |
| `t_other` | `t_total` minus the three means: timer gaps plus the spread between the slowest and the average rank |
| `msgs_per_exch`, `doubles_per_exch_max`, `allreduces`, `exchanges` | communication counts, for the runtime model |
| `rel_res`, `true_rel_res`, `err_max`, `err_l2`, `converged`, `breakdown` | accuracy |
| `binary_sha256`, `git_sha`, `build` | the exact binary (its own SHA-256) and how it was built |

## Checks

Each check prints a verdict and refuses the next step when it fails.

| Check | What it does |
|---|---|
| `checks/validate.py` | Five named cases (below). `--qualify` must pass the correct build **and** refuse both planted-bug builds; only then is the binary's SHA-256 written to `results/validated_binaries.csv`. The output is kept in `results/validation/<cluster>/`. |
| `checks/timing_gate.py --binary bin/p3cg` | Refuses timing with a binary that `validate.py` has not qualified on this cluster. |
| `checks/run_record.py [--for-figures]` | Checks every record row. With `--for-figures` it refuses any row that is not from Atlas or Vanda, has no PBS job id, or comes from an unqualified binary. Figure scripts load data only through `figure_rows()`. `--selftest` qualifies the check on fixtures. |
| `checks/run_plan.py` | `status`: graded cells filled/total, reruns, rows outside the plan, core-hours against the budget. `check`: the plan covers every graded requirement. `pbs`: writes a job script. `run`: runs a local-plan job. `selftest`: shows `check` refuses a plan without the ≥256-core weak cells. |
| `checks/requirements_check.py` | Stub for the report stage; refuses until the report maps E1–E18. |

### The validation cases (`checks/validate.py`)

| Case | Purpose | Pass rule and reason |
|---|---|---|
| V1 order-2d | the 2D serial solver converges, and its error against the exact solution falls as h² | observed order in [1.9, 2.1] for h = 1/32 → 1/64 → 1/128, solved to 1e-12 |
| V2 order-3d | the same in 3D | h = 1/16 → 1/32 → 1/64 |
| V3 agree-2d | 2D parallel runs equal the serial run to rounding | after 25 iterations, relative 2-norm difference ≤ 1e-10 for 1D and 2D splits, uneven blocks, both halo variants, 2 ranks × 2 threads. Only the order of the dot-product partial sums differs; the observed difference is ≤ 3e-14. |
| V4 agree-3d | the same in 3D | 1D, 2D and 3D splits up to 8 ranks; observed ≤ 5e-13 |
| V5 pipelined | pipelined CG reaches the same converged answer as classic CG (1 and 4 ranks, 2D and 3D) | ‖x_p − x_s‖/‖x_s‖ ≤ cond(A)(ρ_p + ρ_s)/(1 − cond(A)ρ_s), where ρ is the true relative residual and cond(A) = cot²(πh/2). The two methods use different recurrences, so only converged answers can be compared. |

The planted bugs (`-DPLANT_HALO_BUG=1` drops one received halo face; `=2` sends the wrong plane on one face) change
the parallel answer by about 0.5 relative. V3, V4 and V5 refuse them. V1 and V2 still pass, because a 1-rank run
has no halo between ranks; that is why the parallel cases exist.

Pipelined CG is less stable than classic CG. At tolerance 1e-14 its recursive residual stalls near 1e-12 while the
true residual b − Ax stays near 1e-9. Classic CG reaches 1e-14 (true residual 5e-13).

## Cluster runs (Atlas / Vanda)

The plans are generated by `scripts/make_plan.py`:

- `config/run_plan.vanda.json` is the primary plan: 72-core nodes, up to 288 cores, and the GPU job.
- `config/run_plan.atlas.json` is the fallback if Vanda is down. It assumes 24 cores per node, which is unverified.
- `config/run_plan.local.json` is development only.

Each plan writes out its size arithmetic under `"arithmetic"`.

1. **First login.** Fill in the plan's `pbs` block (queue and project, from `hpc cpu`, `hpc gpu`, `qstat -Qf`) and
   `core_hour_budget`. Check the module names in `cluster/<cluster>/env.sh` (`module avail`), and that `python3`
   exists on compute nodes.
2. **Copy the repository** to the cluster and run `python3 checks/run_plan.py check --plan vanda`.
3. **Generate and submit the validation job:**
   `python3 checks/run_plan.py pbs --plan vanda --job vanda-validate`, then
   `qsub cluster/generated/vanda/vanda-validate.pbs`. It builds on a compute node (Vanda's login nodes are VMs) and
   qualifies the binary.
4. **Freeze the plan** (`"frozen": true`), then generate and submit the timing jobs. Each job script refuses to
   start if its job is not in the plan or its binary is not qualified. The GPU job builds the offload binary and
   validates it on the GPU node itself.
5. **Track progress** with `python3 checks/run_plan.py status --plan vanda`. A rerun or an extra job needs an entry
   with a reason in the plan's `reruns` / `unplanned` lists.

The first launch of each job prints the process bindings (`--report-bindings`). Check them in the first job's log;
`p3_launch` in `env.sh` is written for Open MPI / HPC-X.

## The report

```bash
scripts/make_report.sh        # figures -> generated numbers/tables -> PDF (Tectonic) -> requirements check
```

- `scripts/figures.py` draws each figure from Atlas/Vanda run records only (through `checks/run_record.py`). It refuses
  if a local row is among them. It draws a figure only when every planned run behind it is recorded, and writes
  `figures/<name>.meta.json` with the axis scales, source CSVs, their SHA-256 and the binaries.
- `scripts/report_macros.py` writes `report/generated/`: `values.tex` (every number in the text), `tab_*.tex`,
  `slots.tex` and `status.json`. A number or table whose runs are missing renders as a red "waiting for cluster data"
  mark, so the PDF can be built at any time.
- `checks/requirements_check.py` maps E1–E18 to report sections and prints which rows are still waiting, and for
  what. It refuses release when:
  - a hand-typed number appears in the body;
  - a filled figure has a linear time, size or core axis, or a changed source;
  - a log file is in the package;
  - an author, or the AI-use section, is missing;
  - the PDF is stale.

  Its `--selftest` shows the refusals on broken copies. The pass example will be the first full render the user
  accepts.
- `scripts/testdouble_render.sh` renders the whole report from **fabricated** cluster rows in `/tmp` (stamped TEST
  DOUBLE). It shows that real rows fill every slot without hand editing; nothing it makes enters `results/`,
  `figures/` or `report/`.
- The orange "to write once the cluster runs are in" boxes are the interpretation paragraphs. They are written by
  hand once the numbers exist; everything else fills automatically.

## Operating the clusters

`cluster/RUNBOOK.md` is the procedure: `cluster/ops/discover.sh`, `scripts/apply_discovery.py`, `cluster/ops/sync.sh`,
`cluster/ops/submit.sh` (the only way a job is submitted), `cluster/ops/poll.sh`, `cluster/ops/fetch.sh`, and what to do
when a job fails. `cluster/ops/test_fake_cluster.sh` runs all of them against a fake cluster.

## Local development

```bash
python3 checks/validate.py --qualify --binary bin/p3cg --bug-binary bin/p3cg_bug1 --bug-binary bin/p3cg_bug2
python3 checks/run_plan.py run --plan local --job local-smoke     # timing pipeline at 1-8 ranks, rows marked local
python3 scripts/plot_dev.py                                       # figures/dev/local_strong.png (stamped as local data)
```

Local rows are for development only: `run_record.py --for-figures` refuses them. On an Apple M5 laptop, memory
bandwidth limits speedup to about 1.4× at 8 ranks, so local runs say nothing about cluster scaling.

## Source layout

| File | Contents |
|---|---|
| `src/grid.*` | process grid, local box, unknown/nonzero counts |
| `src/halo.*` | halo exchange (blocking and overlapped), planted bugs |
| `src/kernels.*` | stencil, vector updates, manufactured problem, device-mapped storage |
| `src/cg.*` | operator with interior/shell split, classic and pipelined CG, timers |
| `src/record.*` | run record, cluster detection, SHA-256 of the binary |
| `src/par.hpp` | loop pragmas for the CPU-thread and GPU-offload builds |
| `src/main.cpp` | options, setup, repeats, true residual and error, solution dump |

The offload build (`P3_OFFLOAD`) has not yet run on a GPU. On the Mac it compiles, and its target regions run on
the host (host fallback), where it passes `validate.py --qualify`; device execution and data mapping are tested only
by the Vanda GPU job.
