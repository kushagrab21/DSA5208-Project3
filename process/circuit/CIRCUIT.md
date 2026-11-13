# Project 3 circuit: what decides the build, and what it turns into

DSA5208 Project 3 (MPI+X), due **17 Nov 2026, 23:59 SGT**. Written 11 Nov by the parent session.
- Encoding: `p3_circuit.py`.
- Computed output: `compute_output.txt`, under rules 0.2.
- Run: `python3 circuit/p3_circuit.py`. The output is deterministic.

## 1. What kind of circuit this is

It works the way Project 2's did (`../prior_circuits/project2_rainfall_spark/CIRCUIT.md`). Each decision records:
- the gates in force and who owns each;
- the quoted lines that carry each gate to the decision;
- which move the gates allow.

`compute` gives the predicted move and what is at risk. `load` shows which gates actually change the move.
Your drills still set how it is used:
- it is a proposal, because nothing has run;
- it gets force only through what a checker prints or refuses;
- a check binds only after passing an accepted example;
- you come in at four points (forks that change a fix, unstated properties, blind or irreversible acts, first rendered
  samples).

So the output is **the checks the build must print, the gates they enforce, and where the child stops for you** (§5).

### What carries over from Projects 1 and 2, and what doesn't

Each earlier mechanism was kept only where its reason still applies here.

| Earlier mechanism | Its reason there | Project 3 | Why |
|---|---|---|---|
| P1/P2: the builder cannot accept its own results | stops self-certified claims | **Kept.** This session accepts; a child builds | Same risk. The cheap version (parent and child, no courier) worked in P2 |
| P2 D1: the environment is written by the run (`env.json`) | the report must describe the machine the numbers came from | **Kept, stronger.** The solver writes its own record: cluster, PBS job ID, nodes, ranks, threads, GPUs, size, and time split into halo, reduction and compute | The brief requires figures "from Atlas or Vanda". The split also feeds the communication analysis (L12) |
| P2 D4: evaluation plan frozen by hash | stopped the test year leaking into model choice | **Changed.** A run plan check prints the graded cells filled and core-hours used. No hash | Nothing is held out here. The risks are an empty graded cell, and reruns on a limited Vanda that keeps going down |
| P2: checks qualified on broken inputs | showed a check can refuse | **Fixed.** The validation check must pass the correct build *and* refuse a planted bug before it gates timing | Your rule ("binding only after it has passed an accepted example"); casebook C12 found P2 skipped the accepted case |
| P2 D5: ask for names and IDs at the start | P1 left them to the due day | **Settled today:** "yes same group" | That gate no longer changes anything (D6 load) |
| P2: every number is generated | no hand-typed numbers | **Kept** in `requirements_check` | Same report pipeline |
| P2: report language rules (`report_language_ASSUMPTIONS.md`) | the report reads as the group's own decisions | **Kept, plus** "define all terminology" and "it is very obvious when you use AI" from L12 | The grader said so directly |
| P2: five cloud reruns | — | **Closed** in D5: no unplanned job leaves the plan | Your line: "wow, these have been 5 reruns, isnt that too much ?" |

## 2. Who owns what

| Owner | Kind | Lines |
|---|---|---|
| Brief and grader (Anthony Chen) | external | Canvas brief; L7 guidelines; **L12 grading and comments** (`course_materials/INSTRUCTOR_GUIDANCE_P3.md`) |
| NUS HPC | external | Atlas is CPU-only and slow; Vanda is limited and goes down; you log in with your NUSNET password and need VPN off campus |
| You, now | you | "yes same group"; "develop the semantic circuit for project 3" |
| You, earlier | you, settled | P1 "take minimum input from me"; P2 "5 reruns, isnt that too much"; P2 "dont submit, ill submit myselves"; circuit_use rule 5 |
| Build skill | skill | `build-application` (parent and child), as in P2 |

## 3. Judged properties (the requirement table)

Every row must be answered in the report or the package. `requirements_check` prints this table and refuses release
while a row is unmapped. (B) = Canvas brief; (G) = L12 grading; (C) = L12 comments.

| # | Property | Source | Where |
|---|---|---|---|
| E1 | The algorithm is introduced | B; G 5 pts | §Algorithm |
| E2 | Serial runtime over problem size, varying structure (matrix size and nonzeros, or vertices and edges) | G 5 pts | §Serial scaling |
| E3 | MPI strong scaling to ≥256 cores, with speedup and efficiency | G 10 pts | §MPI scaling |
| E4 | MPI weak scaling to ≥256 cores, with speedup and efficiency | G 10 pts | §MPI scaling |
| E5 | Effect of communication on runtime, using the L12 model (flops, volume/bandwidth, calls×latency) | G 10 pts | §MPI scaling, from the halo/reduce/compute split |
| E6 | MPI+X analysis: rank × thread layouts on 72-core nodes | G 10 pts | §MPI+X |
| E7 | At least one GPU run if X = OpenMP | G 10 pts | §MPI+X |
| E8 | Design decisions: how it was split, which technique where, which parts communicate most | B; G 5 pts | §Design, §Discussion |
| E9 | Validation that the parallel code is correct, with each test explained and the set kept small | B; C | §Validation |
| E10 | Runtime figures come from Atlas or Vanda | B | every figure, from run records |
| E11 | Real data: conclusions about it; synthetic data: how it was generated | B; C | §Data |
| E12 | Topic asks: Poisson in 2D **and** 3D; for a graph, the effect of sparsity | C | §Algorithm, §Serial scaling |
| E13 | All non-standard terminology defined | C | at first use |
| E14 | Plots with log axes for time, problem size and core count | C | figures |
| E15 | AI use explained | B; C | §AI usage |
| E16 | Code and README in the PDF or behind a public GitHub link; no log files or terminal output | B; C | appendix or link |
| E17 | Names and IDs: Kushagra Bhatnagar (A0351591A) · Pratyush Sinha (A0352482A) | B; you today | title |
| E18 | You upload to Canvas by 17 Nov 23:59 SGT (PDF only) | B; announcement | yours |

## 4. The decisions, and what `compute` says

Each finding is a proposal under rules 0.2, followed by the change it makes to the build.

**D1: Where it builds and runs.**
- *Gates:*
  - the brief requires figures from Atlas or Vanda;
  - L12 asks for 256+ cores;
  - this Mac has no MPI (10 cores);
  - no Atlas or Vanda login has ever been seen from this Mac;
  - cluster jobs need your NUSNET login;
  - the run writes its own record.
- *Computed:* it branches, as P2's D1 did. Either ask you about access now, or install the local toolchain and then
  ask. The open precedence between rule 3 and rule 5 is why there are two branches.
- *load:* **only "HPC login unconfirmed" and "run record written by the run" change the move.**
- **Change:**
  - The child installs Open MPI, libomp and CMake and develops locally at up to 10 ranks. This is needed either way,
    and the circuit marks local runs as proxies: they print a record, but not one from Atlas or Vanda.
  - Access goes to you now (§6). The agent never types your password. You set up key-based SSH once (on campus or
    on VPN), and then the child can submit PBS jobs itself.

**D2: Which algorithm.**
- *Gates:*
  - "not embarrassingly parallel";
  - "an algorithm of your choice";
  - the progress report that may have been sent before 30 Oct;
  - notes: structure must vary in serial runs, Poisson needs 2D and 3D, graphs need a sparsity discussion,
    synthetic data makes weak scaling easy, and six days are left.
- *Computed:* **ask the group.** The choice is yours, and if a progress report already named an algorithm,
  Anthony Chen's feedback is attached to it.
- *load:* "not embarrassingly parallel" and "the group's choice" change the move. The notes change nothing.
- **What the agent proposes when it asks:** conjugate gradient (CG) for the Poisson equation, 2D and 3D, matrix-free
  stencil, on synthetic problems with a known exact solution. Reasons:
  - **Not embarrassingly parallel.** Each iteration needs a halo exchange with neighbouring ranks (bandwidth-bound)
    and two global dot products (latency-bound `MPI_Allreduce`). That maps straight onto L12's runtime model, so E5
    can be measured, not asserted.
  - **There is room for "different methods of parallelization" to compare:**
    - 1D, 2D or 3D domain decomposition (`MPI_Cart_create`);
    - blocking or non-blocking halo exchange that overlaps interior work;
    - classic or pipelined CG (one `MPI_Iallreduce` overlapping the operator). This is L12's "Avoiding Communication"
      in practice.
  - **Weak scaling and validation are easy.** The grid grows with the number of ranks. A known exact solution gives
    error falling as h², and parallel versus serial must agree to rounding.
  - **E2 and E12 come for free.** Size changes the matrix dimension. 2D against 3D changes nonzeros per row (5 against
    7). L12 explicitly asks for both dimensions.
  - **Risk:** it is a common choice, and Anthony Chen works on atmosphere and ocean models, so he knows this ground
    well. That fits L7's "the simpler … the more sophisticated the parallelization should be": the decomposition and
    communication choices are where the marks are.

  **The alternative** is BFS or PageRank on SNAP graphs. Communication is more irregular, and the real data must be
  partitioned and analysed (E11). That is heavier for six days.
- **D2' (variant: you say "you pick", and K-means is the first familiar example).** The lecture's example list puts
  K-means in front. Compute then branches on one gate: **whether the grader reads K-means (one small allreduce per
  iteration) as embarrassingly parallel.** Only the grader can settle that. On the K-means branch the property is at
  risk because the choice clears the brief only as a proxy.
  **Change:** if you hand the choice over, the agent does not pick an algorithm whose acceptability depends on an
  unsettled reading by the grader. That rules out K-means and regression-type loops.

**D3: Which X.**
- *Gates:*
  - "If you choose X=OpenMP, then you also have to test on at least one GPU";
  - MPI+X is graded at 10 points;
  - L9 frames the question of how many ranks and threads to put on each 72-core Vanda node;
  - L12 gives CUDA-aware MPI through nvhpc;
  - Kokkos must be built with both backends (whether Vanda has it is unknown);
  - GPUs are only on Vanda, which goes down.
- *Computed:* **MPI+OpenMP threads on CPU nodes, with the same kernels offloaded to one GPU using OpenMP `target`
  (nvhpc on Vanda).**
- *load:* in D3, only "MPI+X analysis graded" changes the move. Rule 4 takes the first open edit in the encoder's
  listing order, so **D3 lists my preference.** Variant **D3'** puts CUDA first. There, "GPU only on Vanda, and Vanda
  goes down" and "Kokkos must be built" both change the move.
- So the choice between X options turns on **Vanda availability and Kokkos availability**, not on the lectures.
  - OpenMP with offload keeps the main X analysis (rank × thread layouts) runnable on Atlas if Vanda is down. Only the
    one required GPU run needs Vanda.
  - CUDA puts the whole X analysis on Vanda.
- **Change:**
  - X = OpenMP. The GPU run uses the same loops with `target` pragmas, compiled with `nvhpc-hpcx-cuda12/26.1`.
  - Kokkos is not used unless Vanda turns out to have a ready module.
  - The rank × thread cells are 1×72, 2×36, 4×18, 8×9 and 72×1 per node. `run_plan` prints how many are filled.

**D4: Validation.**
- *Gates:*
  - the brief requires validation;
  - your rule that a check binds only after passing an accepted example (with the C12 lesson);
  - "if you have 100+ tests, why?";
  - "explain your validation tests".
- *Computed:* a few named cases. Parallel against serial must agree to rounding. Error against the exact solution must
  fall as h². A planted halo bug must be refused.
- *load:* **only "check passes the correct build first" changes the move.**
- *At risk:* "the validation tests are explained and few" **reaches the decision only as a note.** Nothing printed
  carries it.
- **Change:**
  - `validate.py` prints the number of cases and one line of purpose for each.
  - `requirements_check` maps E9 to a section that explains them.
  - Timing scripts refuse any binary whose hash has not passed `validate.py`.

**D5: The scaling runs.**
- *Gates:*
  - L12's MPI cells (256+ cores, strong and weak, speedup, efficiency, communication) and the serial size sweep, both
    enforced through `run_plan`;
  - Vanda's limited core-hours and your "5 reruns" line, which close ad-hoc reruns;
  - Vanda down (unknown);
  - Atlas capping jobs below 256 cores (unknown; NUS lists Atlas8 as 24-core nodes, in undated material);
  - the instructor's promise to extend for downtime.
- *Computed:* three branches:
  - Vanda up: run the fixed plan on Vanda, with up to 288 cores (4 nodes × 72) and 3 repeats, as a few batched jobs.
  - Vanda down and Atlas accepts 256 cores: run the CPU scaling on Atlas and keep the GPU run for Vanda.
  - Both closed: no rule says what to do. The agent waits, and the decision becomes yours.
- *load:* **"no unbudgeted reruns", "Vanda down" and "Atlas refuses a 256-core job" change the move.**
- **Change:**
  - The first cluster session reads the Atlas queue limits (`qstat -Qf`) and the Vanda allocation, which settles the
    Atlas gate.
  - Cluster runs start early: one small job as soon as access works, then the full plan once D4 passes.
  - `run_plan` refuses a job that is not in the plan unless the plan file records why.

**D6: Report and package.**
- *Gates:*
  - the E1–E18 table;
  - log axes and no log files;
  - terminology defined;
  - names and IDs (settled today);
  - the AI declaration;
  - the code route (inside the PDF, or a public GitHub repository);
  - the first rendered sample;
  - you upload;
  - the deadline.
- *Computed:* fill every row from run records, then stop for you. Two questions are required: the first full render
  and the code route. No rule orders them, so they go as one stop.
- *load:* **only "code route" and "first rendered sample" change the move.** Names and IDs no longer do, since you
  answered.
- *Not proven to bind:* "terminology defined". The check measures "each flagged term has a definition sentence".
  You judge "the report makes sense to the grader". That gap is recorded (`measures` ≠ `prop`). Your read of the
  first full render is the real check.
- **Change:** the report goes through the P2 language rules plus L12's two comments. The code route is your call,
  because a public repository publishes under your name.

## 5. What the circuit compiles into

**Checks the child builds.** Enforced checks refuse the next step.

| Check | Prints | Enforced | Qualified on |
|---|---|---|---|
| run record (written by the solver) + `checks/run_record.py` | `RUN cluster= job= nodes= ranks= threads= gpus= N= iters= t_total= t_halo= t_reduce= t_compute=` → `results/<cluster>/<job>.csv` | yes: figures are drawn only from Atlas/Vanda rows | a real cluster row (pass) and a Mac row offered as a figure (refused) |
| `checks/validate.py` | number of cases with their purposes; parallel vs serial gap; error order; planted bug refused; hash of the binary allowed for timing | yes: timing scripts refuse other binaries | **the correct build (pass)** and a planted halo bug (refused) |
| `checks/run_plan.py` | serial sizes, strong, weak, X layout and GPU cells filled out of total; core-hours used against the budget | yes: no job outside the plan without a recorded reason; no release with an empty cell | a complete plan (pass) and one missing the 256-core weak cell (refused) |
| `checks/requirements_check.py` | E1–E18 mapped; hand-typed numbers 0; linear time, size or core axes 0; log files in the package 0; authors 2; AI section | yes, except TERMS, which is printed only (not proven to bind) | the first full render (pass once you accept it) and a copy with a linear core axis (refused) |

**Where the child stops for you.** Nowhere else:
1. **Now:**
   - HPC access and key-based SSH;
   - the algorithm, and whether a progress report named one;
   - whether to reuse P2's parent and child setup.
2. **Blind or irreversible acts:**
   - publishing a public GitHub repository;
   - the Canvas upload (yours);
   - the D5 gap, if Vanda is down and Atlas can't take 256 cores. That decision is yours: wait for an extension, or
     email Anthony Chen.
3. **First rendered samples:** the first scaling figure built from real cluster records, and the first full PDF.

**Parent and child** (as in P2, if you agree):
- The child builds in `build/` with `build-application`.
- This session accepts results only after reading the printed checker output.
- If the child needs something only you can give, it holds its state and waits.

**Rough schedule:**

| Date (Nov) | Work |
|---|---|
| 11–12 | Toolchain; serial CG in 2D and 3D; validation qualified; first small Atlas/Vanda job |
| 13 | MPI decomposition, halo exchange, reductions, and the pipelined variant |
| 14 | OpenMP and offload; plan frozen; full cluster runs |
| 15 | Fill gaps on the plan only; figures |
| 16 | Report, language pass, first full render to you |
| 17 | Buffer for Vanda downtime; you upload |

## 6. Limits of this circuit

- It is one encoder's reading, made before anything has run. Nothing in it binds yet.
- **Listing order decides between equally open edits** (D3, and D2's proposal). The variants show which gates would
  overturn that order. The reasons for the order are written out above, not computed.
- Some "at risk" lines are artefacts of rules 0.2. Under 0.2, a ban on some other move counts as "still fails", the
  same quirk P2 noted. These are D3's "X=OpenMP needs a GPU test" on the OpenMP path, D5's "no unbudgeted reruns",
  and the CG branch of D2'. The real risks are D4's note-only "explained and few", D2''s proxy, and D6's terminology
  gap.
- Several gates rest on things nobody here has seen yet: the Atlas queue cap, the Vanda allocation, and whether Kokkos
  is on Vanda. Each is an open trigger until the first login.
- The rule 3 against rule 5 precedence (D1, D2) is still open in your package.
- The real test is the build: the checkers' printed verdicts and the grader's reading. Agreement with `compute` is not.

## 7. Answers since writing (11 Nov), re-computed

Each answer turns off only the gate it names (rule 8). Both are encoded as `d1_answered` and `d2_answered` at the end
of `p3_circuit.py`.

| Your answer | Gate turned off | Re-computed move | What remains |
|---|---|---|---|
| "CG Poisson 2D+3D (Recommended)" | D2 "the algorithm is the group's choice" | E[CG, 2D and 3D] → R. Only "not embarrassingly parallel" still changes the move | "the group will defend it" now reaches the build only as a note. Pratyush should see the choice and this circuit before the report is drafted |
| "Account works, set up keys" | D1 "HPC login unconfirmed" | E[local toolchain] → R. Only "run record written by the run" still changes the move | "cluster jobs need your login" stays open until a non-interactive `ssh` succeeds. Until a cluster run exists, every runtime figure is at risk (a local run clears the record check only as a proxy). The enforced run-record check is what keeps Mac numbers out of the report |
| "Same as Project 2" (build setup) | none (it is not a gate) | — | This session accepts results; a `build-application` child builds in `build/` |

## 8. HPC access route (11 Nov): which circuit, and what is prepared

**Which circuit.** This is a setup and handoff problem, not a design fork. From your semantic-workflow router it is
**B3, "Own setup and resumption"**:
- the parent prepares every capability it is allowed to;
- you get only the step that truly needs you;
- the parent then verifies the operation and takes the work back.

The course gives the same procedure: Lecture 13, "Demo 2: HPC projects". This build follows it:

| L13 step | Here |
|---|---|
| 1. "Prepare the tool (SSH) for the agent by setting up the password-free login to the NUS HPC cluster." | This section |
| 2. "Let the agent explore the procedure for submitting jobs, monitoring their progress, and handling failures." | Prepared ahead and tested on a fake cluster (`build/cluster/ops/`, `build/cluster/RUNBOOK.md`, child turn 3). Then the parent's first cluster session: `qstat -Qf`, `hpc project`, one small job on each cluster. This settles D5's Atlas gate and the core-hour budget |
| 3. "Turn the working procedure into a skill that can be reused for future tasks." | After step 2 works: a `nus-hpc-jobs` skill (submit, monitor, collect run records, handle failures) |
| 4. "Build two subagents, one for C++ coding and verification, and the other for handling MPI jobs on HPC" | The C++ child is running now. The HPC-jobs role starts with the parent (D1: cluster access is the parent's). It can move to a second child once the skill exists |

**What the evidence showed**:
- `atlas8.nus.edu.sg` and `vanda.nus.edu.sg` don't resolve from this Mac, and no VPN client is installed.
- Off campus, the NUS VPN is required (`comp_res.pdf`). NUS A.S.K. gives these details:
  - the client is Cisco Secure Client (KBA00028326);
  - the profile is "NUS Student - TLS - Auto Select Nearest Location";
  - MFA through Microsoft Authenticator is required.
- On campus, NUS or NUS-STU Wi-Fi works, but eduroam does not (a public Vanda course tutorial).
- The slides and the course handout describe only password login. The NUSNET ID could not be read from Canvas: the
  browser tool blocked it, and that block was not worked around.

**Who does what**:

| Step | Who | Why |
|---|---|---|
| Key `~/.ssh/id_ed25519_nus` (used only for atlas8 and vanda) and the config block (ControlMaster, 8 h) | parent, **done** | Entrusted by your request ("get the access with minimum manual work"). `~/.ssh/config` was backed up to `config.bak-2026-11-11` |
| One-time script `.application/hpc_first_login.sh <NUSNET_ID>`: fills in the ID, checks the network, installs the key, tests both clusters without a password | parent, **done** (checked on a copy) | — |
| Install and connect Cisco Secure Client, or be on NUS / NUS-STU Wi-Fi | **you** | Your NUS password, MFA, and your Mac's approval of a system extension |
| Give your NUSNET ID, and type your NUSNET password once in the script | **you** | The agent never types your password |
| Verify `ssh -o BatchMode=yes atlas8 true` and `vanda`, then L13 step 2 | parent | — |

**Recurring cost:** cluster work only happens while the VPN is up (or you're on campus). Runs are batched (D5), so
the VPN only needs to be up when jobs are submitted and when results are collected, not while jobs run.

## 9. What the first real access settled (12 Nov)

- **D5 "Atlas refuses a 256-core job": ON.** On Atlas you can use `parallel` (12–96 cores per job, 96 running per user) and
  `serial`. `hpc6a` (192 cores) is limited to a named list of users. So Atlas can never fill the 256-core cells. They are
  Vanda-only, and Atlas is a fallback up to 96 cores.
- **D1 "cluster jobs need your login":**
  - **Atlas:** cleared. The key works.
  - **Vanda:** still on. The new account has not reached Vanda yet (the portal says "NUS HPC account not found").
- **A new failure the circuit did not have, and its fix.** The parent's watcher retried key logins on Vanda every 10 s, and
  each retry counts as a failed login. Vanda then refused the Mac's VPN address. Fixes:
  - watchers check reachability (`nc`) or the portal, never authentication;
  - Vanda is reached through Atlas (ProxyJump).
  This is a parent mechanism (B2: repair the generating rule), not something the child checks.

## 10. D7: the data-science extension (12 Nov)

Encoded as `d7` and `d7_ridge_first` in `p3_circuit.py`. The candidates were:
- **graph:** CG on graph Laplacians from SNAP networks with ground-truth communities;
- **ridge:** regression by CGLS on a UCI/LIBSVM sparse dataset;
- **suite:** CG on SuiteSparse matrices;
- **none:** no extension.

**What compute and load say.** Your request rules out "no extension". The brief and L12 require conclusions about real
data, which SuiteSparse clears only as a proxy. Both graph and ridge clear every gate, and **no gate changes the move**
(load: all "no change"). In `d7` graph wins only because it is listed first. In `d7_ridge_first`, ridge wins. So the
course's lines do not separate the two. As in D3, the choice rests on reasons outside the gates, written down here
rather than computed:
1. Graph keeps the validated CG and pipelined CG unchanged: only the operator changes, from stencil to sparse
   matrix-vector product. Ridge needs CGLS.
2. The SNAP community datasets carry ground-truth labels, so "conclusions about the data" can be scored.
3. One dataset family, from 25 K to 117 M edges, covers L12's "the number of edges and the number of vertices should
   vary". L12's graph comment ("discuss the impact of graph sparsity") then applies directly.
4. Ghost-vertex exchange is a second communication pattern to contrast with the regular stencil halo.

**Decision (parent, under your delegation):** semi-supervised community labelling on SNAP graphs:
- solve (L + αI) x_c = b_c with CG for each chosen community c, seeded from a few labelled members;
- label each node by the largest x_c;
- score against the ground truth.

**At risk, from compute:** "the parallelization presents real challenges" reaches D7 only as a note. **Change:** the
plan gets graph cells up to 288 cores on Vanda, with the ghost-exchange time split out like the stencil halo, and the
requirement check gets the graph rows (E11 conclusions, E12 sparsity).

The remaining at-risk entries ("reported while 'no extension…' still fails") are the known 0.2 artefact, where a ban on
some other move counts as still failing.
