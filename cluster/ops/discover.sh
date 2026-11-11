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
sec user; echo "user: $(id -un)"; echo "groups: $(id -Gn)"
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
  pbsnodes -a 2>&1 | grep -E '^[^[:space:]]|resources_available\.(ncpus|ngpus|mem|Qlist|node_pool)|^[[:space:]]+state =|queue =' | head -3000
else echo "(not available: pbsnodes)"; fi
sec hpc_project; try hpc project
sec hpc_quota; try hpc quota
sec hpc_space; try hpc space
sec module_env
eb="${P3_EBENV:-/app1/ebenv}"   # Atlas: EasyBuild environment, needed before module avail/load (Lecture 8)
if [ -f "$eb" ]; then
  source "$eb" >/dev/null 2>&1 && echo "ebenv: sourced $eb" || echo "ebenv: $eb FAILED"
else echo "ebenv: no $eb here"; fi
echo "MODULEPATH=$MODULEPATH"
echo "default mpicxx: $(command -v mpicxx 2>/dev/null || echo none)"
echo "cmake: $( { cmake --version 2>/dev/null || echo none; } | head -1)"
echo "loaded by default:"; module -t list 2>&1 | sed 's/^/  /'
sec module_avail
# One query per name (no substring filter, no truncation): the newest toolchains must not fall off a capped list.
for name in foss gompi OpenMPI GCC GCCcore CMake Python nvhpc nvhpc-hpcx-cuda12 nvhpc-hpcx mvapich2 intel iimpi; do
  module -t avail "$name" 2>&1 | grep -E "^$name/" || true
done | sort -u
if [ "$cl" = vanda ]; then sec hpc_cpu; try hpc cpu; sec hpc_gpu; try hpc gpu; fi
if [ "$cl" = atlas ]; then  # Atlas's hpc has different options (help pages, read-only)
  sec hpc_queue_limit; try hpc queue limit; sec hpc_cores; try hpc cores; sec hpc_mpi; try hpc mpi
fi
sec end
EOS
mv "$out.part" "$out"
n=$(grep -c '^=== ' "$out" || true)
echo "DISCOVER $cl: $n sections -> ${out#$REPO/}"
grep -E '^=== (host|qstat_Q|hpc_project) ===' -A3 "$out" | grep -v '^--$' | sed 's/^/  /'
echo "next: python3 scripts/apply_discovery.py ${out#$REPO/}   (prints a diff; nothing is written without --apply)"
