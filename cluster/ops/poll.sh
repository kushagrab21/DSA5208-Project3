#!/usr/bin/env bash
# poll.sh <atlas8|vanda>: state of every submitted job not yet seen finished (from the local ledger).
# For finished jobs: exit status, walltime used, core-hours used (qstat -x -f; if the job has left the PBS history,
# the job's own start/end record), and flags: nonzero exit, walltime exceeded, missing records. Exit 2 on a flag.
source "$(dirname "$0")/common.sh"
usage_alias "${1:-}" ""
alias="$1"; cl="$(cluster_of "$alias")"
ids="$("$PY" "$OPS/opslib.py" pending --cluster "$cl")"
if [[ -z "$ids" ]]; then echo "POLL $cl: no jobs in flight (ledger: ${RESULTS#$REPO/}/$cl/jobs.csv)"; exit 0; fi
# shellcheck disable=SC2086
probe="$(remote "$alias" "$REMOTE_DIR" "$cl" $ids <<'EOS'
dir="$1"; cl="$2"; shift 2
cd "$HOME/$dir" 2>/dev/null || true
echo "=== QSTAT ==="
qstat -x -f "$@" 2>&1 || qstat -f "$@" 2>&1 || true
for id in "$@"; do
  echo "=== ROWS $id ==="
  n=0   # rows of the Poisson record and of the graph record (<id>.graph.csv) of this job
  for f in "results/$cl/$id.csv" "results/$cl/$id.graph.csv"; do
    if [ -f "$f" ]; then n=$(( n + $(wc -l < "$f") - 1 )); fi
  done
  echo $n
done
echo "=== EVENTS ==="
f="results/$cl/jobs.csv"
if [ -f "$f" ]; then head -1 "$f"; for id in "$@"; do grep -F "$id," "$f" | grep -v '^pbs_jobid' || true; done; fi
echo "=== VALIDATED ==="
[ -f results/validated_binaries.csv ] && cat results/validated_binaries.csv || true
EOS
)"
printf '%s\n' "$probe" | "$PY" "$OPS/opslib.py" poll-parse --cluster "$cl"
