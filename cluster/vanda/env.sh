# Vanda environment for p3cg. Sourced by the generated PBS scripts (cluster/generated/vanda/*.pbs) on a compute node.
# Lecture 8: Vanda login nodes are VMs, so binaries are built inside jobs, on compute nodes.
#
# Two flavours (P3_FLAVOR, set by the job script):
#   cpu      EasyBuild foss toolchain (GCC + Open MPI) via /app1/ebenv: the same family and version as on Atlas
#            (foss/2025b: GCC 14.3.0, Open MPI 5.0.8), so the two clusters' numbers come from the same compiler
#            and MPI. No CMake module is loaded, so build.sh compiles with one mpicxx line, as it did on Atlas.
#   offload  nvhpc-hpcx-cuda12/26.1 (Lecture 12): nvc++ -mp=gpu for the OpenMP target build, HPC-X (CUDA-aware) MPI.
#            Built as bin/p3cg_offload* and qualified by validate.py on the GPU node before any GPU timing.
# What Atlas taught (12 Nov) and what this file does about it:
#   - compute nodes may lack python3 (atlas-validate 1040043, exit 127): CPU jobs load the Python of the foss
#     toolchain; GPU jobs use the system python3 or that Python; the job stops here if there is none;
#   - the node environment may inject an old libfabric through LD_PRELOAD (atlas-validate 1040044/1040045, "FABRIC_1.7
#     not found"): if LD_PRELOAD (or /etc/ld.so.preload) names a libfabric that is not the toolchain's, the toolchain's
#     goes first; what the loader resolves is logged either way;
#   - every choice is printed to the job log ("p3 env (vanda): ...").
# No `module purge`: Vanda loads `shared` by default, which may carry the /cm module path the nvhpc modules live in.

: "${P3_FLAVOR:=cpu}"
: "${P3_MODULES_CPU:=foss/2025b Python/3.13.5-GCCcore-14.3.0}"
: "${P3_MODULES_GPU:=nvhpc-hpcx-cuda12/26.1}"
: "${P3_PYTHON_FALLBACK:=Python/3.13.5-GCCcore-14.3.0}"

p3_log() { echo "p3 env (vanda/$P3_FLAVOR): $*" >&2; }
# Refusals are top-level `return`s (a `return` inside a function would only leave the function and let the job go on).

if [[ -f "${P3_EBENV:-/app1/ebenv}" ]]; then
  # shellcheck disable=SC1090
  source "${P3_EBENV:-/app1/ebenv}"
fi
if ! command -v module >/dev/null 2>&1; then p3_log "ERROR no module command on this node"; return 1 2>/dev/null || exit 1; fi
if [[ "$P3_FLAVOR" == "offload" ]]; then mods="$P3_MODULES_GPU"; else mods="$P3_MODULES_CPU"; fi
for m in $mods; do
  if ! module load "$m"; then p3_log "ERROR module load $m failed"; return 1 2>/dev/null || exit 1; fi
done
if [[ "$P3_FLAVOR" == "offload" ]] && ! command -v python3 >/dev/null 2>&1; then
  module load "$P3_PYTHON_FALLBACK" || true
fi
p3_log "loaded $(module -t list 2>&1 | grep -v ':$' | tr '\n' ' ')"

if ! command -v mpicxx >/dev/null 2>&1; then p3_log "ERROR no mpicxx after loading: $mods"; return 1 2>/dev/null || exit 1; fi
p3_log "mpicxx=$(command -v mpicxx) ($(mpicxx --version 2>/dev/null | grep -v '^$' | head -1))"
if ! command -v python3 >/dev/null 2>&1; then
  p3_log "ERROR no python3 on this node (the checks run inside jobs); set P3_PYTHON_FALLBACK"
  return 1 2>/dev/null || exit 1
fi
p3_log "python3=$(command -v python3) ($(python3 --version 2>&1))"

# libfabric defence (CPU flavour: Open MPI 5 from foss uses libfabric; HPC-X uses UCX).
if [[ -n "${EBROOTLIBFABRIC:-}" ]]; then
  # (never let this assignment fail: under the job's `set -e` a failing command substitution here ends the job)
  preload="${LD_PRELOAD:-} $(cat /etc/ld.so.preload 2>/dev/null | tr '\n' ' ' || true)"
  LD_LIBRARY_PATH="$(printf '%s' "${LD_LIBRARY_PATH:-}" | tr ':' '\n' | { grep -v -E '^/opt/amazon/efa' || true; } | paste -sd: -)"
  export LD_LIBRARY_PATH="$EBROOTLIBFABRIC/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  if printf '%s' "$preload" | grep -q 'libfabric' && ! printf '%s' "$preload" | grep -q "$EBROOTLIBFABRIC"; then
    for f in "$EBROOTLIBFABRIC/lib/libfabric.so.1" "$EBROOTLIBFABRIC/lib64/libfabric.so.1"; do
      if [[ -f "$f" ]]; then export LD_PRELOAD="$f${LD_PRELOAD:+:$LD_PRELOAD}"; break; fi
    done
    p3_log "a foreign libfabric is preloaded by the node ($preload): the toolchain's goes first"
  else
    p3_log "no foreign libfabric preloaded (LD_PRELOAD='${LD_PRELOAD:-}')"
  fi
  [[ -n "${EBROOTOPENMPI:-}" ]] && p3_log "libmpi resolves libfabric to: $(ldd "$EBROOTOPENMPI/lib/libmpi.so.40" 2>&1 \
    | grep -E 'fabric' | tr -s ' \t' ' ' | tr '\n' ';')"
fi

export P3_CLUSTER=vanda
export CXX_MPI="${CXX_MPI:-mpicxx}"
export P3_OMP_FLAGS="${P3_OMP_FLAGS:--fopenmp}"                    # GCC (foss); used only by the direct build
export P3_OFFLOAD_FLAGS="${P3_OFFLOAD_FLAGS:--mp=gpu -Minfo=mp}"    # nvc++; -Minfo=mp lists offloaded loops
# Vanda compute nodes call themselves GN-A40-075 while $PBS_NODEFILE lists gn-a40-075.stdct.loc, so the MPI launcher
# treats even its own node as remote and starts its daemon over ssh, where no module is loaded: "prted: command not
# found" (vanda-validate 1546488 and diagnostics 1546504/1546514, 12 Nov). Name the daemon by absolute path and forward
# the environment. Diagnostic 1546517 showed this works for 1 rank and for 4 ranks across 2 nodes. Daemons started this way
# get a fresh environment, so the solver's own inputs (P3_CLUSTER, PBS_JOBID: the only getenv calls in src/) are forwarded
# too; without them 1546532 qualified its binary as cluster=local.
if [[ -n "${EBROOTPRRTE:-}" && -x "$EBROOTPRRTE/bin/prted" ]]; then           # foss: Open MPI 5 + PRRTE
  P3_MPI_EXTRA="--prtemca prte_launch_agent $EBROOTPRRTE/bin/prted -x PATH -x LD_LIBRARY_PATH -x P3_CLUSTER -x PBS_JOBID"
else                                                                          # HPC-X / Open MPI 4: orted next to mpirun
  P3_MPI_EXTRA="--prefix $(dirname "$(dirname "$(command -v mpirun)")") -x PATH -x LD_LIBRARY_PATH -x P3_CLUSTER -x PBS_JOBID"
fi
export P3_MPI_EXTRA
echo "p3 env (vanda): mpirun extra: $P3_MPI_EXTRA" >&2
# checks/validate.py launcher: no pinning (it runs 1-8 ranks with 1-2 threads on the cores it was given).
export P3_MPIRUN="${P3_MPIRUN:-mpirun $P3_MPI_EXTRA --bind-to none -x OMP_NUM_THREADS}"

# p3_launch RANKS RANKS_PER_NODE THREADS cmd...   Open MPI syntax (foss Open MPI 5 and HPC-X): RANKS_PER_NODE ranks on
# each node, THREADS cores per rank, threads pinned to those cores. The first launch of each job prints the bindings.
# Open MPI will not bind one rank across two sockets ("Your job failed to map ... CPUs/rank: 72", vanda-1node-variants-layouts
# 1546588, 12 Nov): a rank whose threads exceed one socket's cores is mapped unbound, and OpenMP pins its threads
# (OMP_PLACES=cores, OMP_PROC_BIND=close). Cores per socket come from lscpu on the compute node itself.
p3_map_args() {
  local rpn="$1" th="$2" cps
  cps="$(lscpu 2>/dev/null | awk -F: '/^Core\(s\) per socket/{gsub(/ /,"",$2); print $2}' || true)"
  if [[ -n "$cps" && "$th" -gt "$cps" ]]; then echo "--map-by ppr:${rpn}:node --bind-to none"
  else echo "--map-by ppr:${rpn}:node:PE=${th} --bind-to core"; fi
}
p3_launch() {
  local np="$1" rpn="$2" th="$3"
  shift 3
  OMP_NUM_THREADS="$th" OMP_PLACES=cores OMP_PROC_BIND=close \
    mpirun $P3_MPI_EXTRA -np "$np" $(p3_map_args "$rpn" "$th") \
    ${P3_REPORT_BINDINGS:+--report-bindings} -x OMP_NUM_THREADS -x OMP_PLACES -x OMP_PROC_BIND -x P3_CLUSTER "$@"
}

# Test seam for cluster/ops/fake only (never set on a real cluster): the fake qsub replaces the MPI launch with a
# writer of TEST-DOUBLE rows, so the rest of the generated job script (job-start, timing gate, job-end) runs as is.
if [[ -n "${P3_FAKE_LAUNCH:-}" ]]; then p3_launch() { "$P3_FAKE_LAUNCH" "$@"; }; fi
