#!/usr/bin/env bash
# submit.sh <atlas8|vanda> <plan job> [--dry-run]: the ONLY way a job reaches qsub.
# Refuses: a job not in the plan; a cluster that does not hold the local commit and plan; a second submission
# without a recorded rerun reason; any timed job before a cluster-built binary is qualified there; timed jobs while
# the plan is not frozen (the <cluster>-calibrate job is the one exception); a job whose worst case would exceed the
# core-hour budget. Records the PBS id append-only in results/<cluster>/jobs.csv and prints the remaining budget.
source "$(dirname "$0")/common.sh"
usage_alias "${1:-}" "<job> [--dry-run]"
alias="$1"; job="${2:?usage: submit.sh <atlas8|vanda> <job> [--dry-run]}"; dry="${3:-}"
cl="$(cluster_of "$alias")"
state="$(remote "$alias" "$REMOTE_DIR" <<'EOS'
cd "$HOME/$1" 2>/dev/null || { echo "commit none"; exit 0; }
cat SYNCED 2>/dev/null || echo "commit none"
if [ -f bin/p3cg ]; then
  echo "bin $( { sha256sum bin/p3cg 2>/dev/null || shasum -a 256 bin/p3cg; } | cut -d' ' -f1)"
else echo "bin missing"; fi
EOS
)"
rcommit="$(awk '$1=="commit"{print $2}' <<<"$state")"
rplan="$(awk -v k="plan_$cl" '$1==k{print $2}' <<<"$state")"
rbin="$(awk '$1=="bin"{print $2}' <<<"$state")"
"$PY" "$OPS/opslib.py" submit-check --cluster "$cl" --job "$job" --remote-commit "$rcommit" \
  --remote-plan "$rplan" --remote-bin "$rbin" || exit 1
"$PY" "$REPO/checks/run_plan.py" pbs --plan "$cl" --job "$job" | grep -v '^note:' || exit 1
script="$GENERATED/$cl/$job.pbs"
if [[ "$dry" == "--dry-run" ]]; then echo "DRY RUN: would copy ${script#$REPO/} and qsub it on $alias"; exit 0; fi
remote "$alias" "$REMOTE_DIR/cluster/generated/$cl" <<'EOS'
mkdir -p "$HOME/$1"
EOS
rsync_or_explain -a "$script" "$alias:$REMOTE_DIR/cluster/generated/$cl/"
out="$(remote "$alias" "$REMOTE_DIR" "$cl" "$job" <<'EOS'
cd "$HOME/$1" && qsub "cluster/generated/$2/$3.pbs"
EOS
)" || { echo "SUBMIT: qsub failed on $alias:"; echo "$out" | sed 's/^/  /'; exit 1; }
pbsid="$(echo "$out" | grep -E '^[0-9]+(\.[A-Za-z0-9._-]+)?$' | tail -1)"
if [[ -z "$pbsid" ]]; then echo "SUBMIT: qsub did not return a job id:"; echo "$out" | sed 's/^/  /'; exit 1; fi
"$PY" "$OPS/opslib.py" record-submit --cluster "$cl" --job "$job" --pbs-id "$pbsid" --commit "$rcommit" \
  --alias "$alias"
