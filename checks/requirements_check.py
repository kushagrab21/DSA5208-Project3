#!/usr/bin/env python3
"""Requirements check (STUB for the report turn): prints E1-E18 from circuit/CIRCUIT.md section 3 and refuses
release while any row is unmapped.

Planned (report turn): map each row to a report section or package item, count hand-typed numbers (0), linear
time/size/core axes (0), log files in the package (0), authors (2), the AI-usage section, and print TERMS (flagged
terms with a definition sentence) without enforcing it. Qualify on the first full render (pass once the user
accepts it) and on a copy with a linear core axis (refused).
"""
import sys

ROWS = [
    ("E1", "The algorithm is introduced", "B; G 5"),
    ("E2", "Serial runtime over problem size (matrix size and nonzeros vary)", "G 5"),
    ("E3", "MPI strong scaling to >=256 cores, speedup and efficiency", "G 10"),
    ("E4", "MPI weak scaling to >=256 cores, speedup and efficiency", "G 10"),
    ("E5", "Effect of communication (flops, volume/bandwidth, calls x latency)", "G 10"),
    ("E6", "MPI+X: rank x thread layouts on 72-core nodes", "G 10"),
    ("E7", "At least one GPU run (X = OpenMP)", "G 10"),
    ("E8", "Design decisions; which parts communicate most", "B; G 5"),
    ("E9", "Validation, each test explained, set kept small", "B; C"),
    ("E10", "Runtime figures from Atlas or Vanda", "B"),
    ("E11", "Synthetic data: how it was generated", "B; C"),
    ("E12", "Poisson in 2D and 3D", "C"),
    ("E13", "All non-standard terminology defined", "C"),
    ("E14", "Log axes for time, size and core count", "C"),
    ("E15", "AI use explained", "B; C"),
    ("E16", "Code + README in the PDF or a public GitHub link; no logs/terminal output", "B; C"),
    ("E17", "Names and IDs: Kushagra Bhatnagar (A0351591A), Pratyush Sinha (A0352482A)", "B"),
    ("E18", "Upload to Canvas by 17 Nov 23:59 SGT (PDF only) - the user's act", "B"),
]


def main():
    print("REQUIREMENTS CHECK (stub): report not written yet")
    for rid, prop, src in ROWS:
        print("  %-4s %-80s %-8s UNMAPPED" % (rid, prop, src))
    print("REQUIREMENTS: REFUSED (%d of %d rows unmapped)" % (len(ROWS), len(ROWS)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
