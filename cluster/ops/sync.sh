#!/usr/bin/env bash
# sync.sh <atlas8|vanda>: copies the committed source tree (src CMakeLists.txt scripts checks cluster config README.md)
# to ~/$P3_REMOTE_DIR on the cluster and records the commit on both sides. Refuses on a dirty working tree.
# Remote-only folders (bin, _build, results, cluster/logs, cluster/generated) are never touched.
source "$(dirname "$0")/common.sh"
usage_alias "${1:-}" ""
alias="$1"; cl="$(cluster_of "$alias")"
dirty="$(git -C "$REPO" status --porcelain)"
if [[ -n "$dirty" ]]; then
  echo "SYNC: REFUSED the working tree is not clean; commit first so the cluster runs an identifiable commit:"
  echo "$dirty" | head -10 | sed 's/^/  /'
  exit 1
fi
commit="$(git -C "$REPO" rev-parse HEAD)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
git -C "$REPO" archive HEAD src CMakeLists.txt scripts checks cluster config README.md | tar -x -C "$tmp"
if [[ -n "${P3_CONFIG:-}" ]]; then cp "$P3_CONFIG"/run_plan.*.json "$tmp/config/"; fi   # tests: scratch plans
plansha="$("$PY" "$OPS/opslib.py" plan-sha --cluster "$cl")"
printf 'commit %s\nplan_%s %s\nutc %s\nfrom %s\n' "$commit" "$cl" "$plansha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$(hostname)" > "$tmp/SYNCED"
remote "$alias" "$REMOTE_DIR" <<'EOS'
mkdir -p "$HOME/$1"
EOS
rsync_or_explain -a --delete --exclude=/bin/ --exclude=/_build/ --exclude=/results/ --exclude=/cluster/logs/ \
  --exclude=/cluster/generated/ --exclude=/.venv/ "$tmp/" "$alias:$REMOTE_DIR/"
back="$(remote "$alias" "$REMOTE_DIR" <<'EOS'
cat "$HOME/$1/SYNCED"
EOS
)"
rcommit="$(awk '$1=="commit"{print $2}' <<<"$back")"
if [[ "$rcommit" != "$commit" ]]; then echo "SYNC: FAILED the cluster reports commit '$rcommit'"; exit 1; fi
mkdir -p "$RESULTS/$cl"
[[ -f "$RESULTS/$cl/sync.csv" ]] || echo "utc,alias,commit,plan_sha256,remote_dir" > "$RESULTS/$cl/sync.csv"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$alias,$commit,$plansha,$REMOTE_DIR" >> "$RESULTS/$cl/sync.csv"
echo "SYNC $cl: local HEAD ${commit:0:12} = cluster ~/$REMOTE_DIR (plan sha ${plansha:0:12}); recorded in ${RESULTS#$REPO/}/$cl/sync.csv"
