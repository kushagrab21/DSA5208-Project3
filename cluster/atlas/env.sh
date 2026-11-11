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
: "${P3_MODULES:=foss/2025b Python/3.13.5-GCCcore-14.3.0}"
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

# Atlas compute nodes (cnode-*) carry an older Amazon EFA libfabric (/opt/amazon/efa/lib64) that was found before the
# toolchain's libfabric: atlas-validate 1040044.venus01 (12 Nov) failed with "libfabric.so.1: version `FABRIC_1.7' not
# found (required by .../OpenMPI/5.0.8-GCC-14.3.0/lib/libmpi.so.40)". Keep the EFA directory out of the search path and
# put the toolchain's libfabric first; print what the dynamic loader will use, for the job log.
if [[ -n "${EBROOTLIBFABRIC:-}" ]]; then
  LD_LIBRARY_PATH="$(printf '%s' "${LD_LIBRARY_PATH:-}" | tr ':' '\n' | grep -v -E '^/opt/amazon/efa' | paste -sd: -)"
  for d in "$EBROOTLIBFABRIC/lib64" "$EBROOTLIBFABRIC/lib"; do [[ -d "$d" ]] && LD_LIBRARY_PATH="$d:$LD_LIBRARY_PATH"; done
  export LD_LIBRARY_PATH
  # 1040045.venus01: the old EFA libfabric was still loaded with this path in place, so it is loaded before the search
  # (/etc/ld.so.preload on the compute nodes). LD_PRELOAD is applied first, so the toolchain's libfabric.so.1 owns the soname.
  for f in "$EBROOTLIBFABRIC/lib/libfabric.so.1" "$EBROOTLIBFABRIC/lib64/libfabric.so.1"; do
    if [[ -f "$f" ]]; then export LD_PRELOAD="$f${LD_PRELOAD:+:$LD_PRELOAD}"; break; fi
  done
fi
echo "p3 env (atlas): LD_PRELOAD=${LD_PRELOAD:-}; /etc/ld.so.preload: $(tr '\n' ' ' < /etc/ld.so.preload 2>/dev/null)" >&2
echo "p3 env (atlas): libfabric search: $(printf '%s' "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -n -E 'fabric|efa' | head -3 | tr '\n' ' '); ld.so.conf efa: $(grep -l efa /etc/ld.so.conf.d/* 2>/dev/null | tr '\n' ' ')" >&2

[[ -n "${EBROOTOPENMPI:-}" ]] && echo "p3 env (atlas): libmpi resolves libfabric to: $(ldd "$EBROOTOPENMPI/lib/libmpi.so.40" 2>&1 | grep -E 'fabric' | head -2 | tr -s ' \t' ' ')" >&2

# Compute nodes have no system python3 (atlas-validate 1040043.venus01, 12 Nov: "python3: command not found");
# the checks run inside jobs, so a Python module built on the same GCCcore as foss is loaded above.
if ! command -v python3 >/dev/null 2>&1; then
  echo "p3 env (atlas): ERROR no python3 on this node; load a Python/*-GCCcore module via P3_MODULES" >&2
  return 1 2>/dev/null || exit 1
fi
echo "p3 env (atlas): python3=$(command -v python3) ($(python3 --version 2>&1))" >&2

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
