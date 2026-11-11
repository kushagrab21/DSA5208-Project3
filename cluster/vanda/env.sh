# Vanda environment for p3cg. Sourced by the generated PBS scripts (cluster/generated/vanda/*.pbs) on a compute node.
#
# Lecture 8: Vanda login nodes are VMs, so compile on a compute node (the "vanda-validate" job builds the binaries).
# Lecture 12: CUDA-aware MPI via `module load nvhpc-hpcx-cuda12/26.1` (recommended).
# Module names other than that one are UNVERIFIED: check `module avail` on the first login and set them here or in
# the environment before qsub (qsub -v P3_MODULES_CPU=...).

# CPU build/run modules. nvhpc-hpcx provides mpicxx (nvc++ + HPC-X Open MPI); nvc++ uses -mp for OpenMP threads.
: "${P3_MODULES_CPU:=nvhpc-hpcx-cuda12/26.1}"
# GPU (offload) build/run modules.
: "${P3_MODULES_GPU:=nvhpc-hpcx-cuda12/26.1}"
: "${P3_FLAVOR:=cpu}"

if command -v module >/dev/null 2>&1; then
  module purge >/dev/null 2>&1 || true
  if [[ "$P3_FLAVOR" == "offload" ]]; then mods="$P3_MODULES_GPU"; else mods="$P3_MODULES_CPU"; fi
  for m in $mods; do module load "$m"; done
fi

export P3_CLUSTER=vanda
export CXX_MPI="${CXX_MPI:-mpicxx}"
export P3_OMP_FLAGS="${P3_OMP_FLAGS:--mp}"            # nvc++: -mp (CPU threads); GCC would be -fopenmp
export P3_OFFLOAD_FLAGS="${P3_OFFLOAD_FLAGS:--mp=gpu -Minfo=mp}" # nvc++ offload; -Minfo=mp lists offloaded loops in the build log
# checks/validate.py launcher: no pinning (it runs 1-8 ranks with 1-2 threads on the cores it was given).
export P3_MPIRUN="${P3_MPIRUN:-mpirun --bind-to none -x OMP_NUM_THREADS}"

# p3_launch RANKS RANKS_PER_NODE THREADS cmd...
# Open MPI (HPC-X) syntax: RANKS_PER_NODE ranks on each node, THREADS cores per rank, threads pinned to those cores.
# VERIFY in the first job's log: the first launch of each job prints --report-bindings.
p3_launch() {
  local np="$1" rpn="$2" th="$3"
  shift 3
  OMP_NUM_THREADS="$th" OMP_PLACES=cores OMP_PROC_BIND=close \
    mpirun -np "$np" --map-by "ppr:${rpn}:node:PE=${th}" --bind-to core \
    ${P3_REPORT_BINDINGS:+--report-bindings} -x OMP_NUM_THREADS -x OMP_PLACES -x OMP_PROC_BIND -x P3_CLUSTER "$@"
}
