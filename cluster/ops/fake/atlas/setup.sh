#!/usr/bin/env bash
# FAKE Atlas login environment (tests only): creates, under $P3_FAKE_ROOT/atlas8,
#   app1/centos6.3/gnu/mvapich2-1.9/bin/mpicxx  a 2013-style mpicxx stub that is first on PATH and cannot compile;
#   app1/ebenv                                  defines the EasyBuild `module` function: `avail` lists EasyBuild
#                                               toolchains, `load foss/...` puts a working MPI (this Mac's) first.
set -e
r="${P3_FAKE_ROOT:?}/atlas8"
mkdir -p "$r/home" "$r/app1/centos6.3/gnu/mvapich2-1.9/bin" "$r/easybuild/bin"
cat > "$r/app1/centos6.3/gnu/mvapich2-1.9/bin/mpicxx" <<'X'
#!/usr/bin/env bash
echo "mpicxx for MVAPICH2 version 1.9 (FAKE, 2013)"; [[ "$1" == "--version" ]] || exit 1
X
chmod +x "$r/app1/centos6.3/gnu/mvapich2-1.9/bin/mpicxx"
for t in mpicxx mpirun; do ln -sf "$(command -v $t)" "$r/easybuild/bin/$t"; done
cat > "$r/app1/ebenv" <<X
# FAKE /app1/ebenv (test double): the EasyBuild module function
FAKE_EB_BIN="$r/easybuild/bin"
X
cat >> "$r/app1/ebenv" <<'X'
fake_eb_list() {
  for m in foss/2021b foss/2022a foss/2023a foss/2023b gompi/2023b OpenMPI/4.1.1-GCC-11.2.0 OpenMPI/4.1.6-GCC-13.2.0 \
           GCC/11.2.0 GCC/13.2.0 GCCcore/13.2.0 CMake/3.27.6-GCCcore-13.2.0 Python/3.11.5-GCCcore-13.2.0 \
           ABINIT/9.10.3-foss-2023a; do
    if [[ -z "$1" || "$m" == "$1"/* ]]; then echo "$m"; fi
  done
}
module() {
  [[ "$1" == "-t" ]] && shift
  case "$1" in
    avail) shift; fake_eb_list "$@" >&2;;
    load) shift; for m in "$@"; do
            case "$m" in foss/*|OpenMPI/*|gompi/*) PATH="$FAKE_EB_BIN:$PATH";; esac
            FAKE_EB_LOADED="$FAKE_EB_LOADED $m"; done; export PATH FAKE_EB_LOADED;;
    purge) FAKE_EB_LOADED="";;
    list) for m in $FAKE_EB_LOADED; do echo "$m"; done >&2;;
  esac
}
X
