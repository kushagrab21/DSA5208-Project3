# How the work was planned and checked

These are our planning notes, copied here so that the repository keeps them with the code. The program and the report
do not depend on them. They record why the project went the way it did.

- `circuit/` holds the decision map we used to plan the project (`p3_circuit.py`, read as `CIRCUIT.md`). For each
  decision, such as which algorithm, which cluster, how to validate and how to reach 256 cores, it lists the options, the
  evidence that settled the choice and the check that had to pass before moving on. It follows the same method as our
  Projects 1 and 2, which is summarised in `decision_log/circuits_from_projects_1_and_2.md`.
- `assumption_drill/` records two questions we settled before rewriting the report: how its language should work for
  the grader, and which visual markers help a dense page. In each folder, `ASSUMPTIONS.md` gives the result, and the
  other files show how human-written reports were used to reach it.
- `decision_log/` holds the coordinating session's log (`state.md`). Each entry says what was decided, why and what
  happened. Alongside it are the written instructions given to the session that built the code and the report
  (`build-task-NN.txt`), in order.

They are copies, refreshed by `scripts/sync_process_notes.sh`. The originals live outside the repository. The course
slides and the third-party papers read for the drills are left out, because they are not ours to redistribute.
