#!/usr/bin/env bash
# discover.sh <atlas8|vanda>: read-only probes on the login node -> results/<cluster>/env/discover-<utc>.txt
# Nothing on the cluster is changed. Next step: python3 scripts/apply_discovery.py <that file>
source "$(dirname "$0")/common.sh"
usage_alias "${1:-}" ""
alias="$1"; cl="$(cluster_of "$alias")"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$RESULTS/$cl/env/discover-$stamp.txt"
mkdir -p "$(dirname "$out")"
remote "$alias" "$cl" > "$out.part" <<'EOS'
cl="$1"
sec() { echo; echo "=== $1 ==="; }
try() { if command -v "$1" >/dev/null 2>&1; then "$@" 2>&1 || true; else echo "(not available: $1)"; fi; }
sec host; hostname; uname -a; date -u
sec cpu; try lscpu | head -40; echo "nproc: $(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN)"
sec memory; try free -g
sec tools
for t in python3 mpicxx mpirun cmake qsub qstat module hpc gstat pbsnodes sha256sum rsync; do
  printf '%-10s %s\n' "$t" "$(command -v "$t" 2>/dev/null || echo missing)"
done
python3 --version 2>&1 || true
sec qstat_Q; try qstat -Q
sec qstat_Qf; try qstat -Qf
sec gstat; try gstat | head -80
sec pbsnodes
if command -v pbsnodes >/dev/null 2>&1; then
  pbsnodes -a 2>&1 | grep -E '^[^[:space:]]|resources_available\.(ncpus|ngpus|mem|Qlist)|^[[:space:]]+state =' | head -400
else echo "(not available: pbsnodes)"; fi
sec hpc_project; try hpc project
sec hpc_quota; try hpc quota
sec hpc_space; try hpc space
sec module_avail
[ -f /app1/ebenv ] && source /app1/ebenv >/dev/null 2>&1   # Atlas: EasyBuild environment (Lecture 8)
{ module -t avail 2>&1 || echo "(module not available)"; } |
  grep -iE 'gcc|intel|nvhpc|openmpi|mpich|impi|mvapich|hpcx|cmake|python|cuda|llvm|clang|foss|gompi|not available' |
  sort -u | head -300
if [ "$cl" = vanda ]; then sec hpc_cpu; try hpc cpu; sec hpc_gpu; try hpc gpu; fi
sec end
EOS
mv "$out.part" "$out"
n=$(grep -c '^=== ' "$out" || true)
echo "DISCOVER $cl: $n sections -> ${out#$REPO/}"
grep -E '^=== (host|qstat_Q|hpc_project) ===' -A3 "$out" | grep -v '^--$' | sed 's/^/  /'
echo "next: python3 scripts/apply_discovery.py ${out#$REPO/}   (prints a diff; nothing is written without --apply)"
