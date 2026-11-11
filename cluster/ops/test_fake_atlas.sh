#!/usr/bin/env bash
# Rehearses tonight's Atlas sequence on a FAKE Atlas (cluster/ops/fake; nothing leaves this machine) and tests the
# fixes for the first real session's findings:
#   (a) queue choice: ACL queues the user is not in, disabled/route/routing-only queues, min cores and per-user caps;
#   (b) the module environment: /app1/ebenv must be sourced; the 2013 mvapich2 mpicxx first on PATH is refused.
# The validation job runs FOR REAL in the fake home (build + validate.py); calibration rows are TEST DOUBLES.
set -o pipefail
OPS="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$OPS/../.." && pwd)"; cd "$REPO"
T="${1:-$(mktemp -d /tmp/p3atlas.XXXX)}"; rm -rf "$T"; mkdir -p "$T"
export P3_FAKE_ROOT="$T/fake" P3_RESULTS="$T/results" P3_CONFIG="$T/config" P3_GENERATED="$T/generated" \
       P3_LOGS="$T/logs" P3_CLUSTER_DIR="$T/clusterdir" P3_SSH="$OPS/fake/fake_ssh.sh" P3_RSYNC="$OPS/fake/fake_rsync.sh"
mkdir -p "$P3_CONFIG" "$P3_RESULTS"; cp config/run_plan.*.json "$P3_CONFIG/"; cp -R cluster "$P3_CLUSTER_DIR"
"$OPS/fake/atlas/setup.sh"
snap() { find results figures report config -type f -exec stat -f '%N %m %z' {} + 2>/dev/null | sort | shasum -a 256; }
before="$(snap)"; n=0
step() { n=$((n+1)); echo; echo "----- [$n] $1"; shift; echo "\$ $*"; "$@"; echo "(exit $?)"; }
echo "FAKE ATLAS TEST  scratch=$T  repo HEAD=$(git rev-parse --short=12 HEAD)"

step "discover the fake Atlas (sources ebenv, one module query per name, records the user and node pools)" \
  cluster/ops/discover.sh atlas8
disc="$(ls "$P3_RESULTS"/atlas/env/discover-*.txt | tail -1)"
step "what discovery saw about modules" sed -n '/^=== module_env ===/,/^=== hpc_queue_limit ===/p' "$disc"
step "apply_discovery: ACL and route queues refused, parallel and serial chosen, every job checked" \
  python3 scripts/apply_discovery.py "$disc"
mkdir -p "$T/oldconfig"; cp "$P3_CONFIG"/run_plan.*.json "$T/oldconfig/"
git show 733d697:config/run_plan.atlas.json > "$T/oldconfig/run_plan.atlas.json"
step "the OLD Atlas plan (24-core nodes, 8- to 264-core jobs) against the same queues: refused job by job" \
  env P3_CONFIG="$T/oldconfig" python3 scripts/apply_discovery.py "$disc"
step "the job environment WITHOUT ebenv: the 2013 mvapich2 mpicxx is refused" \
  bash -c "printf 'export P3_EBENV=/nonexistent; source %s/cluster/atlas/env.sh && echo env-ok\n' '$REPO' | $P3_SSH atlas8 bash -s"
step "the job environment WITH ebenv: newest foss loaded, its mpicxx first" \
  bash -c "printf 'source %s/cluster/atlas/env.sh && echo env-ok\n' '$REPO' | $P3_SSH atlas8 bash -s"
step "the fake qsub enforces queue limits like PBS: 8 cores in parallel, and the ACL queue hpc6a" \
  bash -c "printf '#PBS -q parallel\n#PBS -l select=1:ncpus=8:mpiprocs=8\ntrue\n' > $P3_FAKE_ROOT/atlas8/home/s8.pbs; printf '#PBS -q hpc6a\n#PBS -l select=1:ncpus=192:mpiprocs=192\ntrue\n' > $P3_FAKE_ROOT/atlas8/home/s192.pbs; printf 'qsub s8.pbs; echo \"exit \$?\"; qsub s192.pbs; echo \"exit \$?\"\n' | $P3_SSH atlas8 bash -s"
step "apply the proposal (scratch plan and env.sh only)" python3 scripts/apply_discovery.py "$disc" --apply
step "run_plan check atlas" python3 checks/run_plan.py check --plan atlas
step "sync" cluster/ops/sync.sh atlas8
step "submit refuses a timed job before a binary is qualified on Atlas" cluster/ops/submit.sh atlas8 atlas-1node-scaling
step "submit atlas-validate (the fake runs it for real: ebenv, foss, build, validate.py --qualify)" \
  cluster/ops/submit.sh atlas8 atlas-validate
step "the job log: what env.sh loaded" bash -c "grep -h 'p3 env (atlas)' $P3_FAKE_ROOT/atlas8/home/p3/cluster/logs/*"
step "poll" cluster/ops/poll.sh atlas8
step "fetch" cluster/ops/fetch.sh atlas8
step "submit refuses a timed job while the plan is not frozen" cluster/ops/submit.sh atlas8 atlas-serial
step "submit atlas-calibrate (allowed before the freeze; fake times x1.3)" \
  env FAKE_SPEED=1.3 cluster/ops/submit.sh atlas8 atlas-calibrate
step "poll" cluster/ops/poll.sh atlas8
step "fetch: rows, status, recalibration" cluster/ops/fetch.sh atlas8
after="$(snap)"
echo; echo "----- real results/, figures/, report/ and config/ unchanged by the test: $([[ "$before" == "$after" ]] && echo yes || echo NO)"
