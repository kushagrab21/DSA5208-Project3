# Step 4: settle, default, ask

Ranked by how badly the report fails if wrong, how uncertain, and how costly to reverse.

## Settled from the material
- **How the "calibration" bandwidth is computed** (drill L2 sample, user item 8): from the code
  (`cluster/ops/opslib.py cmd_calibrate`). Effective bandwidth = unknowns × bytes moved per unknown per iteration (96 classic,
  128 pipelined, from the plan's memory model) × iterations ÷ measured time, median over cells and repeats. Single-core runs
  with at least 4 million unknowns give the per-core value; full-node runs give the per-node value. The report states this
  in one sentence and drops the word "calibration".
- **The stale "UNTESTED" code comment** (pre-mortem 6): a fact error. The GPU build ran and passed validation on a Vanda
  GPU node (job 1547835). Fix the comment, and scan every printed comment for similar stale claims.
- **Vocabulary** (drill Part E): his words win ("reduction", "halo exchange", "domain decomposition", "validation tests",
  "synthetic test problem", "OpenMP GPU offload").

## Assistant's defaults (open to change; not the user's decisions)
- **Table 2** becomes a plain overview of the experiments, without E-codes and without the Atlas column (no Atlas timings
  exist).
- **Two simple schematics**: the three domain splits with their halos, and one Vanda node with its two sockets and memory.
  They support the "hardware first" rule (P8) and the socket results. Drawn from facts already in the report.
- **Shared-node 256-core points**: if the whole-node 288-core runs arrive, the figures use them and the shared-node points
  move to one sentence. Otherwise the shared-node conditions are explained once, plainly, at the first scaling figure.
- **Graph part**: kept at its length. It opens by saying why it is there (real data, irregular communication, the graph
  rules on the grading slide).
- **MPI windows**: one sentence. The halo exchange uses two-sided messages (MPI_Sendrecv, MPI_Isend/Irecv). One-sided RMA
  windows were not implemented. This is stated as a fact, with no invented reason.
- **Order of work**: sections whose numbers are final are passed now. Sections 6, 7, 8.8-8.9, 9 and the Summary are
  passed when the 256+-core data are in.

## Questions for the user (pass all four conditions: load-bearing, unsettled by material, the user's to decide, costly to undo)
1. **What "first-principled" means.**
   - Why it cannot be settled: your word, with two readings.
   - Proposed default: every claim is shown as a chain from what each process owns, what each operation needs, and the
     flops/bandwidth/latency cost model, in the grader's own terms. This does not mean re-explaining CG from scratch, which
     he taught.
   - Test it on the before/after sample in `03_DRILL.md` (L2).
2. **Who does the pass "by hand", and what the AI declaration then says.**
   - Why it cannot be settled: your words "by hand" could mean you two do it yourselves.
   - Proposed default: I rewrite the text paragraph by paragraph, following the record, with judgement and no
     find-and-replace. You and Pratyush then read each revised section aloud and mark any sentence you cannot explain, and
     I fix those. The AI declaration states exactly that.
