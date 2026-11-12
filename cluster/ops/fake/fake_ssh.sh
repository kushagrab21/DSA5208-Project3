#!/usr/bin/env bash
# FAKE ssh (tests only): fake_ssh.sh ALIAS cmd...  runs cmd "on" ALIAS: a clean environment, HOME=$P3_FAKE_ROOT/ALIAS/home,
# the fake PBS/module/hpc tools first on PATH. P3_FAKE_DOWN=alias[,alias] makes the alias unreachable (VPN dropped).
alias="$1"; shift
root="${P3_FAKE_ROOT:?P3_FAKE_ROOT not set}"
if [[ ",${P3_FAKE_DOWN:-}," == *",$alias,"* ]]; then
  echo "ssh: connect to host $alias port 22: Operation timed out" >&2; exit 255
fi
home="$root/$alias/home"; mkdir -p "$home"; cd "$home"
args=(); for a in "$@"; do [[ "$a" == "-l" ]] || args+=("$a"); done   # no login profile on the fake
here="$(cd "$(dirname "$0")" && pwd)"
extra=""; eb=""
if [[ "$alias" == atlas* ]]; then   # like the real login: the 2013 mvapich2 mpicxx is first on PATH
  extra="$root/$alias/app1/centos6.3/gnu/mvapich2-1.9/bin:"
fi
[[ -f "$root/$alias/app1/ebenv" ]] && eb="$root/$alias/app1/ebenv"
exec env -i HOME="$home" USER="fakeuser" LANG="${LANG:-C}" TMPDIR="${TMPDIR:-/tmp}" P3_EBENV="$eb" \
  PATH="$here/bin:$extra/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  P3_FAKE_ROOT="$root" P3_FAKE_ALIAS="$alias" FAKE_SPEED="${FAKE_SPEED:-1}" FAKE_FAIL_JOBS="${FAKE_FAIL_JOBS:-}" \
  FAKE_QUEUE_ONLY="${FAKE_QUEUE_ONLY:-}" FAKE_FORGET="${FAKE_FORGET:-}" FAKE_QSUB_REJECT="${FAKE_QSUB_REJECT:-}" \
  FAKE_NODE_PRELOAD="${FAKE_NODE_PRELOAD:-}" "${args[@]}"
