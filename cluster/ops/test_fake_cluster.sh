#!/usr/bin/env bash
# Exercises every cluster/ops script against a FAKE cluster (no network, no real PBS):
#   - "cluster home" = a temp directory; ssh/rsync replaced through P3_SSH/P3_RSYNC (cluster/ops/fake/);
#   - qsub/qstat/hpc/module/pbsnodes are stubs; the validation job runs FOR REAL (build + validate.py) in the fake
#     home; timed jobs run their generated PBS script with a fake launcher that writes TEST-DOUBLE rows;
#   - results, plans, generated scripts and logs go to the scratch directory (P3_RESULTS, P3_CONFIG, P3_GENERATED,
#     P3_LOGS), so nothing fabricated reaches results/ or figures/; the end of the test checks that.
# Usage: cluster/ops/test_fake_cluster.sh [scratch dir]   (the working tree must be committed: sync.sh refuses
# a dirty tree, and step 4 shows that).
set -o pipefail
OPS="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$OPS/../.." && pwd)"; cd "$REPO"
T="${1:-$(mktemp -d /tmp/p3fake.XXXX)}"; rm -rf "$T"; mkdir -p "$T"
export P3_FAKE_ROOT="$T/fake" P3_RESULTS="$T/results" P3_CONFIG="$T/config" P3_GENERATED="$T/generated" \
       P3_LOGS="$T/logs" P3_CLUSTER_DIR="$T/clusterdir" P3_SSH="$OPS/fake/fake_ssh.sh" P3_RSYNC="$OPS/fake/fake_rsync.sh"
mkdir -p "$P3_FAKE_ROOT/vanda/home" "$P3_CONFIG" "$P3_RESULTS"
cp config/run_plan.*.json "$P3_CONFIG/"; cp -R cluster "$P3_CLUSTER_DIR"
snap() { find results figures report config -type f -exec stat -f '%N %m %z' {} + 2>/dev/null | sort | shasum -a 256; }
before="$(snap)"
n=0
step() { n=$((n+1)); echo; echo "----- [$n] $1"; shift; echo "\$ $*"; "$@"; echo "(exit $?)"; }
setplan() { python3 - "$P3_CONFIG/run_plan.vanda.json" "$@" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
for kv in sys.argv[2:]:
    k, v = kv.split("=", 1)
    if k == "frozen": d["frozen"] = (v == "true")
    elif k == "rerun": d.setdefault("reruns", []).append({"job": v, "reason": "fake walltime kill in the test"})
open(p, "w").write(json.dumps(d, indent=1) + "\n")
print("  scratch plan:", ", ".join(sys.argv[2:]))
PY
}
echo "FAKE CLUSTER TEST  scratch=$T  repo HEAD=$(git rev-parse --short=12 HEAD)"

step "VPN dropped: the cluster cannot be reached" env P3_FAKE_DOWN=vanda cluster/ops/discover.sh vanda
step "discover (read-only probes)" cluster/ops/discover.sh vanda
disc="$(ls "$P3_RESULTS"/vanda/env/discover-*.txt | tail -1)"
step "apply_discovery: proposal and diff, nothing written" python3 scripts/apply_discovery.py "$disc"
step "apply_discovery --apply (writes the scratch plan and scratch env.sh only)" python3 scripts/apply_discovery.py "$disc" --apply
touch src/_dirty_test.tmp
step "sync refuses a dirty working tree" cluster/ops/sync.sh vanda
rm -f src/_dirty_test.tmp
step "sync" cluster/ops/sync.sh vanda
step "submit refuses a job that is not in the plan" cluster/ops/submit.sh vanda vanda-extra
step "submit refuses a timed job before a binary is qualified on the cluster" cluster/ops/submit.sh vanda vanda-calibrate
step "submit the validation job (accepted; the fake runs it for real: build + validate.py --qualify)" cluster/ops/submit.sh vanda vanda-validate
step "poll" cluster/ops/poll.sh vanda
step "fetch" cluster/ops/fetch.sh vanda
step "submit refuses a timed job while the plan is not frozen" cluster/ops/submit.sh vanda vanda-serial
step "submit the calibration job (allowed before the freeze; fake times x1.6)" env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-calibrate
step "poll" cluster/ops/poll.sh vanda
step "fetch: rows, status, recalibration" cluster/ops/fetch.sh vanda
setplan frozen=true
step "submit refuses: the plan was frozen locally but the cluster has the old plan" cluster/ops/submit.sh vanda vanda-4node
step "sync the frozen plan" cluster/ops/sync.sh vanda
step "submit vanda-4node (the fake kills it at the walltime halfway)" env FAKE_FAIL_JOBS=vanda-4node FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-4node
step "submit vanda-serial and leave it queued" env FAKE_QUEUE_ONLY=1 FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-serial
step "poll: one failed job, one queued" cluster/ops/poll.sh vanda
step "the queue moves (fake scheduler runs the queued job)" env P3_FAKE_ALIAS=vanda python3 "$OPS/fake/fakepbs.py" run-queued vanda
step "poll" cluster/ops/poll.sh vanda
step "fetch after the failure" cluster/ops/fetch.sh vanda
step "unfilled cells of the killed job, as an unplanned job to paste" python3 cluster/ops/opslib.py missing-cells --cluster vanda --job vanda-4node
step "qsub rejects the select syntax: nothing is recorded as submitted" env FAKE_QSUB_REJECT=mem= cluster/ops/submit.sh vanda vanda-2node
step "vanda-2node runs and then drops out of the PBS history" env FAKE_FORGET=1 FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-2node
step "poll: qstat no longer knows the job; the job's own start/end record is used" cluster/ops/poll.sh vanda
step "submit refuses to rerun vanda-4node without a recorded reason" cluster/ops/submit.sh vanda vanda-4node
setplan rerun=vanda-4node
step "sync the plan with the rerun reason" cluster/ops/sync.sh vanda
step "rerun vanda-4node (accepted)" env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-4node
step "poll" cluster/ops/poll.sh vanda
step "fetch: the rerun fills the 4-node cells" cluster/ops/fetch.sh vanda
after="$(snap)"
echo
echo "----- real results/, figures/, report/ and config/ unchanged by the test: $([[ "$before" == "$after" ]] && echo yes || echo NO)"
echo "----- fabricated rows stayed in $T/results (host FAKE-NODE): $(cat "$T"/results/vanda/*.fake-pbs.csv 2>/dev/null | grep -c FAKE-NODE) rows"
