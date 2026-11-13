# The circuits used in DSA5208 Projects 1 and 2

Extracted 11 Nov 2026 for Project 3 (MPI+X, due 17 Nov 23:59 SGT). This file sits on top of the copied source
files in this folder. It is a summary of what was used, not a Project 3 circuit; that is the next step.

## What "circuit" meant in each project

- **Project 1 (Cassandra consistency, 19–27 Sep).** There was no `reasoning_circuits` encoding yet. The circuit was
  the Researcher–Runner protocol. ChatGPT was the Researcher and owned acceptance. Claude Code was the Runner. You
  carried packets between them. Gates G0–G7 decided what could move forward. Afterwards, `WORKFLOW_TRANSFORM_DSA5208.md`
  rewrote the workflow backwards from what the grader needs (rows E1–E12).
- **Project 2 (rainfall, Spark, 17–18 Oct).** This was a real encoding in your `reasoning_circuits` package:
  `p2_circuit.py` with owners, quoted gate lines, five decisions D1–D5, `compute` and `load`. Its output was the set
  of checks the child had to build, the gates those checks enforce, and the points where the child stops for you.
  Project 2's `CIRCUIT.md` §1 also restates Project 1's protocol as a circuit and shows what carried over.

## Project 1: Researcher–Runner protocol

Files: `project1_cassandra_consistency/`

| Piece | Content | Source |
|---|---|---|
| Roles | Researcher accepts claims; Runner implements and cannot accept its own conclusion; user is courier and decides scope | `RESEARCH_PROTOCOL.md` §2 |
| Acceptance invariant | Every transition cites inputs, a named procedure, retained output and a check that can tell a valid case from an invalid one. Four levels: computation, measurement, intervention, interpretation | §3 |
| Gates | G0 grounded start · G1 semantic/design adequacy · G2 apparatus qualified · G3 instrument qualified · G4 pilot adequate · G5 frozen confirmation (not opened) · G6 accepted finding · G7 report readiness | §4 |
| Ledger | Append-only `C-000001…`, record types F/PR/P/V/E/D/R; every number names its command and output file | `RUNNER_INSTRUCTIONS.md` |
| Stop rule | Hard stop after each packet; the next packet comes only after a Researcher audit | `RUNNER_INSTRUCTIONS.md`, last section |
| Grader-first rewrite | E1–E12 table of what the grader needs. Found two rows with no producing step: authors (E8) and the Canvas upload (E9) | `WORKFLOW_TRANSFORM_DSA5208.md` §1, §4 |

**Outcome:** 29.5 / 30, submitted 27 Sep, no grader comments (Canvas, read 11 Nov).
Report: `DSA5208_Project1_Report.pdf`. Group: Kushagra Bhatnagar (A0351591A) · Pratyush Sinha (A0352482A).

## Project 2: encoded circuit, parent and child

Files: `project2_rainfall_spark/`

**How it was built.**
- `CIRCUIT.md` explains the circuit.
- `p2_circuit.py` encodes it.
- `compute_output.txt` is its output.

Run `python3 p2_circuit.py` from that folder; it imports `~/Desktop/connector/components/circuits/src`. Re-run on
11 Nov from the copied location, its output matches `compute_output.txt` byte for byte.

**The five decisions and the gate `load` said was decisive.**

| Decision | Move chosen | Gate that changes the move | Became |
|---|---|---|---|
| D1 where Spark runs | local first; cloud only after you claim the coupon | "coupon form shares your details"; "environment captured from the run" | `checks/env_capture.py`; env § generated from `env.json` |
| D2 data scope and cleaning | all 8 years, ingest check and ledger | none alone (two redundant refusers) | `ingest_check.py`, `clean_ledger.py` |
| D3 comparing years | normalise by coverage | none (marked "not proven to bind") | `coverage_check.py`, plus your eye check of the first figure |
| D4 Task 2 design | split by time; plan frozen by hash before the test year | autocorrelation / time split | `eval_plan.py`; Model A strict + Model B nowcast |
| D5 report and package | ask for names and IDs **now** | names-and-IDs gate | `requirements_check.py`: brief rows E1–E14, zero hand-typed numbers, authors, AI declaration |

**Where the child stopped for you:** at the start (names/IDs, cloud route, build skill), before blind or irreversible
acts (creating a Dataproc cluster, the Canvas upload), and at the first rendered samples (first Task 1 figure set, first
full PDF).

**Roles:** the parent session accepted; the child built in `build/` with the `build-application` skill
(`~/Desktop/tutor_papers/skills/build-application`) and could not accept its own results. The child's briefs are in
`child_briefs/`; the parent's decision log is `parent_state.md`; the acceptance table is `acceptance.md`.

**Report language pass:** `report_language_ASSUMPTIONS.md` (assumption drill). Each paragraph states a decision, its
reason and its consequence. Praise is replaced by evidence. Reasoning goes in prose. Captions say what to notice.
The environment section uses the lecture's terms. Limitations come with numbers.

**Outcome:** submitted 18 Oct 11:47 SGT, not yet graded (Canvas, read 11 Nov).

## What went wrong or cost time (keep for Project 3)

- **Checks were qualified only on broken inputs.** The circuit's own rule says a check binds only after passing an
  accepted example. The qualification described only refusals. Recorded in `casebook_C12_P1_to_P2_transfer.txt`.
- **Five cloud reruns.** You asked whether five was too much. Causes, from `parent_state.md`:
  - a User-Agent 403;
  - stale Parquet objects that doubled the ingest rows;
  - a hung `gcloud jobs describe`;
  - an idle-deleted cluster.
  Most of these came from the remote environment, not the code.
- **Classifier-blocked actions** (an IAM binding, a mass delete on GCS) were not worked around; the fix went into code
  instead.
- **Author fields.** Project 1 left them open until the due day. Project 2 asked at the start, and that worked.

## What looks transferable to Project 3 (candidates, not decisions)

The requirement table for Project 3 should combine the Canvas brief with the Lecture 12 grading split
(`../course_materials/INSTRUCTOR_GUIDANCE_P3.md`). The lecture asks for more than the brief:
- 256+ cores;
- strong and weak scaling;
- serial scaling over problem size;
- a GPU test if X = OpenMP;
- log axes;
- no logs in the submission;
- defined terminology.

| Project 3 item | Earlier mechanism that fits | What changes |
|---|---|---|
| Runtime figures from Atlas or Vanda | D1 `env_capture`: environment and timings written by the run itself | Cluster job scripts (PBS) and node, rank and thread counts come from the scheduler's records, not the Mac |
| Serial scaling (5 pts); MPI strong and weak scaling to ≥256 cores with speedup and efficiency (10 pts) | D4 frozen plan: fix problem sizes, rank and thread grid, repetitions and metrics before the cluster runs | Vanda core-hours are limited and Vanda keeps going down, so the plan also sets the run budget and an Atlas fallback |
| MPI+X analysis (10 pts) | D1-style fork, settled by building both where cheap (as Model A/B in P2) | Rank × thread layouts per 72-core node; if X = OpenMP, a GPU run is also required |
| Validation that the parallel algorithm is correct | P1 acceptance invariant: a check must distinguish valid from invalid | Compare parallel with serial output on known answers. Show the check catches a planted bug and passes a correct run. Keep the test set small and explained: the instructor asked "if you have 100+ tests, why?" |
| Design decisions in the parallelization | P2 report rule: decision → reason → consequence | Decomposition, communication pattern, MPI vs OpenMP/CUDA/Kokkos choice |
| Code + README; PDF only on Canvas | D5 `requirements_check` and the package step | Code goes in the PDF or a public GitHub link. Publishing a public repository is your decision |
| Names and student IDs | D5: ask at the start | Confirm the Project 3 group (Projects 1 and 2 were Kushagra + Pratyush) |
| Explanation of AI usage | D5 AI-declaration check | Same |

**New for Project 3:**
- choosing an algorithm that is not embarrassingly parallel;
- C/C++ with MPI plus one "X";
- an NUS HPC account with VPN access to `atlas8.nus.edu.sg` / `vanda.nus.edu.sg`;
- Vanda downtime, which already caused two deadline extensions.

This Mac has no MPI or OpenMP toolchain yet (no `mpicc`, no Homebrew `open-mpi` or `libomp`). It is an Apple M5 with
10 cores and 16 GB, so CUDA cannot run locally. There are no `atlas`/`vanda` entries in `~/.ssh`, so the HPC account
and access are still unconfirmed.
