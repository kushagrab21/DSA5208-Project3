# Atlas environment for p3cg. Sourced by the generated PBS scripts (cluster/generated/atlas/*.pbs).
#
# Lecture 8: on Atlas, `source /app1/ebenv`, then `module avail` / `module load`, then compile.
# Module names are UNVERIFIED: run `source /app1/ebenv; module avail OpenMPI CMake` on the first login and set
# P3_MODULES here (or qsub -v P3_MODULES=...). The default loads EasyBuild's default OpenMPI (with its GCC).
# Atlas is CPU only, so there is no offload flavour here.

# Lecture 8: on Atlas, `source /app1/ebenv` first, then `module avail` / `module load`. Without it, PATH has the old
# /app1/centos6.3 mvapich2-1.9 (2013) mpicxx. P3_MODULES may name modules explicitly (set by apply_discovery.py after
# discover.sh); if it is empty the newest foss toolchain (GCC + OpenMPI) is chosen by pattern, else the newest OpenMPI.
if [[ -f "${P3_EBENV:-/app1/ebenv}" ]]; then
  # shellcheck disable=SC1090
  source "${P3_EBENV:-/app1/ebenv}"
fi
: "${P3_MODULES:=foss/2025b}"
if command -v module >/dev/null 2>&1; then
  module purge >/dev/null 2>&1 || true
  if [[ -z "$P3_MODULES" ]]; then
    P3_MODULES="$(module -t avail foss 2>&1 | grep -E '^foss/20[0-9]{2}[ab]$' | sort -V | tail -1)"
    [[ -n "$P3_MODULES" ]] || P3_MODULES="$(module -t avail OpenMPI 2>&1 | grep -E '^OpenMPI/' | sort -V | tail -1)"
  fi
  for m in $P3_MODULES; do module load "$m"; done
  echo "p3 env (atlas): loaded $(module -t list 2>&1 | grep -v ':$' | tr '\n' ' ')" >&2
fi
echo "p3 env (atlas): mpicxx=$(command -v mpicxx) ($(mpicxx --version 2>/dev/null | head -1))" >&2
case "$(command -v mpicxx)" in
  */centos6.3/*|*mvapich2-1.9*)
    echo "p3 env (atlas): ERROR the 2013 mvapich2-1.9 mpicxx is still first on PATH; no OpenMPI module loaded" >&2
    return 1 2>/dev/null || exit 1;;
esac

export P3_CLUSTER=atlas
export CXX_MPI="${CXX_MPI:-mpicxx}"
export P3_OMP_FLAGS="${P3_OMP_FLAGS:--fopenmp}"
export P3_MPIRUN="${P3_MPIRUN:-mpirun --bind-to none -x OMP_NUM_THREADS}"

# p3_launch RANKS RANKS_PER_NODE THREADS cmd...   (Open MPI syntax; for Intel MPI use: mpirun -n NP -ppn RPN
# -genv OMP_NUM_THREADS TH -genv I_MPI_PIN_DOMAIN omp ...). VERIFY with the --report-bindings output of the first job.
p3_launch() {
  local np="$1" rpn="$2" th="$3"
  shift 3
  OMP_NUM_THREADS="$th" OMP_PLACES=cores OMP_PROC_BIND=close \
    mpirun -np "$np" --map-by "ppr:${rpn}:node:PE=${th}" --bind-to core \
    ${P3_REPORT_BINDINGS:+--report-bindings} -x OMP_NUM_THREADS -x OMP_PLACES -x OMP_PROC_BIND -x P3_CLUSTER "$@"
}

# Test seam for cluster/ops/fake only (never set on a real cluster): the fake qsub replaces the MPI launch with a
# writer of TEST-DOUBLE rows, so the rest of the generated job script (job-start, timing gate, job-end) runs as is.
if [[ -n "${P3_FAKE_LAUNCH:-}" ]]; then p3_launch() { "$P3_FAKE_LAUNCH" "$@"; }; fi
