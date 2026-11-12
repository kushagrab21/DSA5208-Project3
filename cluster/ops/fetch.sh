#!/usr/bin/env bash
# fetch.sh <atlas8|vanda>: copies results/<cluster>/ (run records, job events, machine files), the cluster's
# validation output and qualified binaries, and the PBS logs back; merges them without rewriting local rows; then
# checks the records, prints the plan status (cells filled, core-hours used) and recalibrates the cost model.
source "$(dirname "$0")/common.sh"
usage_alias "${1:-}" ""
alias="$1"; cl="$(cluster_of "$alias")"
staging="$RESULTS/.staging/$cl"
rm -rf "$staging"; mkdir -p "$staging/cluster" "$RESULTS/validation/$cl" "$LOGS/$cl"
rsync_or_explain -a "$alias:$REMOTE_DIR/results/$cl/" "$staging/cluster/" 2>/dev/null ||
  echo "  (no results/$cl on the cluster yet)"
rsync_or_explain -a "$alias:$REMOTE_DIR/results/validation/$cl/" "$RESULTS/validation/$cl/" 2>/dev/null ||
  echo "  (no validation output on the cluster yet)"
# copy into the folder, not onto a file name: some rsync builds create a directory named after a missing source
rsync_or_explain -a "$alias:$REMOTE_DIR/results/validated_binaries.csv" "$staging/" \
  2>/dev/null || echo "  (no qualified binaries on the cluster yet)"
rsync_or_explain -a "$alias:$REMOTE_DIR/cluster/logs/" "$LOGS/$cl/" 2>/dev/null || true
"$PY" "$OPS/opslib.py" merge-fetched --cluster "$cl" --staging "$staging"
if ls "$RESULTS/$cl"/*.csv >/dev/null 2>&1; then "$PY" "$REPO/checks/run_record.py" "$RESULTS/$cl" || true; fi
"$PY" "$REPO/checks/run_plan.py" status --plan "$cl" || true
"$PY" "$OPS/opslib.py" calibrate --cluster "$cl"
echo "PBS logs (diagnosis only; never part of the submission): ${LOGS#$REPO/}/$cl/"
