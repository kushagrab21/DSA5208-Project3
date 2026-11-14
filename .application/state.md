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

## Turn 3 (11 Nov 2026): cluster operations, tested on a fake cluster (no real cluster contact)
- cluster/ops/: common.sh (P3_SSH/P3_RSYNC transport), discover.sh, sync.sh, submit.sh (only route to qsub), poll.sh,
  fetch.sh, opslib.py (rules, ledger, qstat parsing, merge, calibration, missing-cells); scripts/apply_discovery.py
  (diff; writes only with --apply); cluster/RUNBOOK.md (procedure + failure playbook, skill-shaped).
- Fake cluster: cluster/ops/fake/ (fake ssh/rsync, fake qsub/qstat/hpc/module/pbsnodes, fake launcher);
  cluster/ops/test_fake_cluster.sh runs 32 steps; output kept in results/ops_tests/ (gitignored). The validation job
  runs for real in the fake home; timed jobs run the generated PBS script with the fake launcher.
- Plan change: <cluster>-calibrate job (4 graded cells: serial 2D n=4096, 3D n=256; strong 2D/3D on one full node),
  the only timed job allowed before the freeze. Vanda 8 jobs, est. 164 core-h (<=328 worst case).
- Ledger: results/<cluster>/jobs.csv, events submit/start/end/final, merged by fetch, never rewritten.
- Calibration: results/<cluster>/calibration.json (bandwidths) feeds run_plan estimates and PBS walltimes.
- Cluster builds embed "<commit>-synced" (SYNCED file) instead of git "unknown".
- Report: CPU sections use the cluster plan with the most graded cells filled (Vanda on ties).
- env.sh has an inert test seam (P3_FAKE_LAUNCH) used only by the fake cluster.

## Turn 4 (12 Nov 2026): Atlas findings from the first real discovery
- Real discovery: results/atlas/env/discover-20261111T183351Z.txt (parent ran discover.sh atlas8).
  Usable: parallel (12-96 cores/job, 96/user, 4 running, pool par12), serial (1 core, 2-15 GB). hpc6a ACL; normal disabled.
  Compute nodes listed: 33 x cnode-33-* with 96 cores, ~358 GB (par12 membership not printed by the old filter).
  Module list in that file was cut at 300 lines (A-B only): OpenMPI/foss/CMake fell off; EasyBuild names were visible.
- Fixes: apply_discovery queue rules (Execution, enabled+started, not from_route_only, ACL only if user listed,
  resources_min.ncpus, per-user max_run_res; every job checked); discover.sh records user, node_pool, ebenv status, one
  module query per name, Atlas hpc help pages; atlas env.sh sources ebenv (P3_EBENV), loads newest foss by pattern,
  prints it, refuses the 2013 mvapich2 mpicxx; build.sh uses CMake only if >= 3.16; run_plan status with
  "unlimited" budget (crash fixed); per-job memory (job mem_gb or pbs.mem_per_cpu_gb) and serial queue routing.
- Atlas plan regenerated (scripts/make_plan.py build_atlas_plan): 114 cells, 5 jobs, <= 96 cores, fallback flag,
  limits recorded; check says PASS AS A FALLBACK PLAN + NOT MET (>=256 cores is Vanda-only).
- Report: each section uses the cluster that completed it (Vanda first); captions name the cluster; series must be one
  binary (else unfilled); E3/E4 NOT MET (with reason) if scaling is complete only below 256 cores; the text says so.
- Tests: cluster/ops/test_fake_atlas.sh (19 steps), requirements selftest scenarios (Atlas only, mixed clusters,
  mixed build), test_fake_cluster.sh (32 steps) unchanged and passing.

## Turn 5 (12 Nov 2026): Vanda made runnable on the first submit
- Real Vanda discovery results/vanda/env/discover-20261112T055509Z.txt: -P route `auto` -> batch_cpu (1-720 cores,
  10 nodes, 6 running) / batch_gpu (1-2 GPUs); cpu_node 72 cores x 501 GB (211 GB was only rn-003, offline);
  foss/2025b + Python/3.13.5-GCCcore-14.3.0 (= Atlas), nvhpc-hpcx-cuda12/26.1; hpc samples in ANSI colour.
- apply_discovery: strips ANSI, resolves routing (route_destinations, from_route_only), default queue (qstat -Bf or
  `auto` implied by the samples), project/budgets/mem from CLI (--project, --budget-cpu/--budget-gpu/--budget-source,
  --mem-per-cpu-gb), select_ompthreads, GPU shape per GPU, every job checked against its landing queue.
- env.sh (vanda): cpu = ebenv + foss/2025b + Python (no purge); offload = nvhpc-hpcx-cuda12/26.1 (+ Python fallback);
  refusals are top-level returns; set -e safe; libfabric guard when a foreign one is preloaded; all logged.
- Fixed set -e hazards found by the fake (would have killed the first Vanda job): failing command substitution in an
  assignment (ld.so.preload read; grep -v on an empty LD_LIBRARY_PATH); Atlas env.sh got the same pipeline guard and
  the LD_PRELOAD comment fix.
- run_plan: ompthreads in select, GPU limits; Vanda plan: GPU job 1 x 72 cores + 2 GPUs, batch limits recorded.
- opslib: GPU-hour budget (gpu_hour_budget), worst case per GPU job; fetch copies into the staging folder (openrsync
  made a directory for a missing file).
- Tests: test_fake_cluster.sh 39 steps (routing, env guards, GPU job with its own qualification) all as expected;
  test_fake_atlas.sh 19; all selftests pass.

## Turn 6 (12 Nov 2026): the data-science extension (SNAP community labelling), in worktree ../build-graph
Branch graph-extension (worktree /Users/kushagra/Desktop/final_assignment/build-graph); build/ untouched.
- Solver: src/cg_impl.hpp = classic/pipelined CG as templates over the operator (moved from cg.cpp; Poisson dumps
  bitwise identical before/after on 4 layouts). bin/p3graph (src/graph/): DistGraph (rank 0 reads rowptr + SNAP ids,
  bcast; each rank MPI-IO reads its columns; rows|nnz partition; keep filter on SNAP ids; ghost lists once;
  dist-graph communicator), CsrOperator (L + aI; alltoallv | neighbor | overlap = Ineighbor + interior rows;
  per-thread nnz-balanced row ranges), labelling (K largest disjoint-enough communities, theta 0.1; seeds by
  mix64(SNAP id ^ mix64(seed)), nested in s; truth/eval = exclusive non-seeds; majority/random baselines; unreached =
  all x_c <= 0 counted wrong). PLANT_GHOST_BUG=1: first source neighbour's ghosts go to a scratch area.
- bin/p3convert (src/graph/convert.cpp): SNAP text -> P3CSR001 (natural + BFS/Cuthill-McKee order) + .cmty in both
  orders + meta.json. Reproduces SNAP counts (email-Eu-core V=1005, E=16064 undirected; com-amazon 334863/925872).
- scripts/fetch_snap.sh (login node; gzip -t; SOURCES.tsv url/bytes/sha256; refuses a changed file),
  scripts/convert_snap.sh (refuses inputs whose sha256 differs from SOURCES.tsv; CONVERSIONS.tsv), data/ gitignored.
- checks/validate_graph.py: G1 email-Eu-core (SpMV <= 1e-14, 10 iterations <= 1e-10, converged within cond bound;
  25 iterations was NOT sharp: rounding grows ~1000x per 5 iterations on this graph), G2 tiny dense + converter
  counts, G3 = planted bug refused. Qualified on the Mac (p3graph ce6ea36c...; bug refused by G1+G2). timing_gate
  --require-cases G1,G2; run_record graph schema p3graph-1 in *.graph.csv (Poisson loader never sees them).
- Plans: scripts/make_graph_plan.py adds groups graph-serial/strong/variants/sweep + jobs as amendment
  graph-2026-11-12 (existing content verified unchanged; idempotent; legal on a frozen plan; make_plan.py keeps it).
  Vanda 190 graph cells, 7 jobs, ~657 core-h est. (~1970 with x3); Atlas 182 cells, 5 jobs, ~751 (~2253), fallback.
  run_plan: graph cost model (graph_model, ASSUMED), matching, coverage (E11/E12 groups, >=256 on Vanda, variants
  combos, sweep ranges), PBS bodies (P3_DATA, GREC, prep: build graph + convert + qualify + seeds; failed graph cell
  logged, job continues); job names p3g-<role>. submit.sh/opslib check bin/p3graph against a G1;G2 qualification.
- Report: section "Real data: community labelling on SNAP graphs" (data, method, parallel design, validation G1-G3,
  accuracy vs baselines, a/s/sparsity, serial ladder, strong + comm, partitions/exchanges, conclusions = interp box);
  5 graph figures, 4 tables, ~70 values, all pending until cluster rows. requirements_check: E11/E12 required rows
  (refused without the section), G1-G3 identifiers. PDF 74 pages (graph code in the appendix).
- Fixed on the way (also on main): requirements_check main() crashed after its verdict (unpacked 4 of 5 results);
  .gitignore "bin/" ignored cluster/ops/fake/bin (fake tests could not run from a fresh checkout) -> "/bin/".
- Ops: poll counts <id>.graph.csv rows; opslib estimates use the per-job safety (x3 graph); submit checks
  bin/p3graph. Fake tests: test_fake_cluster.sh 50 steps (11 graph steps: refusal before graph qualification,
  graph-prep for real on fixtures, G1;G2 fetched, graph job 70/70 rows), test_fake_atlas.sh 19; all selftests pass;
  Poisson p3cg requalified on the Mac after the CG template move (V1-V5 pass, bugs refused by V3-V5).
- Merge rehearsed in a /tmp clone against a simulated parent main (frozen plans, reruns, unplanned): auto-merges.
- Local dev (Mac): email-Eu-core accuracy 0.758 (majority 0.193, random 0.1, 102 it/solve); com-amazon 1.000
  (majority 0.192; 113 it/solve; 0.14 s/solve at 4 ranks); amazon keep 1/8 -> acc 0.07, 93% unreached.

## Next (parent): cluster/RUNBOOK.md "Vanda" first sequence. Atlas: atlas-calibrate 1040047 still queued.

## Tonight (parent): cluster/RUNBOOK.md "Atlas" - discover atlas8 again -> apply_discovery (read, --apply) -> check ->
commit -> sync -> submit atlas-validate -> poll/fetch -> submit atlas-calibrate -> poll/fetch.

## First real session (parent): see cluster/RUNBOOK.md "First session, in order"
key works -> discover vanda/atlas8 -> apply_discovery (read diff, --apply) -> run_plan check -> commit -> sync both ->
submit vanda-validate + atlas-validate -> poll/fetch -> submit vanda-calibrate -> poll/fetch -> freeze, commit, sync ->
submit vanda-4node, vanda-gpu, vanda-1node-scaling, vanda-serial, vanda-2node, vanda-1node-variants-layouts.

## Turn 7 (12 Nov 2026): GPU split, the report from 262 real Vanda cells, drafted interpretations
- Real Vanda (parent's runs): every 1- and 2-node job and all graph jobs except graph-4node finished; vanda-4node and
  vanda-graph-4node wait for 4 free nodes; vanda-gpu (2 GPUs, excl) never placed ("ngpus (R: 2 A: 1 T: 70)").
- Amendment gpu-split-2026-11-12 (scripts/amend_vanda_gpu_split.py, idempotent, --check): vanda-gpu1 =
  select=1:ncpus=36:mpiprocs=1:ompthreads=36:ngpus=1:mem=105gb, place=pack, own offload build + validate.py, the two
  1-GPU cells; vanda-gpu keeps its resources and the 2-GPU cells (changed_by recorded); rerun reasons pre-recorded
  for the 1-GPU cells (queued 1546583 still has the pre-split script). job_select: per-job mpiprocs/ompthreads.
  Fake test 52 steps (gpu1 qualified + gated); E7 now needs only the 1-GPU cells and the 1-node layouts.
- Report on real rows: partial figures (drawn from recorded cells, red "still waiting" line, rows stay WAITING),
  partial tables (recorded rows + waiting row), per-role values (one/q/half/node/2node, so Atlas works too),
  partial_values(); fixes: Poisson validation reader picked the graph JSON (crash), comm 1-rank points, log-axis
  labels (narrow ranges had none), graph-serial labels/lines, hybrid rows in fig_graph_variants, label order,
  make_graph_plan repeats rule now independent of calibration (--check passed again).
- Drafts (\draftreview, DRAFT-FOR-USER-REVIEW; requirements_check lists them, rows not FILLED): serial, mpi-node,
  graph-serial, graph-accuracy, graph-sparsity, graph-parallel, graph-conclusions. Waiting slots: mpi-top,
  graph-parallel-top, mpix, discussion. PDF 81 pages.
- Findings: bandwidth-bound in the node (E 0.26 at 72, 2 nodes halve the time); 36 ranks sit on one socket (18->36
  only x1.14; 36->72 x2.01); pipelined slower at <= 144 on the grid (x1.38-1.44, model bytes 1.33) but FASTER for
  graphs across nodes (0.72-0.81 of classic) where classic graph CG slows down on 2 nodes (x1.49-1.54); graph hybrid
  2x36 x1.86 on Orkut; rows partition x1.55-2.03 slower; BFS order cuts MORE edges on LJ/Orkut.

## Turn 8 (12 Nov 2026, ~22:30 IST): 256-core insurance job on shared nodes
- Amendment spread256-2026-11-12 (scripts/amend_vanda_spread256.py, idempotent, --check): job vanda-256spread,
  select=8:ncpus=32:mpiprocs=32:ompthreads=1:mem=93gb, place=scatter, binary cpu+graph, bind none; 12 cells
  (placement shared-8x32, insurance_for the 288-rank cell): Poisson strong + weak 2D/3D classic+blocking and
  pipelined+overlap, graph strong com-lj/com-orkut classic+pipelined; added to the strong/weak/graph-strong groups.
  Estimate from measured 144-rank siblings (x1.0 / x1.2 / x2.0 + setup): 1595 s, walltime 00:55:00, 113 core-h
  (227 worst). The whole-node 288 jobs stay queued.
- env.sh: P3_BIND=none -> --map-by ppr:N:node --bind-to none and OMP_PROC_BIND=false (only that job; others unchanged).
- Rows record placement through the cell id (-pshared8x32) and the tag (<group>@shared-8x32): binaries unchanged.
- run_plan: mixed-binary jobs (one gate per program), est_seconds, per-placement matching; opslib checks both
  programs. Report: a run or its insurance partner completes a group; values/figures from recorded cells; hollow
  diamonds for shared-node points (same 1-core baseline); meas.top/meas.where name the top count and placement;
  E3/E4 met from either placement (selftest scenario "only the 256-core shared-node insurance run").

## Turn 9 (13 Nov 2026): the language pass (assumption_drill/report_language_pass, binding)
- Report body rewritten by hand, paragraph by paragraph (backup of the previous body: not kept in the repo; git has it).
  Order: placement, paragraph logic, sentence rules. Full pass on Sections 1-5, 8.1-8.7 and 8.10, captions and
  generator strings; placement + sentence rules only on 6, 7, 8.8-8.9 and 9. Summary untouched (waits for data).
- New structure: 1 algorithm + synthetic test problem, 2 parallel design (+ cost model, why reductions not the product
  limit scaling, MPI windows one sentence), 3 validation tests, 4 hardware and measurement (sockets, cores per socket,
  memory, launcher fills socket 0 first, compilers, fixed iterations, median of repeats), 5 serial, 6 MPI, 7 MPI+OpenMP
  answering Lecture 9's four questions in order, 8 graphs (opens with why it is there), 9-11. Roadmap after the Summary.
- Removed from the body: "Made by" lines (\src), title-block generator line, E-codes, run IDs, plan/qualification/
  insurance/calibration words, Atlas column, the module table (tab_env). Provenance: one sentence in Section 11
  (generated_at, env.jobs, plan.vanda.cells, val.sha/val.stamp/val.cl.sha) and a Provenance paragraph in README.
- The seven DRAFT-FOR-USER-REVIEW paragraphs are merged with their generated paragraphs and marked \revised{name}
  (prints nothing); requirements_check lists them as "revised under the language rules", not as drafts.
- Generators: tab_plan is a plain experiments overview; env.* values from the job environment records; spread.sent/
  cap/tabnote/except replace spread.desc; scale.where says "up to N nodes" from the recorded whole-node runs;
  tables and figure legends say "non-blocking halo exchange", "decomposition", "reductions (MPI_Allreduce)";
  new tab_graphserial (per-graph ns/nonzero and BFS speed-up moved there from prose).
- Stale comments fixed: src/par.hpp, CMakeLists.txt P3_OFFLOAD, README offload note (the GPU build passed V1-V5 on
  GN-A40-032 in job 1547835, both broken builds failed).
- Checks: 0 hand-typed numbers; prose semicolons 53 -> 2 (both in the Summary); selftests PASS (figures, run_record,
  run_plan, graph_plan, requirements_check; fixture env records now carry compilers and memory).
- Value keys removed from the text: atlas.topcores, plan.atlas.cells (no Atlas timings), spread.desc (retired),
  gs.com-dblp.bfsratio, gs.com-youtube.bfsratio, gs.com-orkut.ns (now in tab_graphserial).
- Open flags: memory per socket assumes an even split (not recorded); GPU model only from the node name; network not
  recorded; appendix listings drop non-ASCII characters (arrows, <=) in README/code comments (pre-existing: listings
  literate does not apply under tectonic); waiting marks still use plan wording and "; " (vanish with full data).

## Turn 10 (13 Nov 2026): the cold-reader findings fixed
- Thesis stated once (2.5): inside a node memory bandwidth limits scaling (new floor T_mem >= max(beta N/(s B),
  beta N/(P b))), across nodes the reductions take a growing share; up to 144 cores the runs are in the first regime,
  the graphs are communication-bound on two nodes. 1.4 and 2.3 point to it; 6.1 calls it "the memory regime".
- From the code: 96/128 B = 12/16 streams (classic 3+6+3, pipelined 3+13, write-allocate counted) -> STREAMS in
  report_macros.py, checked against the plan's model; flops 15/17 per point -> intensity 0.16/0.18. Graph operator
  stores no values (all -1): 4 B per off-diagonal index + 16 B per row -> 5.4 B/nnz on com-Orkut vs 19.2 for the stencil.
- From the records: repeat spread (median 0.6 %, 41 of 184 configurations > 5 %, one-core up to 48 %); one-core
  pipelined/classic 1.08/1.10 vs model 1.33 (full node 1.38-1.44); time-to-tolerance exponents 1.61/1.43 vs 1.50/1.33
  (cost per unknown grows N^0.10 over those sizes); com-Youtube natural-order serial repeats 23.8/19.8/14.3 ms, so its
  BFS speed-up 1.75 is uncertain (1.27 fastest-vs-fastest); seeds are excluded from evaluation (label.cpp); Table 16
  runs on 72 ranks (8 for email-Eu-core); labelling, time-to-tolerance and the one-core com-Orkut runs solve once.
- Specifications cited as such: Intel 8452Y (8 DDR5-4800 channels -> 307.2 GB/s per socket, 67.5 MB cache), NVIDIA A40
  (48 GB, 696 GB/s; GPU model taken from the node name, not recorded); Yang & Leskovec for SNAP's top-5000 selection.
- Placement wording generated for all four states (288 whole / 256 shared / both / neither): scale.where, st.counts,
  spread.sent ("an additional run" when both), waiting marks no longer say "may come from whole or shared nodes";
  Table 7 shows recorded cores and configurations and a "solves" column.
- Appendix printed from ASCII copies (report/generated/listing/), 0 missing characters.
- Checks: 0 hand-typed numbers, 0 prose semicolons, selftests pass. Keys removed from the text: gr.acc.com-amazon,
  gr.acc.com-dblp, gw.com-dblp.deg, gw.com-youtube.deg (all in tables), rankcounts (replaced by st.counts + scale.where).

## Turn 11 (13 Nov 2026): second cold-reader check resolved
- Table 1: dims_create now follows Open MPI's MPI_Dims_create (2D 72 ranks = 12x6, not 9x8) and geometry() takes the real
  rank with the most halo (3D 72: 59,772, not the hypothetical 60,112); matches pdims and halo of all 80 recorded runs.
- Validation: Section 3 reports the CPU solver's run (20261112T063938Z, a0006417c428), not the latest (a GPU build);
  Section 11 lists only the programs whose rows are used (CPU solver, graph solver 9da57b11ddd2, GPU ace45bed3220,
  each validated on Vanda minutes before its first timed row); 2e0a5b22 (job 1547835) rows are superseded by 1546583.
- Weak baseline: the one-rank weak runs (CN-007, job 1546584) cost 2.66/3.06 ns per unknown-iteration against
  4.06/4.54 at two ranks (same job, node) and 3.57/3.92 for serial runs of half the size (CN-094); 67 MB of vectors per
  rank ~ the 67.5 MB socket cache, unconfirmed; one-node weak efficiency now from two ranks (0.27/0.28 ~ strong 0.25/0.26).
- Pipelined/classic: weak series (one job, one node) 0.94/1.00 at P=2/4 in 2D (1.04/1.10 3D), 1.37/1.41 at 36 ranks;
  the strong one-core pair ran on two nodes (classic CN-094 serial job, pipelined CN-007).
- Reductions: per iteration unchanged one node -> two (3D 0.79 ms); two ranks on one socket already 0.79/0.85 ms;
  same size as the compute imbalance (max - mean). Stated as probable waiting; latency not timed.
- GPU: reference is the fastest recorded one-node CPU run of the grid (3D 72x1 2D-decomp, Table 12; 2D 4x18, Table 13),
  1.16/1.12; Table 13 shows the one-node column while the 4-node runs wait.
- Also: attainable accuracy with the V5 point (1.1e-10 at 215 its, 1.5e-9 at 3,000); Poisson-only "100 iterations";
  repeat-spread count reconciled with Table 7 (shared configurations); 6.4 causes from the time split; Lecture 9 Q&A
  shortened; 8.8 recorded core counts; 8.9 per graph; 8.10 iterations follow d_max; Table 7 narrowed (all pages fit).
- Not changed: the AI declaration wording (the user's text) although the cold reader called "coordinating session" jargon.

## Turn 12 (13 Nov 2026): visual structure (report_visual_markers drill, recommendations 1, 2, 3, 5, 6)
- 1: \parskip 3pt -> 0.5\baselineskip (no indent); lists, algorithm boxes and captions checked on rendered pages.
- 2: displayed kappa (1.2), the V5 bound (numbered (1), used by Table 5's caption and G1), row v of eq. (2) and the
  condition-number bound (numbered (3), used by G1 and 8.10), and the Krylov span (8.2). S and E stay inline.
- 3: labels (italic, sentence case, full stop, run-in), only in Sections 3 and 4. Section 3: "Error against the exact
  solution (V1, V2).", "Parallel against serial runs (V3, V4).", "Pipelined CG (V5).", "Broken halo exchanges.",
  "Accuracy of pipelined CG beyond the tests." Section 4 split into six blocks: "The nodes.", "Sockets and rank
  placement.", "The GPU node.", "Compilers.", "What is timed.", "Repeats." (timers paragraph merged into "What is timed").
- 5: Section 7 has Lecture 9's questions as (1)-(4) items (question, then full-sentence answer); Section 9 paragraph 1
  has the three parts as plain items. No bold heads.
- 6: every figure and table is referenced (Figs 3, 4, 5, 7, 10, 11; Tables 18, 19 added).
- Long paragraphs split between their two steps (2.2, 5, 6.1, 6.2, 6.3, 8.3, 8.5, 8.6, 8.7, 8.9, 8.10, 11).
  Paragraph length (pp. 1-25, the drill's script): median 6 -> 5 lines, p90 10 -> 8, max 18 -> 9.
- Part-empty pages (p7, p10, p22 before; p10, p12, p22, p23 after the reflow) cured by [htbp] on Figures 3, 5, 11, 12
  (\figslotfloat) and Tables 9, 10, 20; each float stays within a page of its first mention. References still on p25,
  appendix on p26, 84 pages. requirements_check knows \figslotfloat.
- Not done (deferred by the parent): recommendation 4 (margins) until the cluster data are in.

## Turn 13 (13 Nov 2026): the repository as a private archive (.application/repo_transfer.md, binding)
- .gitignore rewritten with a reason per entry. Tracked now: results/ (run records, validation .json/.csv, job ledger,
  node descriptions), figures/*.pdf and their .meta.json, report/DSA5208_Project3_Report.pdf, report/generated/ (except
  listing/, its diff shows which numbers changed). Ignored: bin/, _build/, __pycache__/, .venv/, data/, cluster/logs/,
  cluster/generated/ (regenerated from the plan), results/.staging/ (refilled by fetch.sh), results/ops_tests/ and
  results/validation/**/*.txt (terminal transcripts; requirements_check counts them as log files), figures/dev/,
  report/*.log, report/generated/listing/, .DS_Store.
- Checked: no private keys or tokens in the tracked set ("password" appears only in prose), no file over 5 MB.
  The PBS project string (the user's NUS account) is in config/run_plan.vanda.json and RUNBOOK, as the scripts need it.
- README rewritten for a reader without context: what the program solves, where things are, why numbers are generated,
  why the plan was fixed in advance, why a program is timed only after passing the tests on that cluster, building
  locally, running on Vanda, adding the remaining runs, the AI declaration (Section 10 wording). No measured results.
- process/ (copy of the process notes) from repo_transfer.md was not part of this brief; left to the parent.

## Turn 14 (14 Nov 2026): 288-core data in, graph rerun prepared, final text pass
- Records (committed by the parent): vanda-4node 1546582 complete (strong, weak, variants, layout to 288 cores on 4 whole
  nodes, one of them GPU node GN-A40-066 with the same CPUs and memory). vanda-graph-4node 1546819 exceeded its walltime
  (21 of 40 cells: every com-LiveJournal cell, one com-Orkut cell). vanda-256spread 1549987 exceeded its walltime
  (Poisson and com-LiveJournal shared-node cells recorded, both com-Orkut ones missing).
- Amendment graph-rerun-2026-11-14 (scripts/amend_vanda_graph_rerun.py, committed as e15eeda): the 19 missing
  com-Orkut cells move to vanda-graph-4node-rerun (4 x 72, place=excl), strong cells first, breadth-first cells last.
  Estimate 17,601 s from measured com-LiveJournal cells at 288 x the com-Orkut/com-LiveJournal ratio at 72 (+10 s each,
  +300 s job overhead), walltime 9:50:00 (x2), 1,408 core-h expected, 2,816 at most. Rerun reason per cell. NOT
  submitted. Submit: cluster/ops/sync.sh vanda && cluster/ops/submit.sh vanda vanda-graph-4node-rerun
- Report reads correctly with or without the rerun: reportdata gains superseded() (a shared-node cell whose whole-node
  partner is recorded leaves figures and tables, one sentence in 6.1), outstanding() (missing cell with a rerun reason)
  and settled(); figures draw settled groups as filled; graph values use each graph's largest complete count
  (com-LiveJournal 288, com-Orkut 144 strong / 72 methods) with a generated sentence saying so.
- Text: Summary rewritten (no semicolons, no gloss); thesis, 6.1-6.4, 7, 8.8-8.9, 9 revised for 288; the four orange
  boxes written. Kept to 288: efficiency lost inside the node (0.26 on 1, 2 and 4 nodes); pipelined slower at every
  count (3D 1.44, 1.38, 1.44). Changed: communication share grows (3D 10 -> 17 -> 27 %), 2D reductions grow with nodes
  (latency), 3D reductions follow the imbalance. Graphs: com-LiveJournal on 4 nodes no faster than 1, hybrid 8x9 per
  node best (1.53x pure MPI), breadth-first + neighbourhood collective 32x slower at 288.
- Margins 2.8 cm (drill item 4). Wide tables fit with adjustbox, Section 6 floats follow their first mention, tall
  floats [htbp] where [H] left gaps; every float within a page of its first mention, one page 19 % empty.
- requirements_check: PASS (0 hand-typed numbers, 0 waiting, 0 log files); every selftest passes.

## Next step
Parent (turn 8): sync vanda; cluster/ops/submit.sh vanda vanda-256spread; keep vanda-4node / vanda-graph-4node /
vanda-gpu queued; fetch and make_report when rows arrive. Turn 9: the cold-reader check of the revised report.
Child (when cluster rows exist): scripts/make_report.sh; language pass on 6, 7, 8.8-8.9, 9 and the Summary; write the
four interpretation boxes from the tables under the same rules; fix
whatever requirements_check.py reports; render for the user. Open user decisions: code route (PDF appendix is in
place; GitHub link optional), first full render acceptance, the Canvas upload.
