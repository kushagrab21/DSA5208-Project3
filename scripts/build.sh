#!/usr/bin/env bash
# Builds the correct binary and the two planted-bug binaries used to qualify checks/validate.py.
#
#   scripts/build.sh            CPU build (MPI + OpenMP threads): bin/p3cg, bin/p3cg_bug1, bin/p3cg_bug2
#   scripts/build.sh offload    OpenMP target offload build (nvhpc on a Vanda GPU node; UNTESTED elsewhere):
#                               bin/p3cg_offload, bin/p3cg_offload_bug1, bin/p3cg_offload_bug2
#   scripts/build.sh graph      the graph extension (CPU): bin/p3graph, bin/p3graph_bug1 (planted ghost bug, for
#                               checks/validate_graph.py) and bin/p3convert. Touches no p3cg binary, so a graph job
#                               can run while the Poisson binaries already qualified on a cluster stay as they are.
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
# A start-up hang on one GPU node (vanda-gpu1 1547695 on GN-A40-027, 12 Nov: linked, then `--version` never returned; 22 min
# walltime, 8 s CPU) is turned into a fast, visible failure: every --version call below has a 120 s timeout. The same binary
# started in 0-5 s five ways on GN-A40-040 (diagnostic 1547817).
if [[ "$flavor" == "offload" ]]; then
  suffix="_offload"
  cmake_extra=(-DP3_OFFLOAD=ON -DP3_OFFLOAD_FLAGS="${P3_OFFLOAD_FLAGS:--mp=gpu}")
  direct_omp=(-DP3_OFFLOAD=1 ${P3_OFFLOAD_FLAGS:--mp=gpu})
elif [[ "$flavor" == "cpu" || "$flavor" == "graph" ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    omp_prefix="$(brew --prefix libomp 2>/dev/null || echo /opt/homebrew/opt/libomp)"
    direct_omp=(-Xpreprocessor -fopenmp -I"$omp_prefix/include" -L"$omp_prefix/lib" -lomp)
  else
    direct_omp=(${P3_OMP_FLAGS:--fopenmp})
  fi
else
  echo "usage: scripts/build.sh [cpu|offload|graph]" >&2
  exit 2
fi

# CMake only if >= 3.16 (CMakeLists.txt minimum); otherwise one direct mpicxx line per binary.
use_cmake=0
if command -v cmake >/dev/null 2>&1 && [[ "${P3_NO_CMAKE:-0}" != "1" ]]; then
  cv="$(cmake --version | head -1 | sed 's/[^0-9.]*\([0-9][0-9.]*\).*/\1/')"
  if [[ "$(printf '%s\n3.16\n' "$cv" | sort -V | head -1)" == "3.16" ]]; then use_cmake=1
  else echo "build.sh: cmake $cv < 3.16, compiling directly with $MPICXX" >&2; fi
fi
git_sha="$(git rev-parse --short=12 HEAD 2>/dev/null || true)"
if [[ -z "$git_sha" && -f SYNCED ]]; then git_sha="$(awk '$1=="commit"{print substr($2,1,12)"-synced"}' SYNCED)"; fi
git_sha="${git_sha:-unknown}"
srcs=(src/main.cpp src/grid.cpp src/halo.cpp src/kernels.cpp src/cg.cpp src/record.cpp)

if [[ "$flavor" == "graph" ]]; then
  gsrcs=(src/graph/graph_main.cpp src/graph/dcsr.cpp src/graph/label.cpp src/kernels.cpp src/grid.cpp src/record.cpp)
  for bug in 0 1; do
    name="p3graph"
    [[ "$bug" != "0" ]] && name="${name}_bug${bug}"
    if [[ "$use_cmake" == "1" ]]; then
      bdir="_build/graph_bug${bug}"
      mkdir -p _build
      cmake -S . -B "$bdir" -DCMAKE_BUILD_TYPE=Release -DMPI_CXX_COMPILER="$(command -v "$MPICXX")" \
        -DPLANT_GHOST_BUG="$bug" >"$bdir.configure.log" 2>&1 || { cat "$bdir.configure.log" >&2; exit 1; }
      targets=(--target p3graph)
      [[ "$bug" == "0" ]] && targets+=(--target p3convert)
      cmake --build "$bdir" -j "${targets[@]}" >"$bdir.build.log" 2>&1 || { cat "$bdir.build.log" >&2; exit 1; }
      cp "$bdir/p3graph" "bin/$name"
      [[ "$bug" == "0" ]] && cp "$bdir/p3convert" bin/p3convert
    else
      "$MPICXX" -O3 -std=c++17 -DPLANT_GHOST_BUG="$bug" -DP3_GIT_SHA="\"$git_sha\"" \
        ${direct_omp[@]+"${direct_omp[@]}"} "${gsrcs[@]}" -o "bin/$name"
      [[ "$bug" == "0" ]] && "$MPICXX" -O3 -std=c++17 src/graph/convert.cpp -o bin/p3convert
    fi
    echo "built bin/$name  sha256=$(timeout 120 bin/$name --version | sed -n 's/.*sha256=\([0-9a-f]*\).*/\1/p')"
  done
  echo "built bin/p3convert"
  exit 0
fi

for bug in 0 1 2; do
  name="p3cg${suffix}"
  [[ "$bug" != "0" ]] && name="${name}_bug${bug}"
  if [[ "$use_cmake" == "1" ]]; then
    bdir="_build/${flavor}_bug${bug}"
    mkdir -p _build
    cmake -S . -B "$bdir" -DCMAKE_BUILD_TYPE=Release -DMPI_CXX_COMPILER="$(command -v "$MPICXX")" \
      -DPLANT_HALO_BUG="$bug" ${cmake_extra[@]+"${cmake_extra[@]}"} >"$bdir.configure.log" 2>&1 || {
        cat "$bdir.configure.log" >&2; exit 1; }
    cmake --build "$bdir" -j --target p3cg >"$bdir.build.log" 2>&1 || { cat "$bdir.build.log" >&2; exit 1; }
    cp "$bdir/p3cg" "bin/$name"
  else
    "$MPICXX" -O3 -std=c++17 -DPLANT_HALO_BUG="$bug" -DP3_GIT_SHA="\"$git_sha\"" ${direct_omp[@]+"${direct_omp[@]}"} \
      "${srcs[@]}" -o "bin/$name"
  fi
  echo "built bin/$name  sha256=$(timeout 120 bin/$name --version | sed -n 's/.*sha256=\([0-9a-f]*\).*/\1/p')"
done
