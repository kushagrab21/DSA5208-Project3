#!/usr/bin/env bash
# FAKE Vanda login environment (tests only): creates $P3_FAKE_ROOT/vanda/app1/ebenv, which defines a `module`
# function like the real one after `source /app1/ebenv`: `avail` lists the EasyBuild toolchains seen on Vanda
# (foss/2025b, its Python) and the nvhpc modules; `load foss/...` or `load nvhpc-hpcx-cuda12/...` puts a working MPI
# (this Mac's) first on PATH; `load foss/...` also sets EBROOTLIBFABRIC and EBROOTOPENMPI like EasyBuild does.
set -e
r="${P3_FAKE_ROOT:?}/vanda"
mkdir -p "$r/home" "$r/app1" "$r/easybuild/bin" "$r/nvhpc/bin" "$r/eb/libfabric/lib" "$r/eb/openmpi/lib"
for t in mpicxx mpirun; do ln -sf "$(command -v $t)" "$r/easybuild/bin/$t"; ln -sf "$(command -v $t)" "$r/nvhpc/bin/$t"; done
: > "$r/eb/libfabric/lib/libfabric.so.1"; : > "$r/eb/openmpi/lib/libmpi.so.40"
cat > "$r/app1/ebenv" <<X
# FAKE /app1/ebenv for Vanda (test double)
FAKE_EB_BIN="$r/easybuild/bin"; FAKE_NV_BIN="$r/nvhpc/bin"; FAKE_EB_ROOT="$r/eb"
X
cat >> "$r/app1/ebenv" <<'X'
fake_eb_list() {
  for m in foss/2024a foss/2025a foss/2025b gompi/2025b OpenMPI/5.0.8-GCC-14.3.0 GCC/14.3.0 GCCcore/14.3.0 \
           Python/3.12.3-GCCcore-13.3.0 Python/3.13.5-GCCcore-14.3.0 CMake/4.0.3-GCCcore-14.3.0 \
           nvhpc/26.1 nvhpc-hpcx/26.1 nvhpc-hpcx-cuda12/26.1 mvapich2/gcc/64/2.3.7; do
    if [[ -z "$1" || "$m" == "$1"/* ]]; then echo "$m"; fi
  done
}
module() {
  [[ "$1" == "-t" ]] && shift
  case "$1" in
    avail) shift; fake_eb_list "$@" >&2;;
    load) shift; for m in "$@"; do
            case "$m" in
              foss/*|OpenMPI/*) PATH="$FAKE_EB_BIN:$PATH"; export EBROOTLIBFABRIC="$FAKE_EB_ROOT/libfabric" \
                                EBROOTOPENMPI="$FAKE_EB_ROOT/openmpi";;
              nvhpc*) PATH="$FAKE_NV_BIN:$PATH";;
            esac
            FAKE_EB_LOADED="$FAKE_EB_LOADED $m"; done; export PATH FAKE_EB_LOADED;;
    purge) FAKE_EB_LOADED="";;
    list) printf 'Currently Loaded Modulefiles:\n' >&2; for m in shared apptainer/1.4.1 $FAKE_EB_LOADED; do echo "$m"; done >&2;;
  esac
}
X
