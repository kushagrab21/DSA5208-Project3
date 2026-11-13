#!/usr/bin/env bash
# Copies the planning notes that live outside this repository into process/, so the repository keeps them too.
# The originals stay in ../circuit, ../assumption_drill and ../.application, and this copy is refreshed before each push.
# Left out: the course slides (the instructor's material), third-party papers downloaded for the drills, and the
# builder's raw session transcripts (../.application/worker/).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
top="$(dirname "$here")"
out="$here/process"
rm -rf "$out/circuit" "$out/assumption_drill" "$out/decision_log"
mkdir -p "$out/circuit" "$out/assumption_drill" "$out/decision_log"
cp "$top"/circuit/*.py "$top"/circuit/*.md "$top"/circuit/*.txt "$out/circuit/" 2>/dev/null || true
(cd "$top/assumption_drill" && find . -name '*.md' -not -path '*/sources/*' -print0 | xargs -0 -I{} rsync -R {} "$out/assumption_drill/")
cp "$top"/.application/state.md "$top"/.application/repo_transfer.md "$top"/.application/build-task-*.txt "$out/decision_log/"
cp "$top"/prior_circuits/CIRCUITS_EXTRACTED.md "$out/decision_log/circuits_from_projects_1_and_2.md"
echo "process notes copied: $(find "$out" -type f | wc -l | tr -d ' ') files"
