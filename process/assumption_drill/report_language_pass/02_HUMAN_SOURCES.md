# Step 2: human sources

Eight sources, read for how expert readers of parallel-solver reports read, decide and judge, and for what makes a
technical paragraph understandable to them without context. The two Chen papers and the slides are the grader's own
writing. The other five are reports of the same kind as ours, written for a similar reader. Downloaded files and their
text versions are in `sources/` and `sources/txt/`.

## The reader's own writing

**1. Anthony Chen, DSA5208 Lectures 7-12 (slides), NUS, AY2026/27.**
- Location: `course_materials/slides/Lecture_7.pdf` ... `Lecture_12.pdf` (Lecture 13 is joint with Zhenning Cai and was
  also read).
- Kind: Beamer lecture slides by the grader. They include the Project 3 slides (deliverables, grading split, "More
  Comments", "AI Usage").
- Why trusted: the title page names Chen. The slides are the course's own teaching material and were delivered in class.
  The Canvas announcements in `course_materials/canvas/` are signed "Anthony" in the same plain register.
- How read: in full. I extracted the text with `pdftotext -layout` and removed repeated overlay frames, so each slide was
  read once at its fullest build.
- What it shows: what he treats as known, and his words for it. These include rank, communicator, point-to-point and
  collective communication, reduce/allreduce, blocking and non-blocking sends, RMA windows, domain decomposition,
  stencil, halo and halo exchange, arithmetic intensity, the cost model (flops + volume/bandwidth + calls × latency),
  speedup Ts/Tp(n) and efficiency Ts/(nTp(n)), strong and weak scaling, OpenMP offload, and floating-point
  non-associativity.
  - Lecture 8 poses CG itself as a worked question. It asks which operation costs most (he writes "computing Ap is
    O(N^2)", i.e. he thinks of a dense product) and whether each rank should own all of A, x, r and p or only a portion.
  - Lecture 9 asks four questions for MPI+OpenMP: what goes across ranks and what across threads, how ranks and threads
    synchronise, how threads interact with MPI windows, and whether 1×72, 2×36 or 4×18 per node is fastest.
  - On the slides he defines a term in one plain sentence and then lists its consequences.
  - Note: `INSTRUCTOR_GUIDANCE_P3.md` and `ASSIGNMENT_BRIEF.md` are summaries compiled during the build. I checked the
    quotations in `01_FRAME.md` against the Lecture 12 slide text, and I did not use the summaries for form.

**2. Anthony Chen and Christiane Jablonowski, "Fast Summation on the Sphere with Applications to the Barotropic Vorticity
Equation", arXiv:2401.07361 (Jan 2024), University of Michigan.**
- Location: https://arxiv.org/abs/2401.07361, saved as `sources/chen_jablonowski_2024_fast_summation_sphere.pdf`.
- Kind: a research paper by the grader as first author, submitted to J. Comput. Phys. It has serial scaling, an MPI
  strong-scaling and efficiency figure, and validation against exact solutions.
- Why trusted: it has named authors and an affiliation, it is a journal submission on arXiv, and it was written before
  the period when generated text became common. Its topic matches his stated research area: fast algorithms for
  atmospheric models.
- How read: in full (pdftotext, 27 pages, mostly figures).
- What it shows:
  - His prose sentences are plain, declarative and of medium length, in the "we" voice, with no semicolons. He defines a
    term in a main clause ("θ is known in the literature as the multipole acceptance criteria"; "We refer to x_i as the
    target particle").
  - The parallel result takes one paragraph: setup, one observation, one cause. ("good scaling ... up until 64
    processors, at which point the performance plateaus, as the gains from additional parallelism are outweighed by the
    increases in communication".)
  - His captions say what is plotted and with which parameters. They do not state the result.
  - He separates the error sources and says which one dominates.

**3. Anthony Chen and Robert Krasny, "A Cubed Sphere Fast Multipole Method", arXiv:2508.13550 (Aug 2025), University of
Michigan.**
- Location: https://arxiv.org/abs/2508.13550, saved as `sources/chen_krasny_2025_cubed_sphere_fmm.pdf`.
- Kind: a research paper by the grader and his advisor, submitted to a SIAM journal. It has serial runtime against N,
  runtime against error, and a parallel runtime study with MPI and remote memory access.
- Why trusted: it has named authors and a journal submission with funding acknowledgements. It is post-2023, but it is
  admitted because it is the grader's own writing.
- How read: in full (pdftotext, 25 pages).
- What it shows:
  - Every symbol and acronym is defined where it first appears, and the paper gives a roadmap paragraph.
  - The parallel section states what is parallelised and how, then the efficiency and the time at the point where it
    falls to about 50%, each with its rank count. It names the single cause of early saturation: the upward and
    downward passes are not parallelised.
  - Each caption is a compact list of what was run.
  - Semicolons are rare, and they join a statement to an example.

## Exemplars of the genre

**4. Michael A. Heroux and Jack Dongarra, "Toward a New Metric for Ranking High Performance Computing Systems", Sandia
Report SAND2013-4744, June 2013.**
- Location: https://www.osti.gov/servlets/purl/1089988, saved as
  `sources/heroux_dongarra_2013_new_metric_SAND2013-4744.pdf`. The search hit was labelled as the HPCG specification, but
  the file is this companion report.
- Kind: a laboratory technical report proposing the HPCG benchmark (CG on a 3D stencil, written with MPI and OpenMP),
  with an appendix primer on parallel CG. This is the one canonical item in the set.
- Why trusted: it has named authors, it is a Sandia report number released through OSTI, and it was the basis of the
  HPCG benchmark list.
- How read: in full (19 pages).
- What it shows: how two experts explain CG's communication to other experts.
  - The primer lists the per-iteration operations (one product, three vector updates, two inner products). For each
    communication pattern it then gives what each process holds, what it needs from others, and why it must wait ("this
    computation is synchronous, meaning that an MPI process must wait for the final value α to arrive before
    proceeding").
  - It ends with the consequence for scaling: synchronous all-reduce "can become the single biggest impediment to
    scalability".
  - It uses numbered points with a bold head and full sentences, and no semicolons in its argument.

**5. Jinglong Sun, Ehsan Shakeri and Matthias K. Gobbert, "Strong Scalability Studies for the 2-D and 3-D Poisson
Equations on the Taki 2018 Cluster", UMBC HPCF Technical Report HPCF-2020-1.**
- Location: https://hpcf-files.umbc.edu/research/papers/PoissonHPCF20201.pdf, saved as
  `sources/umbc_2020_poisson_blocking_nonblocking.pdf`.
- Kind: a technical report by students and a faculty mentor. It covers matrix-free CG for the 2D and 3D Poisson equation
  with MPI, comparing blocking and non-blocking halo exchange. This is our problem with one of our design choices.
- Why trusted: it has named authors and is part of a long-running series of facility reports written by students under
  a numerical analyst. It was written before 2023 and is used to set cluster usage rules.
- How read: in full. The repeated HH:MM:SS table cells were skimmed. The 3D half repeats the 2D text almost word for word.
- What it shows:
  - Numbered conclusions lead the introduction. Each pairs an observation with its hardware cause (runtime stops halving
    at 16-32 processes per node because more processes compete for the 6 memory channels per CPU). A node schematic
    supports this.
  - One long paragraph derives every communication in parallel CG from how the vectors are split across processes.
  - Reading guides tell the reader how to read each table ("Reading along the first column ... Reading along each row").
  - The convergence study (error falling by 4 per halving of h) comes before any timing.
  - It shows a weakness too: the boilerplate is copied between sections.

**6. Carlos Barajas and Matthias K. Gobbert, "Strong and Weak Scalability Studies for the 2-D Poisson Equation on the
Taki 2018 Cluster", UMBC HPCF Technical Report HPCF-2019-1.**
- Location: https://userpages.umbc.edu/~gobbert/papers/PoissonHPCF20191.pdf, saved as
  `sources/umbc_barajas_gobbert_2019_poisson_taki.pdf`.
- Kind: a technical report by a student and a faculty member. It covers the same solver with strong and weak scaling,
  speedup and efficiency tables and plots, MPI+OpenMP layouts (processes × threads per node), compiler comparisons and a
  historical comparison across clusters.
- Why trusted: as for item 5. It was written before 2023.
- How read: in full. Table cells were skimmed.
- What it shows:
  - It defines speedup and efficiency in prose before using them.
  - Each number comes with its reference ("a speedup of 76.01, less than the optimal speedup of 128, for a still
    respectable efficiency of 59.38%").
  - It explains better-than-ideal efficiency by cache effects.
  - It treats the ranks × threads study as weak scaling within a node and strong scaling across nodes. This is the same
    study as our Section 7.

**7. Sushant Kumar, Narendra Nanal and Vignesh Vittal-Srinivasaragavan, "Performance Benchmark of A Parallel Sparse Linear
System Solver Using Conjugate Gradient", course project report, Parallel Computing, Spring 2020, Rensselaer
Polytechnic Institute.**
- Location: https://vickyragav95.github.io/assets/documents/PC_report.pdf, saved as
  `sources/student_PC_report_spring2020.pdf`.
- Kind: a graded HPC course project report on CG with MPI and MPI+CUDA. This is our genre exactly, for a course
  instructor.
- Why trusted: it has three named students with university emails, a course and term header, broken citation marks
  ("[? ]") and typos of the kind people make. It predates 2023 and is posted on an author's personal page.
- How read: in full. I read it with plain pdftotext, because the two-column layout scrambles under `-layout`.
- What it shows what a course report does that works and what an expert grader would see as weak.
  - What works: each kernel (matrix-vector product, vector update, dot product) is explained by what each rank holds,
    computes and sends, with a small picture of the split. Profiling tables attribute the time, and the scaling loss is
    traced to synchronisation.
  - What is weak: weak scaling is misdefined, inflated words appear ("putative", "variegated", "impinges upon the
    efficacy"), and results are left at "needs further investigation".

**8. Adam Cunningham, Gerald Payton, Jack Slettebak, Jordi Wolfson-Pou et al. (mentor Matthias K. Gobbert), "Pushing the
Limits of the Maya Cluster", UMBC REU Site Technical Report HPCF-2014-14.**
- Location: https://userpages.umbc.edu/~gobbert/papers/REU2014Team4.pdf, saved as `sources/umbc_REU2014Team4.pdf`.
- Kind: a report by an undergraduate research team on CG for 2D Poisson with MPI (blocking and non-blocking), CUDA, and
  MPI+CUDA, plus HPCG runs with MPI+OpenMP. It is MPI+X with a GPU, as in our report.
- Why trusted: it has named students, graduate assistants, a faculty mentor and clients. It is a 2014 report in the HPCF
  series.
- How read: in full. Table cells were skimmed.
- What it shows:
  - It explains a socket effect in the same shape as our "18 to 36 cores" result: "processes are not split up onto two
    CPUs but instead one CPU fills out all its cores". The node architecture was described and drawn earlier in the
    report, so the explanation follows from it.
  - It explains why MPI+GPU lost to the CPU nodes by counting the transfers per exchange (two host-device and two
    node-to-node).
  - It defines terms in plain words where they are used (deadlock, benchmark, GFLOP/s).

## Seen and not used
- `github.com/davidzuo023/dsa5208-project3` and `dsa5208-cg-poisson`: another group's submission for this same course
  and term. It is likely AI-assisted, and it is not appropriate to read a classmate's live submission. Not opened.
- `github.com/Anuttaman216/HPC_FInal_Lab_Project`: undated, with no named authors. Not opened.
- Ghysels and Vanroose (2014), the pipelined-CG paper cited by the report: no open copy was found, so it was not used.
