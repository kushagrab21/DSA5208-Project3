#!/usr/bin/env bash
# Downloads one SNAP dataset ("Networks with ground-truth communities", plus email-Eu-core) into the data folder,
# checks the gzip integrity and records the source URL, size and sha256 of every file.
#
#   scripts/fetch_snap.sh NAME [DATA_DIR]
#     NAME      email-Eu-core | com-amazon | com-dblp | com-youtube | com-lj | com-orkut
#     DATA_DIR  default ${P3_DATA:-$HOME/p3data}. Data lives OUTSIDE the repository (never in git, never in the
#               submitted package). On the Mac the repository's data/ folder (gitignored) is used instead.
#
# Run it on a cluster LOGIN node (compute nodes may have no internet). Files go to DATA_DIR/raw/; the record is
# DATA_DIR/raw/SOURCES.tsv (one line per file: utc, name, file, url, bytes, sha256). A file that is already present
# with the recorded sha256 is not downloaded again; a present file whose hash differs from the record is refused.
set -euo pipefail
name="${1:?usage: scripts/fetch_snap.sh NAME [DATA_DIR]}"
dest="${2:-${P3_DATA:-$HOME/p3data}}"
base="https://snap.stanford.edu/data"
case "$name" in
  email-Eu-core) files=("$base/email-Eu-core.txt.gz" "$base/email-Eu-core-department-labels.txt.gz");;
  com-amazon|com-dblp|com-youtube|com-lj|com-orkut)
    files=("$base/bigdata/communities/$name.ungraph.txt.gz" "$base/bigdata/communities/$name.top5000.cmty.txt.gz");;
  *) echo "fetch_snap: unknown dataset '$name' (email-Eu-core com-amazon com-dblp com-youtube com-lj com-orkut)" >&2
     exit 2;;
esac
raw="$dest/raw"
mkdir -p "$raw"
rec="$raw/SOURCES.tsv"
[[ -f "$rec" ]] || printf 'utc\tname\tfile\turl\tbytes\tsha256\n' > "$rec"
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
for url in "${files[@]}"; do
  f="$(basename "$url")"
  known="$(awk -F'\t' -v f="$f" '$3 == f {s = $6} END {print s}' "$rec")"
  if [[ -f "$raw/$f" && -n "$known" ]]; then
    got="$(sha "$raw/$f")"
    if [[ "$got" == "$known" ]]; then echo "fetch_snap: $f present, sha256 matches the record ($got)"; continue; fi
    echo "fetch_snap: REFUSED $raw/$f has sha256 $got but SOURCES.tsv records $known; move it away first" >&2
    exit 1
  fi
  echo "fetch_snap: downloading $url"
  curl -fsSL --retry 3 --max-time 3600 -o "$raw/$f.part" "$url"
  if ! gzip -t "$raw/$f.part"; then echo "fetch_snap: REFUSED $f fails gzip -t (truncated download?)" >&2; exit 1; fi
  mv "$raw/$f.part" "$raw/$f"
  bytes="$(wc -c < "$raw/$f" | tr -d ' ')"
  s="$(sha "$raw/$f")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" "$f" "$url" "$bytes" "$s" >> "$rec"
  echo "fetch_snap: $f  $bytes bytes  sha256 $s  (gzip ok)"
done
echo "fetch_snap: $name in $raw (record: $rec)"
