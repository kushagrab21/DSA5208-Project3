# Child build state: DSA5208 Project 3 (CG Poisson 2D/3D, MPI+OpenMP)

Role: delegated builder (child) under build-application. Parent accepts; parent owns cluster access, user contact.
Brief: ../.application/build-task-01.txt (turn 1). Binding design: ../circuit/CIRCUIT.md (E1-E18, section 5).
Acceptance evidence: .application/acceptance.md. How to build/run: README.md.

## Turn 1 (11 Nov 2026): DONE locally, all 7 steps
1. Serial CG 2D/3D matrix-free; error O(h^2) shown (validate V1/V2).
2. MPI: decomposition 1D/2D/3D (MPI_Dims_create/Cart_create), halo blocking (Sendrecv) / overlap (Isend/Irecv +
   interior/shell split), classic / pipelined (Ghysels-Vanroose, one Iallreduce) CG; OpenMP in all kernels;
   offload behind P3_OFFLOAD (compiles; host-fallback validated; device untested).
3. Run record: src/record.cpp (one CSV row per repeat, schema p3run-1), checks/run_record.py (+ --selftest).
4. checks/validate.py qualified: correct PASS 5/5, planted bugs 1 (skip face) and 2 (shift face) REFUSED by V3-V5.
   Output kept: results/validation/local/20261111T163733Z.txt. Validated list: results/validated_binaries.csv.
5. config/run_plan.{vanda,atlas,local}.json from scripts/make_plan.py; checks/run_plan.py (status/check/pbs/run/
   selftest). Vanda: 148 cells, 7 jobs, est. 158 core-h (316 with x2 safety). Atlas fallback: 152 cells, 103 (206).
6. cluster/{vanda,atlas}/{env.sh,job.pbs.in}; generated scripts in cluster/generated/ (gitignored); README.md.
7. Local smoke: results/local/smoke-20261111T163747Z.csv (66 rows); figures/dev/local_strong.png.

## Current binary
bin/p3cg sha256 50211edd312d7c225889b1d00e3173ad4288f4624eef1c386e70ecef30661a66 (qualified, cluster=local).
The binary embeds the git sha, so a commit followed by scripts/build.sh changes the hash -> re-run
`python3 checks/validate.py --qualify ...` (3 s locally). Cluster binaries are always qualified on the cluster.

## Decisions taken in turn 1 (child, within scope) and why
- Exact solution u = prod x(1-x)e^x, not prod sin(pi x): sine is a discrete eigenvector, CG converges in 1 iteration
  (measured: iters=1). `--problem sine` kept only to show this.
- Agreement tolerance 1e-10 after 25 fixed iterations (observed <= 5e-13; planted bugs ~0.5).
- Pipelined comparison uses the rigorous bound cond(A)(rho_p+rho_s)/(1-cond(A) rho_s), cond(A)=cot^2(pi h/2).
- Timers: t_total = slowest rank; t_halo/t_reduce/t_compute = mean over ranks (+ _max columns); t_reduce includes
  waiting for slower ranks (load imbalance), not just latency.
- cluster=atlas|vanda only when PBS_JOBID is set (env.sh sets P3_CLUSTER); otherwise local.
- Strong grids 2D 8192^2, 3D 406^3 (6.7e7 unknowns each); weak ~2.1e6 unknowns/rank; ranks 1,2,4,9,18,36,72,144,288.
- Plan adds a serial-to-tolerance sweep (iterations grow ~n) and a variants factorial at 72 and 288 ranks.
- Timing jobs use place=excl; the validation job place=pack.

## Open (parent / first login)
- Queue/project names (plan "pbs"), core_hour_budget, module names (env.sh), python3 on compute nodes,
  Open MPI `--map-by ppr:R:node:PE=T` behaviour (check --report-bindings), GPU node shape (gpus/cpus per node).
- Freeze the plan ("frozen": true) before the first timed job.
- Recalibrate plan "model" (bandwidths) from the first cluster rows; current values are assumptions.
- Observed on the M5 only: pipelined CG costs 1.9x classic per iteration (traffic model says 1.33x); 8 ranks give
  1.4x (memory bandwidth). Cluster data decide both.

## Turn 2 (11 Nov 2026): report and its checks, built without cluster data
- report/DSA5208_Project3_Report.tex -> PDF via scripts/make_report.sh (Tectonic). 40 pages: body ~11, code appendix
  ~29 (src/, CMakeLists.txt, scripts/build.sh, cluster/vanda/env.sh, checks/validate.py, README.md).
- Every number is \val{} (report/generated/values.tex) or a generated table; cluster-dependent ones render as red
  "waiting for cluster data" marks; figure slots render as boxes until scripts/figures.py fills them.
- scripts/figures.py (cluster rows only; meta.json per figure; --selftest PASS on fabricated rows in /tmp).
- scripts/report_macros.py, scripts/reportdata.py; checks/requirements_check.py full (--selftest QUALIFIED on
  refusals: hand-typed number, AI section removed, linear core axis, source CSV edited; real report = incomplete).
- validate.py now also writes results/validation/<cluster>/<stamp>.json (structured numbers) + INFO accuracy floor.
- run_plan.py job-start writes results/<cluster>/env/<PBS_JOBID>.json (CPU model, memory, modules) for the
  environment table.
- scripts/testdouble_render.sh: full report from fabricated rows in /tmp/p3_testdouble (proof of drop-in).
- Requirements now: E1, E11, E12, E15, E16, E17 filled; E13 printed (TERMS: 29 used, 29 defined, none late);
  E18 user; waiting for cluster data: E2-E10, E14; interpretation boxes (to write after data): E2-E8.

## What happens when cluster rows arrive (no hand editing except the orange boxes)
1. results/vanda/*.csv (+ env/*.json, validated_binaries.csv, validation/vanda/*.json) land in results/.
2. scripts/make_report.sh -> figures fill, values fill, validation tables switch to the Vanda qualification JSON.
3. Write the interpretation boxes (\interpslot) in the .tex: serial, mpi, mpix, discussion.
4. requirements_check.py must print PASS; the user reads the first full render (that is the pass example).

## Next step
Parent: first-login checklist (README "Cluster runs"), then the vanda-validate job, then the timed jobs.
Child (when cluster rows exist): scripts/make_report.sh; write the four interpretation boxes from the tables; fix
whatever requirements_check.py reports; render for the user. Open user decisions: code route (PDF appendix is in
place; GitHub link optional), first full render acceptance, the Canvas upload.
