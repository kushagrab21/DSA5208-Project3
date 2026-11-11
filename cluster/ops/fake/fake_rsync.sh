#!/usr/bin/env bash
# FAKE rsync transport (tests only): ALIAS:path arguments become $P3_FAKE_ROOT/ALIAS/home/path; then real rsync.
root="${P3_FAKE_ROOT:?P3_FAKE_ROOT not set}"
out=()
for a in "$@"; do
  if [[ "$a" =~ ^([A-Za-z0-9_.-]+):(.*)$ ]] && [[ -d "$root/${BASH_REMATCH[1]}" || "$a" != /* ]] && [[ "$a" != -* ]]; then
    al="${BASH_REMATCH[1]}"; p="${BASH_REMATCH[2]}"; p="${p#\~/}"
    if [[ ",${P3_FAKE_DOWN:-}," == *",$al,"* ]]; then echo "ssh: connect to host $al: Operation timed out" >&2; exit 255; fi
    [[ "$p" == /* ]] || p="$root/$al/home/$p"
    out+=("$p")
  else
    out+=("$a")
  fi
done
exec rsync "${out[@]}"
