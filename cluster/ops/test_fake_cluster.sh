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
"$OPS/fake/vanda/setup.sh"   # fake /app1/ebenv: foss/2025b + Python, nvhpc-hpcx-cuda12
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
BUD=(--budget-cpu 1000 --budget-gpu 50 --budget-source "fake amgr login")
step "apply_discovery without a budget: routes resolved, the amgr-login budget flagged" python3 scripts/apply_discovery.py "$disc"
step "apply_discovery with the budget from the command line --apply (scratch plan and env.sh only)" \
  python3 scripts/apply_discovery.py "$disc" "${BUD[@]}" --apply
ENVT="$REPO/cluster/vanda/env.sh"
step "env (cpu): foss + Python loaded, no foreign libfabric preloaded" \
  bash -c "printf 'set -eo pipefail; source %s && echo env-ok\n' '$ENVT' | $P3_SSH vanda bash -s"
step "env (cpu) on a node that preloads the EFA libfabric: the toolchain's goes first, and the log says so" \
  bash -c "printf 'set -eo pipefail; export LD_PRELOAD=\"/opt/amazon/efa/lib64/libfabric.so.1 /lib64/libefa.so.1\"; source %s && echo \"LD_PRELOAD now: \$LD_PRELOAD\"\n' '$ENVT' | $P3_SSH vanda bash -s"
step "env (cpu) on a node without python3: refused" \
  bash -c "printf 'set -eo pipefail; command() { [[ \"\$2\" == python3 ]] && return 1; builtin command \"\$@\"; }; source %s && echo env-ok\n' '$ENVT' | $P3_SSH vanda bash -s"
step "launcher mapping: a normal job binds ranks to cores; a shared-node job (P3_BIND=none) maps per node, unbound" \
  bash -c "printf 'set -eo pipefail; source %s; echo \"normal: \$(p3_map_args 32 1)\"; export P3_BIND=none; echo \"P3_BIND=none: \$(p3_map_args 32 1)\"\n' '$ENVT' | $P3_SSH vanda bash -s"
step "env (offload): nvhpc-hpcx-cuda12 loaded" \
  bash -c "printf 'set -eo pipefail; export P3_FLAVOR=offload; source %s && echo env-ok\n' '$ENVT' | $P3_SSH vanda bash -s"
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
step "the generated 4-node script: project, no queue, select with ompthreads and memory" \
  bash -c "python3 checks/run_plan.py pbs --plan vanda --job vanda-4node >/dev/null; grep -E '^#PBS -(P|q|l)|^# queue' $P3_GENERATED/vanda/vanda-4node.pbs"
step "submit vanda-gpu: offload build and its OWN qualification on the (fake) GPU node, then the GPU cells" \
  env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-gpu
step "the GPU job log: environment and qualification" \
  bash -c "grep -h -E 'p3 env \\(vanda/offload|QUALIFICATION|VALIDATED BINARY|TIMING GATE' $P3_FAKE_ROOT/vanda/home/p3/cluster/logs/p3-vanda-gpu.o*"
step "submit refuses vanda-256spread (Poisson + graph cells) while bin/p3graph is not qualified: a mixed job needs both" \
  env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-256spread
step "submit vanda-gpu1 (amendment gpu-split: half a GPU node, 1 GPU x 36 cores; its own offload build + qualification, then the 1-GPU cells)" \
  env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-gpu1
step "the gpu1 script asks for the hpc gpu sample shape, and its log shows the qualification and the gate" \
  bash -c "grep -h '^#PBS -l' $P3_GENERATED/vanda/vanda-gpu1.pbs; grep -h -E 'QUALIFICATION|TIMING GATE' $P3_FAKE_ROOT/vanda/home/p3/cluster/logs/p3-vanda-gpu1.o*"
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
# ---- the graph extension: its own qualification job, then a timed graph job
graph_fixtures() {  # SNAP-shaped raw files in the fake home: the two real local datasets, and com-amazon's files
  # standing in for the four large graphs (the fake never downloads)
  local raw="$P3_FAKE_ROOT/vanda/home/p3data/raw"; mkdir -p "$raw"
  printf 'utc\tname\tfile\turl\tbytes\tsha256\n' > "$raw/SOURCES.tsv"
  put() { cp "$REPO/data/raw/$1" "$raw/$2"; printf '%s\t%s\t%s\t%s\t%s\t%s\n' FAKE "$3" "$2" "fixture:$1" \
            "$(wc -c < "$raw/$2" | tr -d ' ')" "$(shasum -a 256 "$raw/$2" | cut -d' ' -f1)" >> "$raw/SOURCES.tsv"; }
  put email-Eu-core.txt.gz email-Eu-core.txt.gz email-Eu-core
  put email-Eu-core-department-labels.txt.gz email-Eu-core-department-labels.txt.gz email-Eu-core
  for d in com-amazon com-dblp com-youtube com-lj com-orkut; do
    put com-amazon.ungraph.txt.gz $d.ungraph.txt.gz $d; put com-amazon.top5000.cmty.txt.gz $d.top5000.cmty.txt.gz $d
  done
  echo "  fixtures in $raw: $(ls "$raw" | grep -c gz) files"
}
if [[ -f data/raw/com-amazon.ungraph.txt.gz && -f data/raw/email-Eu-core.txt.gz ]]; then
  step "graph fixtures in the fake home (p3data/raw; com-amazon stands in for the four large graphs)" graph_fixtures
  step "submit refuses a graph timed job: no p3graph qualified on the cluster (the p3cg qualification does not count)" \
    cluster/ops/submit.sh vanda vanda-graph-sweep
  step "submit vanda-graph-prep (the fake runs it for real: build graph, convert six datasets, validate_graph.py --qualify, seed lists)" \
    cluster/ops/submit.sh vanda vanda-graph-prep
  step "the graph-prep job log: conversion, qualification, gate-free seeds" \
    bash -c "grep -h -E 'p3convert email|p3convert com-orkut|VERDICT|QUALIFICATION|VALIDATED BINARY' $P3_FAKE_ROOT/vanda/home/p3/cluster/logs/p3g-prep.o*"
  step "poll" cluster/ops/poll.sh vanda
  step "fetch: the G1;G2 qualification and the seed lists come back" cluster/ops/fetch.sh vanda
  step "submit vanda-graph-sweep (accepted; TEST-DOUBLE graph rows)" env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-graph-sweep
  step "poll" cluster/ops/poll.sh vanda
  step "fetch" cluster/ops/fetch.sh vanda
  step "status: graph-sweep filled, graph rows from the qualified p3graph only" \
    bash -c "python3 checks/run_plan.py status --plan vanda | grep -E 'graph-|GRADED|qualified'"
  step "submit vanda-256spread (amendment spread256: 8 x 32 cores on shared nodes, place=scatter, unbound; both programs qualified now)" \
    env FAKE_SPEED=1.6 cluster/ops/submit.sh vanda vanda-256spread
  step "the spread script: select, place, P3_BIND=none, both timing gates, rows tagged with the placement" \
    bash -c "grep -h -E '^#PBS -l|P3_BIND|timing_gate' $P3_GENERATED/vanda/vanda-256spread.pbs; grep -c '@shared-8x32' $P3_GENERATED/vanda/vanda-256spread.pbs"
  step "poll" cluster/ops/poll.sh vanda
  step "fetch: the 256-core shared-node cells fill (their 288-core partners may still wait)" \
    bash -c "cluster/ops/fetch.sh vanda >/dev/null; python3 checks/run_plan.py status --plan vanda | grep -E '^  (strong|weak|graph-strong) |256spread'"
  step "the generated graph script: timing gate with the graph cases, records to *.graph.csv" \
    bash -c "grep -E 'timing_gate|GREC=|P3_DATA=' $P3_GENERATED/vanda/vanda-graph-sweep.pbs"
else
  echo; echo "----- graph steps skipped: data/raw has no email-Eu-core and com-amazon files (scripts/fetch_snap.sh NAME \$PWD/data)"
fi
after="$(snap)"
echo
echo "----- real results/, figures/, report/ and config/ unchanged by the test: $([[ "$before" == "$after" ]] && echo yes || echo NO)"
echo "----- fabricated rows stayed in $T/results (host FAKE-NODE): $(cat "$T"/results/vanda/*.fake-pbs.csv 2>/dev/null | grep -c FAKE-NODE) rows"
