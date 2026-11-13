# Frame: language pass and presentation of the DSA5208 Project 3 report

## The artifact
The written report for DSA5208 Project 3, "Parallelizing an Algorithm with MPI+X". It is a PDF built from LaTeX:
`build/report/DSA5208_Project3_Report.tex` / `.pdf` (82 pages: about 26 pages of report text, the rest code listings).
All numbers in the body are generated from run records and must stay generated.

Its purpose: to be graded (35 points), and to be something the two students can stand behind and explain.

What the report contains (facts, given by the primary material):
- the algorithm: conjugate gradient for the 2D and 3D Poisson equation, matrix-free;
- the parallel design: domain decomposition with MPI, halo exchange variants, classic vs pipelined CG, OpenMP threads, a GPU
  path via OpenMP offload;
- validation;
- serial scaling; MPI strong/weak scaling, communication cost, comparison of methods; MPI+OpenMP layouts and one GPU;
- a real-data extension: CG on graph Laplacians of SNAP networks for community labelling, with accuracy against ground truth;
- AI declaration; how to run; code appendix.
Some sections are still waiting for the >=256-core runs, and some interpretation paragraphs are drafts.

## The reader
- **First reader:** the grader. The course instructor for this project is Anthony Chen (NUS Mathematics; research in fast
  algorithms for atmospheric and ocean modelling; he wrote Lectures 7-12 on parallel computing, MPI, OpenMP, CUDA, Kokkos and
  the design of parallel algorithms, and the grading slide). [given: course materials]
- **What the reader knows:** MPI, OpenMP, GPUs, CG, scaling analysis, the Poisson equation — expert level. [inferred: he
  teaches them] He does not know this group's choices, code or data. [inferred]
- **Conditions:** one report among many in the class, read on screen as a PDF; no rubric beyond the Lecture 12 grading slide.
  Minutes available per report: unknown.
- **Second reader:** the two students (Kushagra Bhatnagar, Pratyush Sinha), who submit it under their names and must be able
  to explain every sentence. [given: names on the title page; the user's request]

## What the grader has said about reports (given, verbatim, Lecture 12)
- "All non-standard terminology used in the report should be defined"
- "Please explain your validation tests"
- "For the validation tests, if you have 100+ tests, why?"
- "If you use AI, you have to declare it. It is very obvious when you use AI, even if you don't declare it."
- "Your report has to make sense. All terminology has to be defined."
- "You should include some plots. Plots should effectively convey information. For plot axes that are time, problem size,
  or CPU count, these should be logarithmic."
- Grading: algorithm explained (5); serial scaling with problem size (5); MPI scaling to >=256 cores, strong and weak,
  speedup and efficiency, impact of communication (10); MPI+X (10); overall discussion (5).

## The user's words (given, verbatim)
"ok now you need to apply a pass over it , so there are small sentences, senctnbces are not first principled, semi cokons
sentenes not u derstandable without prior context run an assumption drill on how should the output pe presented and how
shoud the language pass be done hgiven the context  by hand"

Read as four complaints about the current text:
1. sentences that are too short / choppy;
2. sentences that are not "first-principled" (meaning not settled: they may mean "do not build up from basics", or "state
   a conclusion without the reasoning that leads to it" — unknown which);
3. semicolon-chained sentences;
4. sentences that cannot be understood without prior context.
Plus: the pass is to be done "by hand" (not by mechanical find-and-replace).

## After reading, the reader should (target reception)
- The grader: "I know what they solved, why it is not embarrassingly parallel, how they split it, what each design choice
  costs and gains, that it is correct, and how it scales — and each claim is backed by a number I can find." Then they award
  marks per grading row without hunting. [inferred from the grading slide]
- The students: "I can read any paragraph aloud and explain it, without having been in the build." [inferred from the
  user's complaint 4]

## Open (left open by the user and the material)
- What "first principled" means here (see above).
- Target length: no page limit is given.
- Whether the structure (section order, what goes in appendices) may change, or only the sentences.
- How much of the build machinery (run records, timing gate, plan, validation qualification) the grader should see.
- Register: "we" voice, formality level.

## Default sketch (what the pass would be without the drill)
Keep the structure; go section by section. Split every semicolon sentence into two sentences. Merge runs of very short
sentences into one. Add a definition at the first use of each term. Keep every number and claim; do not add claims. The
reason this default seems right: the user named four sentence-level faults, so the fix is assumed to be sentence-level, and
the grader's own comments ask for defined terms and sense. Length roughly unchanged.
