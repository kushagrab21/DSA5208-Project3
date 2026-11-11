# Sourced by the cluster/ops scripts. Transport is replaceable for tests:
#   P3_SSH    command used as `$P3_SSH ALIAS cmd...`      (default: ssh -o BatchMode=yes -o ConnectTimeout=20)
#   P3_RSYNC  command used as `$P3_RSYNC -a SRC DST`       (default: rsync; ALIAS:path addresses the cluster)
#   P3_REMOTE_DIR  checkout on the cluster, relative to the cluster home (default: p3)
#   P3_RESULTS / P3_CONFIG / P3_GENERATED / P3_LOGS  local folders (defaults: results, config, cluster/generated,
#                  cluster/logs in the repository; the fake-cluster test points them at a scratch directory)
set -eo pipefail
OPS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$OPS/../.." && pwd)"
P3_SSH="${P3_SSH:-ssh -o BatchMode=yes -o ConnectTimeout=20}"
P3_RSYNC="${P3_RSYNC:-rsync}"
REMOTE_DIR="${P3_REMOTE_DIR:-p3}"
RESULTS="${P3_RESULTS:-$REPO/results}"
GENERATED="${P3_GENERATED:-$REPO/cluster/generated}"
LOGS="${P3_LOGS:-$REPO/cluster/logs}"
PY="${PYTHON:-python3}"

usage_alias() { [[ -n "${1:-}" ]] || { echo "usage: $(basename "$0") <atlas8|vanda> $2" >&2; exit 2; }; }
cluster_of() { "$PY" "$OPS/opslib.py" cluster "$1"; }

# remote ALIAS [args...] < script   runs the script on the login node in a login shell (modules, PBS on PATH)
remote() {
  local alias="$1"; shift
  local rc=0
  $P3_SSH "$alias" bash -l -s -- "$@" || rc=$?
  if [[ $rc -eq 255 ]]; then
    echo "cannot reach $alias (ssh exit 255): connect the NUS VPN, then check that 'ssh $alias true' works" \
         "without a password. Jobs already queued keep running; poll.sh and fetch.sh catch up later." >&2
  fi
  return $rc
}

rsync_or_explain() {
  local rc=0
  $P3_RSYNC "$@" || rc=$?
  if [[ $rc -eq 255 || $rc -eq 12 ]]; then
    echo "rsync could not reach the cluster (exit $rc): check the NUS VPN and the SSH key" >&2
  fi
  return $rc
}
