#!/usr/bin/env python3
"""Timing gate: refuses to start timing runs with a binary that validate.py has not qualified here.

  python3 checks/timing_gate.py --binary bin/p3cg
  python3 checks/timing_gate.py --binary bin/p3graph --require-cases G1,G2     (graph runs: validate_graph.py)

"Here" is the cluster label the solver will write (atlas|vanda inside a PBS job with P3_CLUSTER set, else local),
so a binary validated on the Mac does not open the gate on Vanda, and vice versa. Exit 0 = allowed, 1 = refused.
"""
import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3common as C  # noqa: E402


def current_cluster():
    """Same rule as detect_cluster() in src/record.cpp."""
    host = socket.gethostname()
    want = os.environ.get("P3_CLUSTER") or ("atlas" if "atlas" in host else "vanda" if "vanda" in host else "local")
    if want not in C.CLUSTERS:
        return "local"
    if not os.environ.get("PBS_JOBID"):
        return "local"
    return want


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--require-cases", default="", help="comma list of case ids the qualification must include")
    a = ap.parse_args()
    sha = C.sha256_file(a.binary)
    cl = current_cluster()
    need = set(x for x in a.require_cases.split(",") if x)
    hits = [e for e in C.validated_entries() if e["binary_sha256"] == sha and e["cluster"] == cl and
            need <= set(e["cases"].split(";"))]
    if not hits:
        others = sorted(set(e["cluster"] for e in C.validated_entries() if e["binary_sha256"] == sha))
        print("TIMING GATE: REFUSED  %s sha256=%s is not qualified%s on cluster=%s%s" %
              (a.binary, sha, (" with cases %s" % ",".join(sorted(need))) if need else " by validate.py", cl,
               (" (qualified on: %s)" % ",".join(others)) if others else ""))
        return 1
    e = hits[-1]
    print("TIMING GATE: ALLOWED  %s sha256=%s qualified on cluster=%s at %s (cases %s; refused %s)" %
          (a.binary, sha, cl, e["utc"], e["cases"], e["bug_binaries_refused"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
