# Step 3: drill

## Context carried in
- I started with only the brief for steps 2-3 and `01_FRAME.md`.
- The user's global instructions made me read the routing file `semantic-workflow/SKILL.md`. I used it only to decide how
  to work. No button reference was loaded, and nothing in it was used for form.
- Everything else here comes from material I read myself:
  - the report PDF/TeX, read for facts and to see the faults;
  - the course slides (Lectures 7-13) and the Canvas export;
  - the eight sources in `02_HUMAN_SOURCES.md`.
- I opened no earlier drills, run notes, earlier-project reports or skills about writing.

## What the exemplars show about how this reader reads
- **The reader's frame is ownership, then operations, then communication, then cost.** Chen's Lecture 8 slide on CG asks
  which operation is most costly, whether each rank owns all of A, x, r and p or a portion, and what communication
  follows. Lecture 12 gives the cost model: flops × time per flop, plus volume / bandwidth, plus calls × latency. The UMBC
  reports and the Heroux-Dongarra primer explain parallel CG in exactly this order. A claim that follows from this frame
  reads as obvious to him. A claim that skips it reads as asserted.
- **Results are read as observation, then cause, then consequence.** Chen writes "good scaling ... up until 64
  processors, at which point the performance plateaus, as the gains from additional parallelism are outweighed by the
  increases in communication". UMBC and the REU report write "This behavior is a typical characteristic of memory-bound
  code ... we would expect a bottleneck when more processes ... than the available 6 memory channels".
- **The hardware is described before the results that depend on it.** UMBC and the REU report draw the node (two CPUs,
  memory channels) in Section 1 or 2. Their later explanations then follow from the drawing and do not come as reveals.
- **Captions are reading keys, not findings.** Chen's captions say what is plotted, which side is which, and the
  parameters. The claim is made in the text that cites the figure.
- **Terms are introduced by describing the thing and then naming it, in a main clause.** UMBC writes "This summation ...
  is known as a reduce operation". Chen writes "θ is known in the literature as the multipole acceptance criteria". Only
  terms the reader does not already have get this treatment.
- **Sentences carry one claim and its link.** Claim sentences run to roughly 20-40 words, with *because, so, by
  contrast, however, therefore*. Short sentences appear only as signposts ("We now go into more detail."). Semicolons are
  absent or rare (a few in Chen-Krasny, joining a statement to its example).
- **Course-level weaknesses are visible to an expert.** The RPI course report shows them: an inflated word list,
  misdefined terms, results left at "needs further investigation". The grader says that AI use "is very obvious", and he
  asks why a report would have "100+ tests". Both comments show that he reads volume and machinery with suspicion.

---

## Part A. Load-bearing words, redefined for this grader and this report

**A1. "First-principled."**
- Two readings were left open: build up from basics, or give the reasoning behind each conclusion.
- What it means for this reader: the grader knows the basics. He taught CG, MPI and the cost model. What he cannot see
  is how our design and our numbers follow from those basics. The exemplars show one meaning that covers both readings.
  Every claim is derived, on the page, from (i) what each rank or thread owns, (ii) what each operation needs, and (iii)
  the flops/bandwidth/latency model. This applies to design claims and result claims alike.
- So: "first-principled" means a visible chain from ownership, operations and cost to the claim, in the grader's terms.
  It does not mean "explain CG from scratch".
- Status: ready to test on the sample in L2. **Only the user can confirm that this is what they meant.**

**A2. "Understandable without prior context."**
- What the "prior context" is: the build's own history, not the course. Examples are the run plan, insurance runs,
  qualification, "the calibration", program-file hashes, requirement codes E2-E12, "the defaults", "the dataset ladder",
  "refuse" and "planted bug".
- What the grader does have: his own lectures.
- So: a paragraph may assume Lectures 7-12 and earlier sections of the report. It may not assume anything that happened
  during the build.
- Test: each student reads a paragraph aloud and can explain it without opening another file.

**A3. "Clear."**
- For him: his vocabulary; every non-standard term defined; validation explained with a reason for its size; plots that
  "effectively convey information" with log axes for time, size and core count.

**A4. "Short."**
- The user's complaint is that the *sentences* are too short. It is not that the report is too long.
- So: "short" applies to the report as a whole, meaning no machinery and no padding. Sentences should be complete
  claims with their links, which usually makes them longer.

**A5. "Complete."**
- What it means: every item on the Lecture 12 grading slide and the "More Comments" slide is covered and can be found:
  - the algorithm explained;
  - serial scaling, varying both the dimension and the nonzeros;
  - at least 256 cores, strong and weak scaling, speedup and efficiency numbers, the impact of communication;
  - MPI+X with at least one GPU;
  - the overall discussion: how each part was parallelised and which parts communicate most;
  - for a graph problem, the impact of sparsity;
  - for synthetic data, how it was generated;
  - the validation tests explained;
  - AI declared;
  - the code included.
- What it does not mean: an exhaustive account of every run.

---

## Part B. Pre-mortem: "The grader stopped reading carefully after page 2 and marked down. Why?"

Likely causes, in page order. Each one points to the decision that removes it.
1. **Page 1 looks generated and unfinished.**
   - The title block reads "Numbers, tables and figures generated from the run records by scripts/report_macros.py ...
     19:52 UTC".
   - The Summary is one block: parenthetical definitions of terms he taught ("workers that share one process's memory"),
     a semicolon chain, and unresolved slots.
   - His slide says AI use "is very obvious". → P2, P3, P4, L3, L5.
2. **Pages 4-5 describe a pipeline describing itself.**
   - Section 2.6 says the program "appends one line per solve to a run record ... the SHA-256 hash of the program file".
     It says scripts "accept only records ... from a program file that passed the validation". It mentions the "run
     plan" and that "a run outside the plan needs a recorded reason".
   - Table 2 lists requirement codes E2-E12 and an Atlas column, although no Atlas timing appears.
   - Section 3 lists hashes such as "2e0a5b22cd3d".
   - He cannot map any of this to anything he taught. → P3.
3. **The captions cannot be read cold.** "Hollow diamonds: 8×32 cores on shared nodes, unbound, the insurance run,
   against the same one-core time." → P5, P6.
4. **The key results arrive as surprises, not as derivations.**
   - Sockets first appear in Section 6 ("That shape held a surprise").
   - The "calibration" bandwidth is never introduced. → P8, L2.
5. **The 10-point row has no ≥256-core numbers yet.** → P4 (order of work). This is a data problem, not a language
   problem.
6. **Something the grader will also read: code comments.** `src/par.hpp` line 5 in the appendix says the offload build
   is "UNTESTED until it is run on Vanda", and Section 7 reports GPU times. The pass must also check comments printed in
   the PDF for stale statements (a fact check, flagged here).

---

## Part C. Presentation

**P1. Default element: "Keep the structure."**
- Why it works in the exemplars: UMBC, Chen, RPI and REU all run problem → method and parallel implementation →
  correctness → performance → conclusions. The reader must trust the solver before reading its timings, and UMBC's
  convergence study comes before any timing.
- Depends on: the reader reading in order and marking against a list.
- Here:
  - It holds. Sections 1, 5, 6, 7 and 9 already map one-to-one onto the grading rows, and validation (Section 3) comes
    before the timings.
  - There is one gap. Every exemplar has a roadmap paragraph ("The rest of this report is organized as follows"), and
    the report has none.
- So:
  - Keep the top-level order.
  - Add a two-to-four-sentence roadmap after the Summary.
  - Retitle sections in the grader's words, for example "Serial runtime scaling with problem size" and "MPI strong and
    weak scaling, and the cost of communication".
  - Fold Section 4 into a short "Hardware and measurement" section placed before the results (see P8).
- Status: decided.

**P2. What leads: the Summary.**
- Exemplars:
  - UMBC opens with conclusions, each paired with its hardware cause.
  - Chen's abstracts are two or three sentences: what, how, applied to what.
- Why it works: the reader knows the findings first and reads the body to check them.
- Depends on: final numbers, and a reader who needs no definitions there.
- Here:
  - The reader needs no definitions. The parentheticals belong in the body or nowhere.
  - The ≥256-core numbers are still pending.
- So:
  - The Summary has four to six plain sentences: the problem and method; the parallel design in one sentence; the
    validation result; the headline scaling result with its cause; the MPI+X and GPU result; one conclusion about the
    data.
  - No parentheses for definitions and no semicolons.
  - Write it last, after the data arrive.
  - Remove the generation line from the title block.
- Status: ready to test once the numbers are in.

**P3. Reason, not object: the build machinery in the body.**
- Objects:
  - "Made by scripts/…" in every caption;
  - program-file hashes and run IDs in Section 3, the seed-list SHA-256 in 8.2, and the "qualification" in 8.4;
  - the run-record field list in Section 2.6;
  - Table 2 with requirement codes and an Atlas column;
  - Table 8's module chain and build strings ("omp=201511;offload=0;bug=0;…");
  - "a run counts if it or its shared-node insurance run is recorded" under every figure and table.
- What they were for: control inside the build. Every number had to be traceable, every requirement covered, and the
  timed binary had to be the validated one.
- Does that purpose hold for the grader? Only part of it.
  - He needs three facts: the timed program passed the validation tests on Vanda; how a time is measured (fixed 100
    iterations and why, median of 3, slowest rank, dedicated nodes); and the machine and toolchain.
  - He needs no file names, hashes or codes.
  - Lecture 12 says "Do not include log files or terminal output", and a module chain is terminal output.
  - UMBC gives the same facts in two sentences (MPI_Wtime after a barrier, nodes used exclusively) plus a paragraph on the
    hardware.
- So:
  - Keep the three facts as plain sentences.
  - Move hashes, run IDs and the run-record format to the README.
  - Put one sentence in "How to run": all tables and figures are generated from the recorded runs by scripts in the
    code package.
  - Replace Table 8 with a short hardware paragraph (see P8).
  - Table 2 either becomes an experiment overview in the grader's terms (what varies, grid sizes, core counts) or is
    removed. In either case the E-codes and the Atlas column go.
- Status: decided. **Whether Table 2 stays as an overview is for the user.**

**P4. Placeholders and draft markers, and the order of work.**
- Objects: "waiting for cluster data", "DRAFT-FOR-USER-REVIEW (…)", "To write once the cluster runs are in", "partial
  figure, still waiting…".
- Why they cannot simply be polished: the claim of each pending paragraph depends on its numbers. For example, the
  paragraph changes depending on whether pipelined CG overtakes classic CG at 288 cores.
- So:
  - Run the language pass now on sections whose numbers are final: 1, 2, 3, 5, and the parts of 8 up to 8.7.
  - Run it on 6, 7, 8.8-8.9, 9 and the Summary only after the runs are in.
  - Before submission, check that the PDF contains none of the marker strings.
- Status: decided.

**P5. The shared-node ("insurance") points in the figures.**
- What they are for: a fallback for the ≥256-core requirement if four whole nodes were not granted.
- Depends on: the grader trusting the measurement conditions. Nodes shared with other jobs, with ranks not bound to
  cores, give noisier and slower times.
- So:
  - If the four-node runs arrive, drop these points.
  - If they are the only ≥256-core data, keep them. Say once, in the text at the first scaling figure and in plain words,
    what differs: 8 nodes × 32 cores, nodes shared with other jobs, ranks not bound to cores. Say also why this can
    inflate the times.
- Status: the data and the user settle this.

**P6. Figures and captions.**
- Exemplars:
  - Chen's captions: "On the left, we plot the strong scaling ... for a fixed problem size of 163842 particles. On the
    right hand side, we plot the parallel efficiency. For these tests, we are using θ = 0.7 and d = 6."
  - UMBC's captions name what is tabulated.
  - Every exemplar that explains a data split or a node draws it: RPI Figs. 1, 4 and 5 (rows per rank), Chen Figs. 1 and
    3, UMBC Fig. 1.1, REU Fig. 2.1.
- Why it works: the caption tells the reader how to read the figure, and the text makes the claim, which the reader can
  then check against the figure.
- Here:
  - The captions repeat result numbers, sometimes as slots, and carry machinery.
  - No schematic exists, although two arguments rest on geometry: the halo size per split (Table 1) and the two sockets
    per node (Section 6).
- So:
  - A caption states what is plotted, the axes, the problem and variant, and the reading key (the dotted line is
    ideal). The results go in the text.
  - Consider two schematics: the three splits with their halo faces, and a Vanda node with two sockets, each with its
    own memory. These add no claims but are extra work.
  - Check every axis for time, size or core count is logarithmic (for example the time axis of Fig. 7).
- Status: captions decided. **The schematics are for the user.**

**P7. Default element: "Length roughly unchanged."**
- Depends on: there being a page limit or a known reading time. Neither is given.
- Here: the exemplars run 11-25 body pages. Removing machinery shortens the report, and writing out the reasoning
  lengthens it a little.
- So:
  - Length is not a target. Every paragraph must serve a grading row, or a claim that a row needs.
  - The graph part (about 8 of 23 body pages) covers the real-data row and the sparsity comment. It should open with one
    paragraph saying why it is there: real data with conclusions about the data, and an irregular communication pattern
    that contrasts with the grid.
- Status: decided. **Whether to shorten the graph part is for the user.**

**P8. Describe the hardware before the results that depend on it.**
- Exemplars: UMBC and the REU report draw the two-CPU node with its memory channels early. Their later explanations,
  such as "one CPU fills out all its cores" and "competition for the 6 memory channels", then read as consequences.
- Here: the report's two central explanations depend on the node.
  - Efficiency is lost inside the node because memory bandwidth saturates.
  - The 18→36 core flattening happens because ranks fill one socket first.
  - Yet the sockets first appear in Section 6, as "a surprise".
- So:
  - The hardware section states, before any result: two sockets × 36 cores per node, memory attached to each socket,
    the network, the GPU model, and the compiler and MPI versions in one sentence. Each item must be a fact from the run
    records. Add no specifications that the material does not contain.
  - The results then refer back to it.
- Status: decided.

---

## Part D. The language pass

**L1. Default element: "The fix is sentence-level, section by section."**
- Why it seemed right: the user named four sentence faults.
- Where it fails:
  - Most "needs prior context" faults come from objects in the text (the insurance run, the calibration, the program
    file). Rewording a sentence cannot fix them. Only removing the object, or explaining it once, can.
  - Most "not first-principled" faults are at paragraph level: a claim without its cause.
- So: three passes, in order.
  1. Placement: P3-P5.
  2. Paragraph logic: L2.
  3. Sentence rules: L3-L8.
- Each pass works in the `.tex`, editing prose around the `\val{}` macros and never retyping a number. "By hand" means
  paragraph by paragraph with judgement, with no find-and-replace except for checked term renames.
- Status: decided. **Only the user can say whether "by hand" means the students will do it themselves.**

**L2. Paragraph shape.**
- Exemplar: the UMBC paragraph on parallel CG builds one chain, and each step follows from the previous by a stated
  connective.
  - Each vector is split into blocks.
  - An inner product is a local part plus a reduce over all processes.
  - So communication grows with the process count and eventually dominates.
  - By contrast, the vector updates need no communication but need the scalars everywhere, which is why an Allreduce is
    used.
  - The product needs the neighbours' boundary values, which takes point-to-point messages.
  - Only a few components need remote data, so the interior can be computed while the messages travel.
- Exemplar: results paragraphs (UMBC, REU, Chen) go observation with numbers → "This is due to …" → consequence.
- Depends on: a reader who accepts the ownership, operations and cost frame. Lecture 8 and Lecture 12 show that he does.
- Here: the frame holds, with one twist that the report must address explicitly. His own CG slide treats Ap as the
  costly O(N²) step. In this report Ap is a cheap matrix-free stencil. The report must therefore say why the reductions,
  and not the product, limit scaling.
- So: every paragraph is a claim plus its chain.
  1. What was measured, and where it is shown.
  2. The observation, with the one or two numbers it needs and their reference.
  3. The mechanism, stated as who owns what, what must be communicated, and which term of the cost model grows.
  4. The consequence for the design, or for the next section.
- If the mechanism is not in the report: derive it from facts that are, or present it as a hypothesis with the test that
  would settle it.
- Status: **ready to test.** Sample below.

> **Sample: current text (Section 6, draft "mpi-node"; numbers as generated):**
> "The efficiency is lost inside the node, not between nodes. With classic CG the 3D run keeps an efficiency of 0.26 on
> one node and 0.26 on two: going from 72 to 144 cores halves the time (a factor 1.96), while the 72 cores of one node
> give a speedup of only 19.0 over one core (2D: 17.8). Each iteration has to stream the same vectors through memory
> whatever the core count (Section 2.5), so the node's memory bandwidth, not its core count, sets the speedup. The
> calibration derives from the one-core and full-node runs a bandwidth of 26.3 GB/s for one core and 438 GB/s for a whole
> Intel Xeon Platinum 8452Y node, 16.6 times as much. Because the calibration comes from these same runs, that ratio
> describes the speedup rather than confirming it independently; the independent evidence is the shape of the curve."
>
> **Sample: after the pass (same numbers, same claims):**
> "Almost all of the efficiency is lost inside the first node. With classic CG on the 3D grid, the 72 cores of one node
> run 19.0 times as fast as one core (17.8 in 2D), where perfect scaling would give 72, so the efficiency on one node is
> 0.26. Going from one node to two (72 to 144 cores) divides the time by 1.96, close to the ideal factor of 2, so the
> efficiency stays at 0.26. The memory model of Section 2.5 explains this. Every iteration of classic CG streams about
> 96 bytes per unknown through memory, whatever the number of cores. Once the cores of a node saturate its memory
> bandwidth, more cores on that node cannot make an iteration faster, while a second node brings its own memory and
> doubles the bandwidth. Dividing the bytes moved per iteration by the measured time **[check: is this how the
> 'calibration' was computed?]** gives 26.3 GB/s on one core and 438 GB/s on the whole node, a ratio of 16.6. This ratio
> is computed from the same runs, so it restates the speedup in units of bandwidth and does not confirm it
> independently. The independent evidence is the shape of the speedup curve inside the node, which follows from the two
> sockets described in Section 4."
>
> What changed:
> - The teaser topic sentence became the plain claim.
> - Each number now carries its reference (72 ideal, factor 2 ideal).
> - The undefined "calibration" is described, and the pass exposes that its method is not stated in the report. Only the
>   code or the user can supply it.
> - The semicolon became two sentences, each with its link.
> - The appeal to "Section 2.5" now states the fact it uses.
>
> The user should judge this against their own sense of "first-principled" (A1).

**L3. Default element: "Split every semicolon sentence into two."**
- Why it seemed right: one idea per sentence.
- Exemplars: UMBC, Heroux-Dongarra and REU use no semicolons in argument. Chen's prose with Jablonowski has none. Where
  Chen-Krasny use one, it joins a statement to its example. The relation between clauses is otherwise always stated with
  a connective.
- Depends on: the two clauses being independent. In the report they rarely are. Splitting leaves the relation unstated
  and produces two short sentences, which brings back faults 1 and 2.
- So: for each semicolon, name the relation (cause, consequence, contrast, elaboration, list) and write the connective.
  Split only when the clauses are separate points, and start the second sentence with a link back. No semicolons in
  prose.
  - Current: "It is parallelised with MPI across processes and with OpenMP threads (workers that share one process's
    memory) inside each process; the same loops can also run on a GPU through OpenMP offloading."
  - After: "We parallelise it with MPI across processes and with OpenMP threads inside each process, and the same loops
    also run on a GPU through OpenMP offload." The definition of a thread is dropped because it is his term (L5).
  - Current: "At the tolerances of the validation cases the two variants agree (V5); the difference appears only when a
    very small residual is asked for."
  - After: "The two variants agree at the tolerances used in the validation tests (V5) and differ only when a residual
    far below those tolerances is requested."
- Status: decided.

**L4. Default element: "Merge runs of very short sentences."**
- Exemplars: Chen's short sentences are signposts ("We now go into more detail."; "Some details need explanation.").
  Claims always come with their link.
- Here: the report's short sentences are of two kinds.
  - **Compressed steps** state a cause and its effect as separate facts. An example is in Section 2.3: "It costs in three
    ways. It carries 8 vectors instead of 5. It moves about 128 bytes per grid point per iteration instead of 96…"
  - **Aphorisms and teasers**: "A check that cannot fail proves nothing."; "That shape held a surprise."; "Real graphs
    come in fixed sizes."; "Only the operator changes: …". This is a recognisable generated-prose habit, and the grader
    says such habits are "very obvious".
- Why plain merging fails: merging into comma chains just moves the fault.
- So:
  - Join a compressed step to the claim it supports, with its connective. Example: "Pipelined CG carries 8 vectors
    instead of 5, so each iteration moves about 128 bytes per grid point instead of 96, and on a memory-bound problem an
    iteration therefore takes longer whenever there is no reduction latency to hide."
  - Replace each aphorism or teaser with the plain claim it gestures at.
  - Keep a short sentence only as a signpost where a section turns.
- Status: decided.

**L5. Default element: "Add a definition at the first use of each term."**
- Why it seemed right: his slide says "All non-standard terminology used in the report should be defined".
- Depends on: knowing what is *non-standard for him*.
  - His lectures already define: rank, communicator, point-to-point and collective, reduce/allreduce, blocking and
    non-blocking, RMA window, domain decomposition, stencil, halo, halo exchange, arithmetic intensity, latency,
    bandwidth, speedup, efficiency, strong and weak scaling, Amdahl and Gustafson, thread, race condition,
    `schedule(static)`, master construct, OpenMP offload (`target`, `teams distribute`, `map`), kernel, host and device,
    CUDA-aware MPI, floating-point non-associativity, and the CG iteration itself.
  - Defining these again (the report's "(an MPI process with its own memory)", "(the bytes per second a link can
    carry)") is padding. It reads as written for a novice and makes sentences heavy.
- So: sort every term into one of three classes.
  1. **His terms.** Use them bare, in his words. See the vocabulary table.
  2. **Non-standard technical terms.** Define each once, where it first matters, by describing the thing and then naming
     it in a main clause, not in a parenthesis. Use that one name everywhere afterwards. The list: matrix-free; ghost
     layer; slab, column and block splits; pipelined CG; recursive versus true residual; attainable accuracy;
     manufactured solution; observed order; socket and first touch; funneled thread level; graph Laplacian shift *a*;
     seed vertices; exclusive vertex; edge cut; load imbalance; breadth-first (Cuthill-McKee) order; neighbourhood
     collective.
  3. **Build-internal words.** Do not define them. Replace them with a plain description, or delete them. The list:
     program file, qualification, insurance run, run plan, run record, E-codes, "refuse", "planted bug", "the
     calibration", "the defaults", "the dataset ladder", "variants" (when the word means a build label).
- Status: decided. The term lists above are the working list.

**L6. Default element: "Keep every number and claim; add none."**
- Depends on: the numbers being generated (`\val{}`), so they cannot be retyped.
- Exemplars: prose carries the one or two numbers a claim needs, each with its comparison. Chen writes "efficiency falls
  to around 50% at 1024 ranks ... (runtime 7 seconds)". UMBC writes "a speedup of 76.01, less than the optimal speedup
  of 128". Tables carry the full sets.
- Here: the report's prose is number-dense, and many numbers stand without their reference. An example is "an
  efficiency of 0.26" with no "where perfect would be 1, i.e. 19 times on 72 cores".
- So:
  - Every number stays in the report, in a table or in prose.
  - Prose keeps the numbers its claim needs, and each gets its reference (ideal, baseline, or the other variant).
  - Drop prose repetitions of table values that carry no claim.
  - Always give units.
  - Never round by hand. If a coarser value is needed, add a macro.
  - Keep every claim.
  - A reasoning step may be added only if it uses facts already in the report. If it needs a new fact, flag it, as in
    the "calibration" in the L2 sample.
- Status: decided.

**L7. Conclusions, reasoning and hedges.**
- Exemplars:
  - Conclusions stand together with their cause: Chen's "saturates earlier primarily because the upward and downward
    passes are not parallelized", and UMBC's numbered conclusions with causes.
  - The RPI report shows the weak form: "Further [investigation] is needed".
- Here: the report hedges ("most likely", "A plausible reading", "probably"). Some of these hedges are honest, but they
  do not say what would settle the question.
- So:
  - Every conclusion sentence is followed, in the same paragraph, by its evidence and its mechanism.
  - Every hedge says what was not measured and what would settle it. Example: "we did not rerun with ranks spread over
    both sockets".
  - The Discussion restates the conclusions per grading row, in plain words, with pointers to the tables. It follows
    the grader's own list: how each part was parallelised, with which technique, and which part communicates most.
- Status: decided.

**L8. Self-contained references, register, and the second reader.**
- References: replace bare pointers ("(Section 2.5)") with the fact used plus the pointer.
- Register: "we", active voice, plain words. Keep British spelling consistently; MPI names stay as they are. Avoid both
  the RPI kind of inflated word and the report's own tics ("the trade", "refuse", "held a surprise").
- Second reader: after each section is revised, one student reads it aloud and marks any sentence they could not
  explain without looking elsewhere. That marked sentence is the next fix. The test serves the students, and it is the
  closest available proxy for a grader reading without context.
- Status: ready to test.

**L9. How to apply the pass by hand (procedure).**
1. Work in this section order: title block and Summary are last (P2). Then sections 1 → 2 → 3, then the hardware
   section, then 5 → 8.1-8.7. Sections 6, 7, 8.8-8.9 and 9 wait until their data are in.
2. For each paragraph:
   1. Write down its claim in one line.
   2. List the facts and `\val{}` numbers it uses.
   3. Sort its terms into the three classes of L5.
   4. Rewrite it as the chain of L2, applying L3, L4 and L6.
   5. Compare with the old version: no claim lost, and every `\val{}` either still present or present in a table.
3. After each section:
   - diff the set of `\val{}` keys used (none may disappear unless it is in a table);
   - search for the marker strings, "Made by", hashes and E-codes;
   - apply the read-aloud test (L8).

---

## Part E. Their vocabulary against ours

| Thing | Report says | Grader says (where) | Which wins |
|---|---|---|---|
| Combining partial dot products | "global sum", "sum", "global reduction" | "Reductions", "MPI_Reduce ... variant MPI_Allreduce" (L8); "reduction" (L12) | His: "reduction (MPI_Allreduce)", one word throughout |
| Values a rank needs from neighbours | "halo", "ghost cells", "ghost layer", "ghosts" | "each rank needs a halo around its computational domain"; "Halo exchanges" (L12) | His "halo" and "halo exchange"; "ghost layer" only once, as the storage that receives the halo |
| Splitting the grid | "split", "decomposition", "slabs/columns/blocks" | "Domain decomposition" (L12) | His for the concept; "1D/2D/3D decomposition (slabs, columns, blocks)" defined once |
| Speedup baseline | T(1)/T(P), "one-core run of the same variant" | Ts/Tp(n), Ts/(nTp(n)), Ts = "a serial program" (L7) | Keep P. State in his terms that Ts is the one-rank run of the same program, and say whether that differs from a serial build |
| Symbols | n = grid points per direction, N = unknowns, P = ranks | N = problem size, n = processes (L7) | Keep the report's symbols (renaming is costly). Never use n for processes, and spell out "grid points per direction n" on axes and at first use in each section |
| Overlapped exchange | "overlapped halo", "overlap" | MPI_Isend "returns immediately" (L8); UMBC: "interleaving calculations and communications" | "non-blocking halo exchange overlapped with the interior stencil", defined once, then "non-blocking exchange" |
| Pipelined CG | used as a name | not in his lectures | Define with his terms: one non-blocking reduction (MPI_Iallreduce) per iteration, overlapped with the next matrix-vector product |
| Threads and MPI | "master thread calls MPI", MPI_THREAD_FUNNELED | "master construct ... (perhaps an MPI communication command?)" (L9) | Describe in his wording, then name the thread level |
| Rank × thread layouts | "layouts", "1×72 … 72×1" | "1 MPI rank per node ..., or 2 MPI ranks and 36 OpenMP threads per rank, or 4 and 18" (L9) | His framing. Section 7 answers his four L9 questions in his order |
| Halo implementation choice | MPI_Sendrecv / MPI_Isend | "Implementation? MPI send/receive, windows" (L12); his own papers use RMA | One sentence on why windows were not used. **Content gap, user to settle** |
| Test problem | "manufactured solution" | "If you are working with synthetic data, please explain how you generated the data" (L12) | Open with "synthetic test problem with a known exact solution", then name the method |
| Correctness checks | "validation cases", "refuses", "planted bug" | "validation tests" (L12) | His: "validation tests". "the tests fail on two deliberately broken versions of the halo exchange" |
| Real data | "Stanford Network Analysis Project (SNAP)" | "Stanford Large Network Dataset Collection" (L7) | Name it once as he does, then "SNAP" |
| GPU path | "offload build", "GPU path" | "OpenMP GPU Offload" (L9) | His |
| Memory limit | "memory-bound", "memory traffic" | "arithmetic intensity" (L12); "Communication between a CPU and Memory ... really slow" (L7) | Keep "memory-bound", tied once to arithmetic intensity (the report already does this) |

---

## Part F. Dropped (changes nothing), and what only the user can settle

**Dropped:**
- Register "we": the report already uses it, as all the exemplars do.
- Tables that repeat figures: the genre accepts this. UMBC says outright that "These plots do not provide new results".
- Citing the lectures: keep it, once per concept.
- British versus American spelling: the report is already consistent.

**Only the user can settle:**
1. Whether A1 ("first-principled" = a visible chain from ownership, operations and cost) matches what they meant. Test
   it on the L2 sample.
2. Whether "by hand" means the students do the pass themselves or the agent does it paragraph by paragraph (L1).
3. Whether Table 2 survives as an experiment overview (P3).
4. Whether to add the two schematics (P6).
5. What to do with the shared-node points if the four-node runs arrive or do not (P5).
6. Whether to shorten the graph part (P7).
7. Whether to add one sentence on why MPI windows were not used (Part E).
8. How the "calibration" bandwidth was computed (L2 sample).
9. Whether the AI declaration should say that the students revised the text by hand.

---

## Checks on the record (run by the invoking session, 13 Nov)
- **Provenance:**
  - Every assumption in ASSUMPTIONS.md traces to a human source in 02_HUMAN_SOURCES.md (the grader's slides and two
    papers, the Sandia, UMBC and RPI reports), to the user, or to a labelled default. None traces to an excluded
    AI-generated source.
  - Steps 2-3 were drilled by a fresh agent that carried only the brief and 01_FRAME.
  - Sources: one canonical (Heroux-Dongarra) and seven task-specific.
- **Changed-decision test:** each of the 8 assumptions names the decision it changes. Together they move the pass from the
  default (sentence surgery) to a three-step pass: machinery out, then paragraph chains, then sentence rules.
- **Independent drill:**
  - Method: a second fresh agent had only 01_FRAME, the sources, the slides and the report, and named five deciding
    assumptions. It shares the model but not the context.
  - Agreement: the build words are the "non-standard terms"; the missing connective is the shared cause of semicolons and
    short sentences; "first-principled" means derived from premises on the page, with the node structure added before the
    results.
  - Gaps it found, now added as assumptions 7 and 8: results are stated two or three times (generated paragraph plus
    drafted interpretation plus caption); and much of the machine text comes from the generator, so the generator must be
    edited and open claims scoped.
  - Raised only by us: the term classes taken from the lecture list (5) and numbers with references (6). Both are sourced
    from the slides and the UMBC/Chen papers.
- **Level of transfer:** each assumption carries a reason checked against this reader, for example "his slide says AI use is
  obvious" or "he taught these terms". None only adds or renames a component.
- **Readability of the record:** ASSUMPTIONS.md was re-read as the user would, without the drill files. Each assumption
  stands alone.
- **Status:** checked; assumptions 1 and the "by hand" question settled by the user. Assumptions 7-8 and the defaults in
  04_QUESTIONS.md are not yet seen by the user.
- **What the checks cannot show:** whether the grader in fact reads this way. Only the grade, or a human reader, can show
  that.
