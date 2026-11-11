#!/usr/bin/env bash
# Builds the correct binary and the two planted-bug binaries used to qualify checks/validate.py.
#
#   scripts/build.sh            CPU build (MPI + OpenMP threads): bin/p3cg, bin/p3cg_bug1, bin/p3cg_bug2
#   scripts/build.sh offload    OpenMP target offload build (nvhpc on a Vanda GPU node; UNTESTED elsewhere):
#                               bin/p3cg_offload, bin/p3cg_offload_bug1, bin/p3cg_offload_bug2
#
# Uses CMake when it is available, otherwise one direct mpicxx line per binary (some cluster login environments have
# no CMake module). Set CXX_MPI to override the MPI compiler wrapper (default mpicxx).
set -euo pipefail
cd "$(dirname "$0")/.."
flavor="${1:-cpu}"
MPICXX="${CXX_MPI:-mpicxx}"
mkdir -p bin

suffix=""
cmake_extra=()
direct_omp=()
if [[ "$flavor" == "offload" ]]; then
  suffix="_offload"
  cmake_extra=(-DP3_OFFLOAD=ON -DP3_OFFLOAD_FLAGS="${P3_OFFLOAD_FLAGS:--mp=gpu}")
  direct_omp=(-DP3_OFFLOAD=1 ${P3_OFFLOAD_FLAGS:--mp=gpu})
elif [[ "$flavor" == "cpu" ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    omp_prefix="$(brew --prefix libomp 2>/dev/null || echo /opt/homebrew/opt/libomp)"
    direct_omp=(-Xpreprocessor -fopenmp -I"$omp_prefix/include" -L"$omp_prefix/lib" -lomp)
  else
    direct_omp=(${P3_OMP_FLAGS:--fopenmp})
  fi
else
  echo "usage: scripts/build.sh [cpu|offload]" >&2
  exit 2
fi

git_sha="$(git rev-parse --short=12 HEAD 2>/dev/null || true)"
if [[ -z "$git_sha" && -f SYNCED ]]; then git_sha="$(awk '$1=="commit"{print substr($2,1,12)"-synced"}' SYNCED)"; fi
git_sha="${git_sha:-unknown}"
srcs=(src/main.cpp src/grid.cpp src/halo.cpp src/kernels.cpp src/cg.cpp src/record.cpp)

for bug in 0 1 2; do
  name="p3cg${suffix}"
  [[ "$bug" != "0" ]] && name="${name}_bug${bug}"
  if command -v cmake >/dev/null 2>&1 && [[ "${P3_NO_CMAKE:-0}" != "1" ]]; then
    bdir="_build/${flavor}_bug${bug}"
    mkdir -p _build
    cmake -S . -B "$bdir" -DCMAKE_BUILD_TYPE=Release -DMPI_CXX_COMPILER="$(command -v "$MPICXX")" \
      -DPLANT_HALO_BUG="$bug" ${cmake_extra[@]+"${cmake_extra[@]}"} >"$bdir.configure.log" 2>&1 || {
        cat "$bdir.configure.log" >&2; exit 1; }
    cmake --build "$bdir" -j >"$bdir.build.log" 2>&1 || { cat "$bdir.build.log" >&2; exit 1; }
    cp "$bdir/p3cg" "bin/$name"
  else
    "$MPICXX" -O3 -std=c++17 -DPLANT_HALO_BUG="$bug" -DP3_GIT_SHA="\"$git_sha\"" ${direct_omp[@]+"${direct_omp[@]}"} \
      "${srcs[@]}" -o "bin/$name"
  fi
  echo "built bin/$name  sha256=$(bin/$name --version | sed -n 's/.*sha256=\([0-9a-f]*\).*/\1/p')"
done
