# Assumptions for the language pass on the Project 3 report

**Reader and conditions:** the grader, Anthony Chen, who taught MPI, OpenMP, GPUs, CG and the cost model, reads this
report on screen as one of many, with the Lecture 12 grading slide in mind. Behind him are you and Pratyush, who must be
able to explain every sentence.
**What "correct" means here:** after reading, the grader understands what was solved, how it was split and why, that it is
correct, and how and why it scales, finding each graded item where he expects it. He believes only what a number on the
page supports, and nothing reads as machine-written. You two can read any paragraph aloud and explain it without opening
another file.

## The assumptions that decide this pass
1. **"First-principled" means every claim follows visibly from what each process owns, what each operation needs, and the
   flops/bandwidth/latency cost model. It does not mean re-explaining CG.**
   Why: the grader's own papers and the human HPC reports (UMBC, Sandia) explain parallel results this way, and his
   lectures already teach CG, so restating it is padding. The current text often states a result and never gives the cause
   ("That shape held a surprise").
   Settled by: those sources, and **confirmed by you** ("Yes, that reading", 13 Nov).
   Changes: results paragraphs are rebuilt around their cause. Example: why the reductions, not the matrix product, limit
   scaling here, even though his own CG slide treats the product as the costly step.
2. **"Without prior context" means without the build's history. The body keeps only what the grader can map to his
   course.**
   Why: run plans, program hashes, E-codes, "qualification", "insurance run", "calibration" and the "Made by" captions are
   the build talking to itself. He cannot map them to anything he taught, and on AI use his slide says "It is very obvious".
   Settled by: the sources and his slides.
   Changes: those objects leave the body and go to the README. Three facts stay as plain sentences: the timed program
   passed the validation tests, how each time was measured, and which machine and compilers were used. The title-block
   script line goes.
3. **Each results paragraph runs: what was measured → the observation with its reference value → the mechanism → the
   consequence. A hedge says what was not measured.**
   Why: this is how the UMBC reports and the grader's own papers write ("efficiency falls to around 50% ... primarily
   because ..."). A bare "0.26" means nothing until it is set against the ideal of 1.
   Settled by: those sources.
   Changes: the hardware (two 36-core sockets, memory bandwidth) is described before the results that depend on it, so the
   socket and bandwidth effects read as derived, not as surprises. "Probably" becomes "we did not measure X; Y would settle
   it".
4. **No semicolons in the prose. Write the connective that names the relation. Join short sentences to the claim they
   support. Replace slogans with the plain claim.**
   Why: the grader's own prose uses no semicolons. In the human reports every step is linked by "so", "because" or "while".
   Splitting a semicolon sentence in two would only bring back your "short sentences" fault.
   Settled by: those sources and your complaint.
   Changes: this replaces the default "split every semicolon". Lines like "A check that cannot fail proves nothing." become
   the claim they gesture at. Short sentences survive only as signposts.
5. **Terms fall into three classes: his terms (used bare), non-standard terms (defined once, by describing the thing and
   then naming it), and build-internal words (removed).**
   Why: his slide asks that non-standard terms be defined, but redefining what he taught ("threads (workers that share one
   process's memory)") reads as written for a novice and makes sentences heavy.
   Settled by: his lectures and his slide.
   Changes: no definitions of rank, halo, speedup and the like. Matrix-free, pipelined CG, ghost layer, attainable
   accuracy, edge cut, graph-Laplacian shift and similar terms are each defined once. His words win: "reduction",
   "halo exchange", "domain decomposition", "validation tests", "synthetic test problem".
6. **Every number stays in the report. Prose carries only the numbers a claim needs, each with its reference, and none is
   retyped.**
   Why: the human reports put full sets in tables and give one or two numbers per claim in the text ("76.01, less than
   the optimal 128").
   Settled by: those sources and the report's generated-number rule.
   Changes: number-dense sentences are cut back, and every number in prose gets its ideal or baseline.

7. **One paragraph per finding. Each result is said once, and captions say only what was run and plotted.**
   Why: the grader's own scaling paragraph is setup, then one observation, then its cause, and his captions list only what
   is plotted (Chen and Jablonowski). In the report, a generated results paragraph is followed by a drafted interpretation
   that repeats the same numbers, and captions restate results.
   Settled by: those sources, found by the independent check.
   Changes: each results-plus-interpretation pair becomes one paragraph, repeats are deleted, and captions are cut to their
   contents. Paragraphs inside a section may move; the section order stays.
8. **Much of the machine-sounding text comes from the generator, so the generator's sentences are rewritten too. Claims
   the coming data could overturn are scoped to what was measured.**
   Why: "Made by scripts/..." (32 times), "a run counts if...", the module-list table and phrases that misread for some
   values are written by report_macros.py and figures.py, not typed into the .tex. A pass over the .tex alone would leave
   them. Claims such as "the efficiency is lost inside the node, not between nodes" may not survive the 256- and 288-core
   runs.
   Settled by: the independent check, confirmed against the report.
   Changes:
   - sentence templates in the generator are rewritten so they read correctly for any value;
   - provenance goes into one sentence in the "how to run" section;
   - open claims say "up to 144 cores";
   - the Summary, the communication and method interpretations, the MPI+X section and the Discussion get a second short
     pass when the data are in.

## Settled by you (13 Nov)
- "First-principled" means assumption 1 ("Yes, that reading").
- "By hand": the AI rewrites the text paragraph by paragraph, with judgement and without find-and-replace. There is **no
  read-aloud step** ("You rewrite, no read-aloud"). The AI declaration therefore says the text was revised by the AI under
  your direction.
- In place of the read-aloud test, a fresh agent with no context reads each revised section cold and marks any sentence it
  cannot follow. This is a proxy for the grader, labelled as such.

## How this differs from the default
Without the drill, the pass would have been sentence surgery: split semicolons, merge short sentences, add definitions
everywhere. Now it has three ordered steps:
1. Take the build's machinery out of the body.
2. Rebuild each paragraph as a cause-and-effect chain in the grader's own terms.
3. Apply the sentence rules: connectives instead of semicolons, no slogans, his vocabulary.

The assistant's further defaults are listed in `04_QUESTIONS.md` and are open to change:
- a plain experiment table;
- two small schematics;
- handling of the shared-node points;
- one sentence on MPI windows.
