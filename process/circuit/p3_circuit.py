"""DSA5208 Project 3 (MPI+X parallelization): the forward circuit for the build.

Same standing as Project 2's circuit (prior_circuits/project2_rainfall_spark/p2_circuit.py): this is a circuit for
work that has not run, so every finding is a proposal (circuit_delegation/ASSUMPTIONS.md). Every line an agent will
meet at a decision is quoted from where it already exists:
- the Canvas brief and announcements;
- Anthony Chen's Lectures 7-12;
- comp_res.pdf;
- this Mac's shell;
- your messages.
Lines a checker is designed to print are Known.PREDICTED.

What it is for (circuit_use/ASSUMPTIONS.md, 4): it gets force only through what the environment prints or refuses.
Its outputs are:
(a) the checks the build must print, and which of them refuse the next step;
(b) where the child stops for you;
(c) which gates actually change the move (load), so effort goes there.

What changed from Project 2 (the reason transferred, not the mechanism):
- P2 froze its evaluation plan by hash to stop test-year leakage. Project 3 has no held-out data. The risks a plan
  guards against here are a graded cell left empty (256 cores, strong and weak, serial sizes, GPU) and unbudgeted
  reruns on a limited, unreliable Vanda. So the plan check prints coverage and core-hours, not a hash.
- P2's checks were qualified only on broken inputs (casebook C12). Here the validation check must also pass the
  correct build before it may gate anything.

Run: python3 circuit/p3_circuit.py   (uses the package at ~/Desktop/connector/components/circuits/src)
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Desktop/connector/components/circuits/src"))

from reasoning_circuits import compute, load  # noqa: E402
from reasoning_circuits.model import (  # noqa: E402
    Clear, Decision, Effect, Fix, Gate, Hop, Judge, Known, Move, MoveKind, Owner, OwnerKind, Quote, Trigger,
)

BRIEF = "Canvas brief, assignment 279026 (course_materials/ASSIGNMENT_BRIEF.md)"
ANN = "Canvas announcement 'Project 3 Extension', Anthony Chen, updated 10 Nov 2026"
L7 = "Lecture_7.pdf, 'Project 3' slides (Anthony Chen)"
L8 = "Lecture_8.pdf, 'HPC Resources' slides (Anthony Chen)"
L9 = "Lecture_9.pdf, MPI + OpenMP slide (Anthony Chen)"
L11 = "Lecture_11.pdf, 'More on Execution Spaces' (Anthony Chen)"
L12 = "Lecture_12.pdf, 'Project 3' slides (Anthony Chen)"
L12C = "Lecture_12.pdf, 'Avoiding Communication' (Anthony Chen)"
COMP = "course_materials/comp_res.pdf, section 2"
SESSION = "parent session 2026-11-11"

# --------------------------------------------------------------------------- owners

COURSE = Owner("the brief and grader (Anthony Chen)", OwnerKind.EXTERNAL)
HPC = Owner("NUS HPC (Atlas, Vanda)", OwnerKind.EXTERNAL)
YOU = Owner("you, in this session", OwnerKind.YOU_NOW)
YOU_EARLIER = Owner("you, Projects 1-2 and your circuit drills (settled earlier)", OwnerKind.YOU_EARLIER)
SKILL = Owner("the build skill the child runs", OwnerKind.SKILL)
AGENT = Owner("the agent", OwnerKind.AGENT)

# --------------------------------------------------------------------------- quoted lines

q_mpix = Quote("This project focuses on a MPI+{OpenMP, CUDA, Kokkos, *} parallelization of an algorithm of your choice.",
               BRIEF, "brief")
q_not_ep = Quote("the parallelization of the algorithm should present some challenges (i.e., not embarrassingly "
                 "parallel).", BRIEF, "brief")
q_choice = Quote("you should pick an algorithm and implement it in serial and in parallel", BRIEF, "brief")
q_runtime = Quote("Runtime figures from Atlas or Vanda", BRIEF, "brief")
q_validation = Quote("A validation that the parallel algorithm works correctly", BRIEF, "brief")
q_report = Quote("An introduction to the algorithm / A discussion of the design decisions made in the parallelization / "
                 "A discussion of the parallel scaling and efficiency of your parallelization / A validation that the "
                 "parallel algorithm works correctly / Runtime figures from Atlas or Vanda / If working with real data, "
                 "conclusions about the data / Explanation of any AI usage", BRIEF, "brief")
q_ai = Quote("Explanation of any AI usage", BRIEF, "brief")
q_code = Quote("To submit your code, you can either include it directly in the pdf, or you can include a link to a "
               "public Github repository.", BRIEF, "brief")
q_group = Quote("If you do, the report should include everyone's names and student ID numbers.", BRIEF, "brief")
q_progress = Quote("you may optionally email me a progress report before 30 October, and I will provide direction if "
                   "necessary.", BRIEF, "brief")
q_due = Quote("I have extended the deadline for project 3 submissions to November 17th.", ANN, "announcement")

g_algo = Quote("5 points for explaining the algorithm being parallelized", L12, "lecture")
g_serial = Quote("5 points for performing a runtime scaling analysis for the serial algorithm with varying problem size. "
                 "For sparse matrix problems, both the dimension of the matrix and the number of nonzero entries should "
                 "vary. For graph algorithms, the number of edges and the number of vertices should vary.", L12, "lecture")
g_mpi = Quote("10 points for analyzing the MPI runtime performance, scaling to at least 256 CPU cores. Both strong and "
              "weak scaling should be tested. Please present parallel speedup and parallel efficiency numbers. Do also "
              "explain the impact of communication on the runtime.", L12, "lecture")
g_x = Quote("10 points for analyzing the MPI+X parallelization. If you choose X=OpenMP, then you also have to test on at "
            "least one GPU.", L12, "lecture")
g_disc = Quote("5 points for the overall discussion. ... You should also explain how you chose to parallelize the "
               "problem, how different parts of the problem were parallelized using different techniques, which parts "
               "need the most communication, etc...", L12, "lecture")
c_terms = Quote("All non-standard terminology used in the report should be defined", L12, "lecture")
c_poisson = Quote("If you are solving the Poisson equation, please implement a solver for both the 2D and 3D problems",
                  L12, "lecture")
c_graph = Quote("If you are working with a graph problem, please make sure to discuss the impact of graph sparsity",
                L12, "lecture")
c_synth = Quote("Working with synthetic data is an easy way to perform the weak scaling tests", L12, "lecture")
c_valid = Quote("Please explain your validation tests", L12, "lecture")
c_100 = Quote("For the validation tests, if you have 100+ tests, why?", L12, "lecture")
c_ai = Quote("If you use AI, you have to declare it. It is very obvious when you use AI, even if you don't declare it.",
             L12, "lecture")
c_logs = Quote("Include your code in your final submission. Do not include your log files or terminal output.", L12,
               "lecture")
c_axes = Quote("For plot axes that are time, problem size, or CPU count, these should be logarithmic.", L12, "lecture")
c_extend = Quote("If Vanda has more downtime, I will extend the deadline accordingly", L12, "lecture")
c_cuda_mpi = Quote("Vanda has support for CUDA aware MPI. ... module load nvhpc-hpcx-cuda12/26.1 ... The first one is "
                   "recommended.", L12, "lecture")
c_comm = Quote("The runtime of some code is the sum of three components: Number of floating point operations times time "
               "per floating point operation; Communication volume divided by bandwidth; Number of communication calls "
               "times the latency", L12C, "lecture")

l7_simple = Quote("The simpler of an algorithm you choose to implement, the more sophisticated the parallelization "
                  "should be", L7, "lecture")
l7_kmeans = Quote("Some data science algorithms you might consider: ... Clustering algorithms (K-means)", L7, "lecture")
l8_atlas = Quote("Atlas: CPU only, slow, unlimited use", L8, "lecture")
l8_vanda = Quote("Vanda: Mixed CPU and GPU, limited core-hour allocation", L8, "lecture")
l9_layout = Quote("On Vanda, each CPU node has 72 CPU cores. Is it better to only have 1 MPI rank per node and only use "
                  "OpenMP for intra-node parallelism, or is faster to have 2 MPI ranks and 36 OpenMP threads per rank, "
                  "or 4 and 18, or whatever?", L9, "lecture")
l11_backends = Quote("When you compile Kokkos, you specify which “backends” you want Kokkos to use. ... 1. Device "
                     "backends, including CUDA and HIP 2. Host parallel backends, including OpenMP and pthreads", L11,
                     "lecture")
q_login = Quote("Once your application is approved, verify your application by logging in to the server atlas8.nus.edu.sg "
                "and vanda.nus.edu.sg using your NUSNET ID and password. ... NUS VPN is required if you are off-campus.",
                COMP, "course handout")
q_vanda_down = Quote("Vanda Down AGAIN :-(", "Canvas discussion title, 5 Nov 2026", "a student")
q_atlas_nodes = Quote("64 compute nodes having 192GB memory and 24 cores each and 100Gbps interconnect",
                      "nusit.nus.edu.sg HPC newsletter 'Performance of the new Atlas8 cluster' (undated, read 2026-11-11)",
                      "NUS IT")
q_pdf_only = Quote("the Project 3 submission page only accepts PDF files and does not allow ZIP files to be uploaded.",
                   "Canvas discussion 'Unable to Upload ZIP File', 9 Nov 2026; no instructor reply by 11 Nov", "a student")

q_no_mpi = Quote("mpicc not found / mpirun not found; Apple M5, 10 cores, 16 GB", "this Mac, 2026-11-11", "shell")
q_no_login = Quote("grep -c 'atlas|vanda' ~/.ssh/known_hosts ~/.ssh/config -> 0, 0", "this Mac, 2026-11-11", "shell")

q_you_group = Quote("yes same group", SESSION, "you")
q_you_circuit = Quote("now develop the semantic circuit for project 3", SESSION, "you")
q_you_min = Quote("no, you have to shift your invariant, you have to take minimum input from me",
                  "DWA5208 session 2026-09-24 (Agent_Building_Knowledge records)", "you (Project 1)")
q_you_reruns = Quote("wow, these have been 5 reruns, isnt that too much ?", "Project_2 session 2026-10-17 #335",
                     "you (Project 2)")
q_you_nosubmit = Quote("dont submit, ill submit myselves", "Project_2 session 2026-10-17 #344", "you (Project 2)")
q_bind_rule = Quote("A check may become binding only after it has passed an accepted example.",
                    "connector/assumption_drill/circuit_use/ASSUMPTIONS.md, 5", "your circuit drill")
q_c12 = Quote("The qualification text omits the accepted case it says is required.",
              "prior_circuits/casebook_C12_P1_to_P2_transfer.txt", "your workflow analysis")
q_p1_authors = Quote("Kushagra Bhatnagar (A0351591A) · Pratyush Sinha (A0352482A)",
                     "prior_circuits/project2_rainfall_spark/project_README.md l.3", "Project 2 title")


def predicted(text: str, where: str) -> Quote:
    return Quote(text, where, "a checker the child will build", Known.PREDICTED)


q_runrec = predicted("RUN cluster=<atlas|vanda> job=<PBS_JOBID> nodes=<n> ranks=<r> threads=<t> gpus=<g> N=<size> "
                     "iters=<k> t_total=<s> t_halo=<s> t_reduce=<s> t_compute=<s> -> results/<cluster>/<job>.csv",
                     "src: the solver writes its own record; checks/run_record.py refuses a figure without one")
q_val = predicted("VALIDATE accepted build: max|u_par-u_ser|=<e> <= tol PASS, error vs exact solution falls as h^2 PASS; "
                  "planted halo bug: FAIL (refused). Timing runs allowed for binary sha256=<h>",
                  "checks/validate.py")
q_plan = predicted("PLAN cells: serial sizes <a>/<A>; strong to >=256 cores <b>/<B>; weak to >=256 cores <c>/<C>; "
                   "X layouts <d>/<D>; GPU runs <e>/<E>; core-hours <h> of <budget>",
                   "checks/run_plan.py")
q_req = predicted("REQUIREMENTS E1-E18 mapped to sections (circuit/CIRCUIT.md section 3); NUMBERS 0 hand-typed; "
                  "AXES 0 linear time/size/cores axes; PACKAGE 0 log files; AUTHORS 2; AI declaration present",
                  "checks/requirements_check.py")
q_terms = predicted("TERMS <n> flagged terms used, <n> with a definition sentence", "checks/requirements_check.py")

# =========================================================================== D1. Where it builds and runs

D1_LOCAL = Move(MoveKind.E, "install Open MPI, libomp and CMake on the Mac; develop and validate at <=10 ranks")
D1_HPC = Move(MoveKind.E, "build and run on Atlas/Vanda through PBS jobs")
D1_Q_ACCESS = Move(MoveKind.Q, "you: confirm Atlas/Vanda login works and set up key-based SSH the agent can use")
D1_F_MAC = Move(MoveKind.F, "report runtimes measured on the Mac")
D1_R = Move(MoveKind.R)
D1_DELIVERS = "a working build-and-run route, with every reported run recorded where it ran"

d1 = Decision(
    name="D1 where it builds and runs",
    where="before any code is written",
    status="forward; proposal",
    delivers=D1_DELIVERS,
    options=(D1_LOCAL, D1_HPC, D1_Q_ACCESS, D1_F_MAC, D1_R),
    judged=("every runtime figure comes from Atlas or Vanda", "the report describes the machine the numbers came from"),
    gates=(
        Gate("runtime figures from Atlas or Vanda", "every runtime figure comes from Atlas or Vanda", (COURSE,), D1_F_MAC,
             Trigger("always", Judge.TOOL),
             ((Hop("brief", q_runtime, Effect.CLOSES),), (Hop("grading", g_mpi, Effect.CLOSES),))),
        Gate("no MPI on this Mac", "every runtime figure comes from Atlas or Vanda", (AGENT,), D1_R,
             Trigger("mpicc missing", Judge.TOOL), ((Hop("shell", q_no_mpi, Effect.CLOSES),),), judges=D1_DELIVERS,
             cleared_by=(Clear(D1_LOCAL, Fix.FIXES, q_no_mpi), Clear(D1_HPC, Fix.FIXES, q_no_mpi))),
        Gate("HPC login unconfirmed", "every runtime figure comes from Atlas or Vanda", (YOU, HPC), D1_Q_ACCESS,
             Trigger("no Atlas/Vanda login has been seen from this Mac", Judge.YOU, now=None, basis=q_no_login),
             ((Hop("handout", q_login, Effect.REQUIRES), Hop("shell", q_no_login)),)),
        Gate("cluster jobs need your login", "every runtime figure comes from Atlas or Vanda", (YOU, HPC), D1_HPC,
             Trigger("the login is not confirmed", Judge.YOU, now=None, basis=q_no_login),
             ((Hop("handout", q_login, Effect.CLOSES),),)),
        Gate("run record written by the run", "the report describes the machine the numbers came from",
             (COURSE, YOU_EARLIER), D1_R,
             Trigger("every timed run", Judge.TOOL, rechecks=True, basis=q_runrec),
             ((Hop("brief", q_runtime, Effect.CLOSES), Hop("printed", q_runrec)),), judges=D1_DELIVERS, enforced=True,
             cleared_by=(Clear(D1_HPC, Fix.FIXES, q_runrec), Clear(D1_LOCAL, Fix.PROXY, q_runtime))),
        Gate("Atlas slow, Vanda limited and unreliable", "every runtime figure comes from Atlas or Vanda", (HPC,), None,
             Trigger("always", Judge.TOOL),
             ((Hop("lecture", l8_atlas), Hop("lecture", l8_vanda), Hop("canvas", q_vanda_down)),)),
    ),
)

# =========================================================================== D2. Which algorithm

D2_CG = Move(MoveKind.E, "conjugate gradient for the Poisson equation, 2D and 3D, matrix-free stencil")
D2_GRAPH = Move(MoveKind.E, "a graph algorithm (BFS or PageRank) on SNAP graphs")
D2_Q = Move(MoveKind.Q, "you: the group's algorithm, and whether a progress report already named one")
D2_R = Move(MoveKind.R)
D2_DELIVERS = "the chosen algorithm, implemented in serial"

d2_gates = (
    Gate("not embarrassingly parallel", "the parallelization presents real challenges", (COURSE,), D2_R,
         Trigger("until an algorithm is chosen and its serial version runs", Judge.TOOL),
         ((Hop("brief", q_not_ep, Effect.CLOSES),), (Hop("lecture", l7_simple),)), judges=D2_DELIVERS,
         cleared_by=(Clear(D2_CG, Fix.FIXES, q_not_ep), Clear(D2_GRAPH, Fix.FIXES, q_not_ep))),
    Gate("the algorithm is the group's choice", "the algorithm is one the group will defend", (YOU,), D2_Q,
         Trigger("neither you nor the group has named the algorithm in this session", Judge.YOU),
         ((Hop("brief", q_mpix, Effect.REQUIRES), Hop("brief", q_progress)), (Hop("you, P1", q_you_min),))),
    Gate("structure must vary in the serial runs", "the parallelization presents real challenges", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("grading", g_serial),),)),
    Gate("topic-specific asks", "the parallelization presents real challenges", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("comments", c_poisson), Hop("comments", c_graph)),)),
    Gate("synthetic data eases weak scaling", "the parallelization presents real challenges", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("comments", c_synth),),)),
    Gate("six days left", "the parallelization presents real challenges", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("announcement", q_due),),)),
)

d2 = Decision(
    name="D2 which algorithm",
    where="after D1's local toolchain works",
    status="forward; proposal",
    delivers=D2_DELIVERS,
    options=(D2_CG, D2_GRAPH, D2_Q, D2_R),
    judged=("the parallelization presents real challenges", "the algorithm is one the group will defend"),
    gates=d2_gates,
)

# D2' variant: you hand the choice to the agent, and the lecture's example list puts K-means in front of it.
# Inferred, not observed: listing K-means first stands for the agent taking the first familiar example.
D2_KMEANS = Move(MoveKind.E, "K-means from the lecture's example list")
# K-means fills the slot (an algorithm chosen, serial version runs), but whether it meets "not embarrassingly
# parallel" is the grader's reading, so it clears the gate only as a proxy. Leaving it out of cleared_by would let the
# encoding, not a gate, decide the variant (the first run of this file did exactly that).
_not_ep = d2_gates[0]
_not_ep_kmeans = replace(_not_ep, cleared_by=_not_ep.cleared_by + (Clear(D2_KMEANS, Fix.PROXY, l7_kmeans),))
d2_delegated = Decision(
    name="D2' which algorithm, choice handed to the agent, K-means in front",
    where=d2.where,
    status="forward; variant",
    delivers=D2_DELIVERS,
    options=(D2_KMEANS, D2_CG, D2_GRAPH, D2_R),
    judged=("the parallelization presents real challenges",),
    gates=(_not_ep_kmeans,) + tuple(g for g in d2_gates[1:] if g.name != "the algorithm is the group's choice") + (
        Gate("lecture lists K-means", "the parallelization presents real challenges", (COURSE,), D2_KMEANS,
             Trigger("always", Judge.TOOL), ((Hop("lecture", l7_kmeans, Effect.OPENS),),)),
        Gate("K-means read as embarrassingly parallel", "the parallelization presents real challenges", (COURSE,),
             D2_KMEANS,
             Trigger("the grader reads one small allreduce per iteration as embarrassingly parallel",
                     Judge.OTHER_PERSON, now=None, basis=q_not_ep),
             ((Hop("brief", q_not_ep, Effect.CLOSES), Hop("lecture", l7_simple)),)),
    ),
)

# =========================================================================== D3. Which X

D3_OMP_GPU = Move(MoveKind.E, "MPI+OpenMP threads on CPU nodes, the same kernels offloaded to one GPU with OpenMP "
                              "target (nvhpc on Vanda)")
D3_KOKKOS = Move(MoveKind.E, "MPI+Kokkos: OpenMP backend on CPU nodes, CUDA backend on GPU nodes")
D3_CUDA = Move(MoveKind.E, "MPI+CUDA with CUDA-aware MPI on Vanda GPU nodes")
D3_OMP_CPU = Move(MoveKind.F, "MPI+OpenMP on CPU nodes only")
D3_R = Move(MoveKind.R)
D3_DELIVERS = "the MPI+X implementation and its analysis"
q_xcells = predicted("X cells: ranks x threads per 72-core node {1x72, 2x36, 4x18, 8x9, 72x1} <n>/5; GPU runs <g>/<G>",
                     "checks/run_plan.py")

d3_gates = (
    Gate("X=OpenMP needs a GPU test", "the MPI+X analysis earns its 10 points", (COURSE,), D3_OMP_CPU,
         Trigger("always", Judge.TOOL), ((Hop("grading", g_x, Effect.CLOSES),),)),
    Gate("MPI+X analysis graded", "the MPI+X analysis earns its 10 points", (COURSE,), D3_R,
         Trigger("any X cell empty", Judge.TOOL, rechecks=True, basis=q_xcells),
         ((Hop("grading", g_x, Effect.CLOSES), Hop("printed", q_xcells)),), judges=D3_DELIVERS, enforced=True,
         cleared_by=(Clear(D3_OMP_GPU, Fix.FIXES, g_x), Clear(D3_KOKKOS, Fix.FIXES, g_x),
                     Clear(D3_CUDA, Fix.FIXES, g_x))),
    Gate("lecture frames the rank x thread question", "the MPI+X analysis earns its 10 points", (COURSE,), D3_OMP_GPU,
         Trigger("always", Judge.TOOL), ((Hop("lecture", l9_layout, Effect.OPENS),),)),
    Gate("nvhpc gives CUDA-aware MPI on Vanda", "the MPI+X analysis earns its 10 points", (COURSE,), D3_CUDA,
         Trigger("always", Judge.TOOL), ((Hop("lecture", c_cuda_mpi, Effect.OPENS),),)),
    Gate("Kokkos must be built for both backends", "the MPI+X analysis earns its 10 points", (HPC,), D3_KOKKOS,
         Trigger("Vanda has no Kokkos module built with OpenMP and CUDA", Judge.TOOL, now=None, basis=l11_backends),
         ((Hop("lecture", l11_backends, Effect.CLOSES),),)),
    Gate("GPU only on Vanda, and Vanda goes down", "the MPI+X analysis earns its 10 points", (HPC,), D3_CUDA,
         Trigger("Vanda is down when the X runs are due", Judge.TOOL, now=None, basis=q_vanda_down),
         ((Hop("lecture", l8_atlas), Hop("canvas", q_vanda_down, Effect.CLOSES)),)),
    Gate("no GPU on this Mac", "the MPI+X analysis earns its 10 points", (AGENT,), None,
         Trigger("always", Judge.TOOL), ((Hop("shell", q_no_mpi),),)),
)

d3 = Decision(
    name="D3 which X",
    where="after the serial version is validated",
    status="forward; proposal",
    delivers=D3_DELIVERS,
    options=(D3_OMP_GPU, D3_KOKKOS, D3_CUDA, D3_OMP_CPU, D3_R),
    judged=("the MPI+X analysis earns its 10 points",),
    gates=d3_gates,
)

# D3' variant: the same gates with CUDA listed first. Rule 4 offers the first open edit in listing order, so the
# order in d3 is the encoder's preference. This variant shows which gate, if any, overturns it.
d3_cuda_first = Decision(
    name="D3' which X, CUDA listed first",
    where=d3.where,
    status="forward; variant",
    delivers=D3_DELIVERS,
    options=(D3_CUDA, D3_KOKKOS, D3_OMP_GPU, D3_OMP_CPU, D3_R),
    judged=d3.judged,
    gates=d3_gates,
)

# =========================================================================== D4. Validation

D4_REF = Move(MoveKind.E, "a few named cases: parallel vs serial to rounding, error vs the exact solution falling as "
                          "h^2, and a planted halo bug the check must refuse")
D4_RESID = Move(MoveKind.F, "report 'validated' because the residual fell below tolerance")
D4_SWEEP = Move(MoveKind.F, "an automated sweep of 100+ cases")
D4_R = Move(MoveKind.R)
D4_DELIVERS = "the validation evidence, and the binary allowed to be timed"

d4 = Decision(
    name="D4 validation",
    where="before any timing run is accepted",
    status="forward; proposal",
    delivers=D4_DELIVERS,
    options=(D4_REF, D4_RESID, D4_SWEEP, D4_R),
    judged=("the parallel code computes the right answer", "the validation tests are explained and few"),
    gates=(
        Gate("validation in the report", "the parallel code computes the right answer", (COURSE,), D4_R,
             Trigger("no validation evidence yet", Judge.TOOL),
             ((Hop("brief", q_validation, Effect.CLOSES),), (Hop("comments", c_valid),)), judges=D4_DELIVERS,
             cleared_by=(Clear(D4_REF, Fix.FIXES, q_validation), Clear(D4_SWEEP, Fix.FIXES, q_validation),
                         Clear(D4_RESID, Fix.PROXY, q_validation))),
        Gate("check passes the correct build first", "the parallel code computes the right answer", (YOU_EARLIER,),
             D4_R,
             Trigger("before the check may gate a timing run", Judge.TOOL, rechecks=True, basis=q_val),
             ((Hop("your rule", q_bind_rule, Effect.CLOSES), Hop("P2 lesson", q_c12), Hop("printed", q_val)),),
             judges=D4_DELIVERS, enforced=True, cleared_by=(Clear(D4_REF, Fix.FIXES, q_val),)),
        Gate("100+ tests, why?", "the validation tests are explained and few", (COURSE,), D4_SWEEP,
             Trigger("always", Judge.TOOL), ((Hop("comments", c_100),),)),
    ),
)

# =========================================================================== D5. The runs

D5_VANDA = Move(MoveKind.E, "run the fixed plan on Vanda: serial sizes, strong and weak scaling to 288 cores "
                            "(4 nodes x 72), X layouts, one GPU node; 3 repeats; few batched PBS jobs")
D5_ATLAS = Move(MoveKind.F, "run the CPU scaling on Atlas (24-core nodes, slower); GPU run still on Vanda")
D5_WAIT = Move(MoveKind.W, "wait for Vanda; the instructor extends for downtime")
D5_ADHOC = Move(MoveKind.F, "submit runs one at a time and add what is missing")
D5_R = Move(MoveKind.R)
D5_DELIVERS = "the run records behind every scaling figure"

d5 = Decision(
    name="D5 the scaling runs",
    where="after D4 has allowed a binary to be timed",
    status="forward; proposal",
    delivers=D5_DELIVERS,
    options=(D5_VANDA, D5_ATLAS, D5_WAIT, D5_ADHOC, D5_R),
    judged=("MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and communication cost",
            "serial runtime is measured over problem size", "core-hours and reruns stay within budget"),
    gates=(
        Gate("MPI scaling cells", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and "
             "communication cost", (COURSE,), D5_R,
             Trigger("any graded cell in the plan is empty", Judge.TOOL, rechecks=True, basis=q_plan),
             ((Hop("grading", g_mpi, Effect.CLOSES), Hop("printed", q_plan)), (Hop("lecture", c_comm),)),
             judges=D5_DELIVERS, enforced=True,
             cleared_by=(Clear(D5_VANDA, Fix.FIXES, g_mpi), Clear(D5_ATLAS, Fix.FIXES, g_mpi),
                         Clear(D5_ADHOC, Fix.FIXES, g_mpi))),
        Gate("serial size sweep", "serial runtime is measured over problem size", (COURSE,), D5_R,
             Trigger("the serial sweep is incomplete", Judge.TOOL, rechecks=True, basis=q_plan),
             ((Hop("grading", g_serial, Effect.CLOSES), Hop("printed", q_plan)),), judges=D5_DELIVERS, enforced=True,
             cleared_by=(Clear(D5_VANDA, Fix.FIXES, g_serial), Clear(D5_ATLAS, Fix.FIXES, g_serial),
                         Clear(D5_ADHOC, Fix.FIXES, g_serial))),
        Gate("no unbudgeted reruns", "core-hours and reruns stay within budget", (HPC, YOU_EARLIER), D5_ADHOC,
             Trigger("always", Judge.TOOL),
             ((Hop("lecture", l8_vanda), Hop("you, P2", q_you_reruns, Effect.CLOSES)),)),
        Gate("Vanda down", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and "
             "communication cost", (HPC,), D5_VANDA,
             Trigger("Vanda is down when the runs are due", Judge.TOOL, now=None, basis=q_vanda_down),
             ((Hop("canvas", q_vanda_down, Effect.CLOSES),),)),
        Gate("Atlas refuses a 256-core job", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency "
             "and communication cost", (HPC,), D5_ATLAS,
             Trigger("the Atlas queues cap a job below 256 cores", Judge.TOOL, now=None, basis=q_atlas_nodes),
             ((Hop("NUS IT", q_atlas_nodes), Hop("lecture", l8_atlas, Effect.CLOSES)),)),
        Gate("extension for downtime", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and "
             "communication cost", (COURSE,), D5_WAIT,
             Trigger("always", Judge.TOOL), ((Hop("lecture", c_extend, Effect.OPENS),),)),
    ),
)

# =========================================================================== D6. Report and package

D6_FILL = Move(MoveKind.E, "fill every requirement row from run records and generated figures")
D6_Q_SAMPLE = Move(MoveKind.Q, "you: the first full render")
D6_Q_CODE = Move(MoveKind.Q, "you: code inside the PDF, or a public GitHub repository under your name")
D6_R = Move(MoveKind.R, "the submission PDF")
D6_DELIVERS = "the PDF report with the code and README"

d6 = Decision(
    name="D6 report and package",
    where="after D5's plan check shows every cell filled",
    status="forward; proposal",
    delivers=D6_DELIVERS,
    options=(D6_FILL, D6_Q_SAMPLE, D6_Q_CODE, D6_R),
    judged=("every brief item and grading row is answered", "the report makes sense to the grader",
            "names and student IDs are right", "AI use is declared", "the code reaches the grader"),
    gates=(
        Gate("requirement table", "every brief item and grading row is answered", (COURSE,), D6_R,
             Trigger("any row unmapped", Judge.TOOL, rechecks=True, basis=q_req),
             ((Hop("brief", q_report, Effect.CLOSES), Hop("grading", g_algo), Hop("grading", g_disc),
               Hop("printed", q_req)),),
             judges=D6_DELIVERS, enforced=True, cleared_by=(Clear(D6_FILL, Fix.FIXES, q_req),)),
        Gate("log axes, no logs", "every brief item and grading row is answered", (COURSE,), D6_R,
             Trigger("a time/size/core axis is linear, or a log file is packaged", Judge.TOOL, rechecks=True,
                     basis=q_req),
             ((Hop("comments", c_axes, Effect.CLOSES), Hop("comments", c_logs), Hop("printed", q_req)),),
             judges=D6_DELIVERS, enforced=True, cleared_by=(Clear(D6_FILL, Fix.FIXES, c_axes),)),
        Gate("terminology defined", "the report makes sense to the grader", (COURSE,), D6_R,
             Trigger("a flagged term has no definition", Judge.TOOL, rechecks=True, basis=q_terms),
             ((Hop("comments", c_terms, Effect.CLOSES), Hop("printed", q_terms)),), judges=D6_DELIVERS,
             measures="each flagged term has a definition sentence", measures_basis=q_terms,
             cleared_by=(Clear(D6_FILL, Fix.PROXY, q_terms),)),
        Gate("names and IDs", "names and student IDs are right", (COURSE, YOU), D6_Q_SAMPLE,
             Trigger("the Project 3 group is not confirmed", Judge.YOU, now=False, basis=q_you_group),
             ((Hop("brief", q_group, Effect.REQUIRES), Hop("P2", q_p1_authors)),)),
        Gate("AI declaration", "AI use is declared", (COURSE,), D6_R,
             Trigger("missing", Judge.TOOL, rechecks=True, basis=q_req),
             ((Hop("brief", q_ai, Effect.CLOSES), Hop("comments", c_ai)),), judges=D6_DELIVERS, enforced=True,
             cleared_by=(Clear(D6_FILL, Fix.FIXES, q_ai),)),
        Gate("code route", "the code reaches the grader", (YOU,), D6_Q_CODE,
             Trigger("the package is ready", Judge.YOU, now=False, after=MoveKind.E, basis=q_code),
             ((Hop("brief", q_code, Effect.REQUIRES), Hop("canvas", q_pdf_only)),)),
        Gate("first rendered sample", "the report makes sense to the grader", (SKILL, YOU), D6_Q_SAMPLE,
             Trigger("the first full render exists", Judge.YOU, now=False, after=MoveKind.E,
                     basis=Quote("the first rendered sample", "circuit_use/ASSUMPTIONS.md, 6", "your records")),
             ((Hop("you", q_you_circuit), Hop("skill", Quote("At every stage the user sees a real, rendered intermediate "
                                                              "output", "checkpoint-build skill description", "skill"),
                                              Effect.REQUIRES)),)),
        Gate("you upload", "the code reaches the grader", (YOU_EARLIER,), None,
             Trigger("always", Judge.TOOL), ((Hop("you, P2", q_you_nosubmit),),)),
        Gate("deadline", "every brief item and grading row is answered", (COURSE,), None,
             Trigger("always", Judge.TOOL), ((Hop("announcement", q_due),),)),
    ),
)

# =========================================================================== D0. HPC access from India (added 12 Nov)
# B3 "Own setup and resumption" plus Lecture 13 Demo 2 step 1. The parent prepares everything it may. The question
# is which steps only you can take, and whether they can go in one stop.

HOST = Owner("the host's safety rules for this agent", OwnerKind.EXTERNAL)
L13 = "Lecture_13.pdf, 'Demo 2: HPC projects' (Cai Zhenning, Anthony Chen)"
q_l13 = Quote("Step 1: Prepare the tool (SSH) for the agent by setting up the password-free login to the NUS HPC cluster.",
              L13, "lecture")
q_you_india = Quote("load gthe circuit to do this ferom my laptop in india with mi9nimmum manual worj and start",
                    "parent session 2026-11-12", "you")
q_dns = Quote("atlas8.nus.edu.sg DNS: (none) port22: closed/unreachable; vanda.nus.edu.sg likewise; no VPN client in "
              "/Applications", "this Mac, 2026-11-11", "shell")
q_vpn = Quote("students should select \"NUS Student - TLS - Auto Select Nearest Location\" ... Yes, Multi-Factor "
              "Authentication (MFA) is required ... Microsoft Authenticator", "NUS A.S.K. HelixGPT answer, 2026-11-11",
              "NUS IT")
q_pkg = Quote("Developer ID Installer: Cisco (DE8Y96K9QP) ... Notarization: trusted by the Apple notary service; "
              "spctl: accepted", "pkgutil --check-signature on the A.S.K. installer, 2026-11-12", "shell")
q_no_pw = Quote("Prohibited: ... entering passwords to authenticate", "this agent's host safety rules", "host")
q_blocked_id = Quote("[BLOCKED: Cookie/query string data]", "Chrome tool, reading the Canvas profile login id, 2026-11-11",
                     "browser tool")
q_ok_ssh = predicted("OK atlas8: password-free login works / OK vanda: password-free login works",
                     ".application/hpc_first_login.sh, then ssh -o BatchMode=yes by the parent")

D0_PREP = Move(MoveKind.E, "parent: key, ssh config, first-login script, installer downloaded and verified")
D0_Q_VPN = Move(MoveKind.Q, "you: install Cisco Secure Client and connect (NUS Student profile, MFA)")
D0_Q_ID = Move(MoveKind.Q, "you: your NUSNET ID")
D0_Q_PW = Move(MoveKind.Q, "you: type your NUSNET password once in the script window")
D0_VERIFY = Move(MoveKind.E, "parent: ssh -o BatchMode=yes to atlas8 and vanda; then qstat -Qf, hpc project")
D0_R = Move(MoveKind.R)
D0_DELIVERS = "password-free SSH from this Mac to atlas8 and vanda"

d0 = Decision(
    name="D0 HPC access from India",
    where="before any cluster run (now)",
    status="forward; proposal",
    delivers=D0_DELIVERS,
    options=(D0_PREP, D0_VERIFY, D0_Q_VPN, D0_Q_ID, D0_Q_PW, D0_R),
    judged=("the agent can run cluster jobs without you", "your manual work is the minimum"),
    gates=(
        Gate("password-free login verified", "the agent can run cluster jobs without you", (COURSE, YOU), D0_R,
             Trigger("until both BatchMode logins succeed", Judge.TOOL, rechecks=True, basis=q_ok_ssh),
             ((Hop("lecture", q_l13, Effect.CLOSES), Hop("printed", q_ok_ssh)),), judges=D0_DELIVERS, enforced=True,
             cleared_by=(Clear(D0_VERIFY, Fix.FIXES, q_ok_ssh),)),
        Gate("off campus: VPN required", "the agent can run cluster jobs without you", (HPC,), D0_VERIFY,
             Trigger("the clusters do not resolve from this Mac", Judge.TOOL), ((Hop("shell", q_dns, Effect.CLOSES),
                                                                                  Hop("handout", q_login)),)),
        Gate("VPN login is yours", "the agent can run cluster jobs without you", (YOU, HPC), D0_Q_VPN,
             Trigger("no VPN client connected", Judge.YOU), ((Hop("NUS IT", q_vpn, Effect.REQUIRES),
                                                              Hop("installer", q_pkg)),)),
        Gate("NUSNET ID unknown", "the agent can run cluster jobs without you", (YOU,), D0_Q_ID,
             Trigger("the ID could not be read without working around a block", Judge.YOU),
             ((Hop("browser", q_blocked_id, Effect.REQUIRES),),)),
        Gate("password is yours", "the agent can run cluster jobs without you", (HOST, YOU), D0_Q_PW,
             Trigger("the script reaches ssh-copy-id", Judge.YOU, now=False, after=MoveKind.Q,
                     basis=Quote("ssh-copy-id -i ~/.ssh/id_ed25519_nus.pub \"$h\"", ".application/hpc_first_login.sh",
                                 "script")),
             ((Hop("host", q_no_pw, Effect.REQUIRES),),)),
        Gate("minimum manual work", "your manual work is the minimum", (YOU,), None, Trigger("always", Judge.YOU),
             ((Hop("you", q_you_india),),)),
    ),
)

# =========================================================================== D7. Data-science extension (added 12 Nov)
# Your request: "add the data science extension, or identify the correct circuit to find the extension and add it".
# The base solver (CG on the Poisson equation, validated on Atlas) stays. The extension adds real data.

q_you_ext = Quote("ok continur and add the data science extension, or identifythe correct circuit to find the extension and "
                  "add it", "parent session 2026-11-12", "you")
q_realdata = Quote("If working with real data, conclusions about the data", BRIEF, "brief")
g_disc_data = Quote("If you are using real world datasets, please explain any conclusions about the dataset that you drew.",
                    L12, "lecture")
l7_snap = Quote("Some datasets which might be useful: ... Stanford Large Network Dataset Collection", L7, "lecture")
l7_uci = Quote("Some datasets which might be useful: UC Irvine Machine Learning Repository", L7, "lecture")
l7_regr = Quote("Some data science algorithms you might consider: Regression (linear, logistic)", L7, "lecture")
q_snap_gt = Quote("Networks with ground-truth communities: email-Eu-core 1,005 / 25,571 ... com-Amazon 334,863 / 925,872 ... "
                  "com-DBLP 317,080 / 1,049,866 ... com-Youtube 1,134,890 / 2,987,624 ... com-LiveJournal 3,997,962 / "
                  "34,681,189 ... com-Orkut 3,072,441 / 117,185,083 (nodes / edges)", "snap.stanford.edu/data, read 2026-11-12",
                  "SNAP")
q_reach = Quote("https://snap.stanford.edu/data/bigdata/communities/com-lj.ungraph.txt.gz -> 200; "
                "https://archive.ics.uci.edu/ -> 200", "curl from vanda login node, 2026-11-12", "shell")
q_cg_spd = Quote("CG needs a symmetric positive definite operator; a graph Laplacian plus a positive shift, L + aI, is one, so "
                 "the validated CG and pipelined CG run unchanged with a sparse matrix-vector product in place of the stencil",
                 "inferred from the algorithm (any CG text)", "parent", Known.INFERRED)
q_cgls = Quote("ridge regression by CG runs on the normal equations (X^T X + lambda I) w = X^T y: two sparse products per "
               "iteration and an Allreduce of a length-d vector", "inferred from the algorithm", "parent", Known.INFERRED)
q_gt_conclusion = predicted("GRAPH <name>: n=<V> m=<E>; seeds per community <k>; label recovery accuracy vs ground truth <acc> "
                            "(majority baseline <b>); CG iterations <it> vs average degree <d>", "checks/graph_conclusions.py")

D7_GRAPH = Move(MoveKind.E, "CG on graph Laplacian systems (L + aI) x = b from SNAP networks with ground-truth communities: "
                            "semi-supervised community labelling, scored against the ground truth")
D7_RIDGE = Move(MoveKind.E, "ridge regression on a UCI/LIBSVM sparse dataset by CG on the normal equations (CGLS)")
D7_SUITE = Move(MoveKind.E, "CG on SuiteSparse SPD engineering matrices")
D7_NONE = Move(MoveKind.F, "no extension: synthetic Poisson only")
D7_R = Move(MoveKind.R)
D7_DELIVERS = "a real-data extension of the CG solver, with conclusions about the data"

d7_gates = (
    Gate("you asked for a data-science extension", "the report draws conclusions about real data", (YOU,), D7_R,
         Trigger("until a real-data run and its conclusions exist", Judge.TOOL, rechecks=True, basis=q_gt_conclusion),
         ((Hop("you", q_you_ext, Effect.CLOSES), Hop("printed", q_gt_conclusion)),), judges=D7_DELIVERS,
         cleared_by=(Clear(D7_GRAPH, Fix.FIXES, q_gt_conclusion), Clear(D7_RIDGE, Fix.FIXES, q_realdata),
                     Clear(D7_SUITE, Fix.PROXY, q_realdata), Clear(D7_NONE, Fix.PROXY, q_you_ext))),
    Gate("real data needs conclusions about the data", "the report draws conclusions about real data", (COURSE,), D7_R,
         Trigger("a real-data run without conclusions", Judge.TOOL, rechecks=True, basis=q_gt_conclusion),
         ((Hop("brief", q_realdata, Effect.CLOSES), Hop("grading", g_disc_data)),), judges=D7_DELIVERS, enforced=True,
         cleared_by=(Clear(D7_GRAPH, Fix.FIXES, q_gt_conclusion), Clear(D7_RIDGE, Fix.FIXES, g_disc_data),
                     Clear(D7_SUITE, Fix.PROXY, q_realdata))),
    Gate("no extension is what you ruled out", "the report draws conclusions about real data", (YOU,), D7_NONE,
         Trigger("always", Judge.YOU), ((Hop("you", q_you_ext, Effect.CLOSES),),)),
    Gate("graph asks: vary vertices and edges, discuss sparsity", "the parallelization presents real challenges", (COURSE,),
         D7_GRAPH, Trigger("always", Judge.TOOL), ((Hop("grading", g_serial), Hop("comments", c_graph)),
                                                    (Hop("SNAP", q_snap_gt),))),
    Gate("lecture lists SNAP", "the report draws conclusions about real data", (COURSE,), D7_GRAPH,
         Trigger("always", Judge.TOOL), ((Hop("lecture", l7_snap, Effect.OPENS),),)),
    Gate("lecture lists regression and UCI", "the report draws conclusions about real data", (COURSE,), D7_RIDGE,
         Trigger("always", Judge.TOOL), ((Hop("lecture", l7_regr, Effect.OPENS), Hop("lecture", l7_uci)),)),
    Gate("data reachable from Vanda", "the report draws conclusions about real data", (HPC,), None,
         Trigger("always", Judge.TOOL), ((Hop("shell", q_reach),),)),
    Gate("CG stays the validated CG", "the parallel code computes the right answer", (AGENT,), None,
         Trigger("always", Judge.TOOL), ((Hop("algorithm", q_cg_spd), Hop("algorithm", q_cgls)),)),
    Gate("weak scaling stays on synthetic Poisson", "the parallelization presents real challenges", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("comments", c_synth),),)),
    Gate("five days left", "the report draws conclusions about real data", (COURSE,), None,
         Trigger("always", Judge.TOOL), ((Hop("announcement", q_due),),)),
)

d7 = Decision(
    name="D7 data-science extension",
    where="after the Poisson solver is validated on a cluster (Atlas 1040046)",
    status="forward; proposal",
    delivers=D7_DELIVERS,
    options=(D7_GRAPH, D7_RIDGE, D7_SUITE, D7_NONE, D7_R),
    judged=("the report draws conclusions about real data", "the parallelization presents real challenges",
            "the parallel code computes the right answer"),
    gates=d7_gates,
)

# D7' variant: the same gates, with ridge regression listed first. As in D3', rule 4 takes the first open edit in listing
# order, so this shows whether any gate, rather than the encoder, separates graph from ridge.
d7_ridge_first = replace(d7, name="D7' data-science extension, ridge listed first", status="forward; variant",
                         options=(D7_RIDGE, D7_GRAPH, D7_SUITE, D7_NONE, D7_R))

# =========================================================================== D8. Getting >=256 cores scheduled (12 Nov)
# Your question: "is there any other node efficient method to do that, identify the correct circuit and ask this question".

q_you_d8 = Quote("is there any other node efficient method to do that, identofy the correct circuit and ask this question?",
                 "parent session 2026-11-12 22:15 IST", "you")
q_queue = Quote("cpu_node pool: 19 fully free; 20 with >=32 free cores. batch_cpu: Priority 100, Queued 993, Running 186. "
                "Our 4-node jobs: 'Not Running: Insufficient amount of resource: ncpus' (queued since 14:42 SGT)",
                "pbsnodes / qstat -Qf on vanda, 2026-11-12 22:15 IST", "shell")
q_autox = Quote("autox: Route -> batch_cpux,batch_gpux; batch_cpux: Priority 200, Queued 0, Running 11, default_chunk.node_pool = "
                "cpu_node, resources_max.ncpus = 720, queue_charge_rate = 1, no acl listed", "qstat -Qf autox batch_cpux, "
                "2026-11-12", "shell")
q_samples = Quote("##PBS -q auto_free ... To submit job to [auto_free] queue, delete '-P Project-Name' line",
                  "`hpc cpu` sample script on vanda", "NUS HPC")
q_nodoc = Quote("The search didn't turn up anything about the Vanda system or the autox and batch_cpux queues",
                "web search 2026-11-12", "search")
q_aup = Quote("Refrain from any illegal, harmful, offensive, or unethical use of the system.",
              "HPC Registration Form, Acceptable Use Policy item", "NUS HPC")
q_whole = Quote("Timing jobs reserve whole nodes (place=excl).", "child turn 1 report (run plan design)", "build")

D8_WAIT = Move(MoveKind.W, "keep the 4-node jobs in batch_cpu and wait (Saturday-evening fallback)")
D8_AUTOX = Move(MoveKind.E, "resubmit the two 4-node jobs to -q autox (batch_cpux, priority 200, same nodes and charge)")
D8_SPREAD = Move(MoveKind.F, "add a 256-core job spread over 8 partly used nodes (8 x 32 cores, shared) in batch_cpu")
D8_Q = Move(MoveKind.Q, "you: may we use autox? (or ask NUS HPC first), and do you accept spread-node timings")
D8_R = Move(MoveKind.R)
D8_DELIVERS = "runs on >=256 cores for strong and weak scaling"

d8 = Decision(
    name="D8 getting >=256 cores scheduled",
    where="12 Nov 22:15 IST, two 4-node jobs queued ~8 h",
    status="forward; proposal",
    delivers=D8_DELIVERS,
    options=(D8_AUTOX, D8_SPREAD, D8_WAIT, D8_Q, D8_R),
    judged=("MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and communication cost",
            "the timings compare like with like", "we use the cluster fairly"),
    gates=(
        Gate("256 cores required", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and "
             "communication cost", (COURSE,), D8_R, Trigger("until a >=256-core run exists", Judge.TOOL, rechecks=True,
                                                             basis=q_plan),
             ((Hop("grading", g_mpi, Effect.CLOSES), Hop("printed", q_plan)),), judges=D8_DELIVERS, enforced=True,
             cleared_by=(Clear(D8_AUTOX, Fix.FIXES, g_mpi), Clear(D8_SPREAD, Fix.PROXY, q_whole))),
        Gate("the bottleneck is queue position, not nodes", "MPI scaling reaches 256 cores, strong and weak, with "
             "speedup, efficiency and communication cost", (HPC,), None, Trigger("always", Judge.TOOL),
             ((Hop("shell", q_queue),),)),
        Gate("autox: purpose undocumented", "we use the cluster fairly", (HPC, YOU), D8_Q,
             Trigger("autox is not documented as open to course users", Judge.OTHER_PERSON, now=None, basis=q_nodoc),
             ((Hop("shell", q_autox), Hop("samples", q_samples), Hop("AUP", q_aup, Effect.REQUIRES)),)),
        Gate("whole nodes for comparable timings", "the timings compare like with like", (YOU_EARLIER,), D8_SPREAD,
             Trigger("the other series ran on whole nodes", Judge.TOOL), ((Hop("plan", q_whole, Effect.CLOSES),),)),
        Gate("you asked", "MPI scaling reaches 256 cores, strong and weak, with speedup, efficiency and communication "
             "cost", (YOU,), D8_Q, Trigger("always", Judge.YOU), ((Hop("you", q_you_d8, Effect.REQUIRES),),)),
    ),
)

# --------------------------------------------------------------------------- answers since writing (11 Nov)
# Rule 8: an answer settles only the property its gate names, so each answer turns one gate off and nothing else.
q_ans_algo = Quote("CG Poisson 2D+3D (Recommended)", "parent session 2026-11-11, answer to the algorithm question",
                   "you")
q_ans_hpc = Quote("Account works, set up keys", "parent session 2026-11-11, answer to the HPC access question", "you")


def _answered(d: Decision, gate_name: str, basis: Quote, suffix: str) -> Decision:
    gates = tuple(replace(g, trigger=replace(g.trigger, now=False, basis=basis)) if g.name == gate_name else g
                  for g in d.gates)
    return replace(d, name=d.name + suffix, status="forward; after your answer", gates=gates)


d2_answered = _answered(d2, "the algorithm is the group's choice", q_ans_algo, " (after: CG chosen)")
# D1: your account works, but no login has been seen from this Mac yet. The access question is answered; the
# 'cluster jobs need your login' gate stays open until the first non-interactive ssh succeeds.
d1_answered = _answered(d1, "HPC login unconfirmed", q_ans_hpc, " (after: account works, keys pending)")

DECISIONS = (d0, d1, d2, d2_delegated, d3, d3_cuda_first, d4, d5, d6, d7, d7_ridge_first, d8, d1_answered, d2_answered)


def main() -> None:
    for d in DECISIONS:
        print("=" * 100)
        print(d.name)
        f = compute(d)
        print(f.explain())
        print("load (gate removed -> does the path change?):")
        for name, _, changed in load(d, pairs=False):
            print(f"  {'CHANGES' if changed else 'no change':10} {name}")


if __name__ == "__main__":
    main()
