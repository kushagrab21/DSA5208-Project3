#!/usr/bin/env bash
# Converts one downloaded SNAP dataset (scripts/fetch_snap.sh) to the binary CSR files bin/p3graph reads.
#
#   scripts/convert_snap.sh NAME [DATA_DIR]        NAME as in fetch_snap.sh; DATA_DIR default ${P3_DATA:-$HOME/p3data}
#
# Reads DATA_DIR/raw/, writes DATA_DIR/csr/NAME.{natural,bfs}.{csr,cmty} and NAME.meta.json (counts: edge lines,
# self-loops and duplicates dropped, V, E, degrees, communities), and appends one line per conversion to
# DATA_DIR/csr/CONVERSIONS.tsv (utc, name, the sha256 of the inputs and of bin/p3convert). Refuses if an input's
# sha256 is not the one fetch_snap.sh recorded. Needs bin/p3convert (scripts/build.sh graph). Conversion of com-orkut
# needs ~5 GB of memory and a few minutes: on a cluster run it inside a job (the graph-prep job does), not on a login
# node.
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:?usage: scripts/convert_snap.sh NAME [DATA_DIR]}"
dest="${2:-${P3_DATA:-$HOME/p3data}}"
raw="$dest/raw"
out="$dest/csr"
conv="bin/p3convert"
[[ -x "$conv" ]] || { echo "convert_snap: no $conv (run scripts/build.sh graph)" >&2; exit 2; }
case "$name" in
  email-Eu-core) edges="email-Eu-core.txt.gz"; comm="email-Eu-core-department-labels.txt.gz"; kind=--labels;;
  com-amazon|com-dblp|com-youtube|com-lj|com-orkut)
    edges="$name.ungraph.txt.gz"; comm="$name.top5000.cmty.txt.gz"; kind=--cmty;;
  *) echo "convert_snap: unknown dataset '$name'" >&2; exit 2;;
esac
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
for f in "$edges" "$comm"; do
  [[ -f "$raw/$f" ]] || { echo "convert_snap: missing $raw/$f (run scripts/fetch_snap.sh $name first)" >&2; exit 2; }
  want="$(awk -F'\t' -v f="$f" '$3 == f {s = $6} END {print s}' "$raw/SOURCES.tsv" 2>/dev/null || true)"
  got="$(sha "$raw/$f")"
  if [[ "$want" != "$got" ]]; then
    echo "convert_snap: REFUSED $raw/$f sha256 $got is not the recorded ${want:-<none>} (SOURCES.tsv)" >&2; exit 1
  fi
done
mkdir -p "$out"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/p3conv.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
gzip -dc "$raw/$comm" > "$tmp/communities.txt"
gzip -dc "$raw/$edges" | "$conv" --edges - "$kind" "$tmp/communities.txt" --source-label "$comm" \
  --out "$out/$name" --name "$name"
[[ -f "$out/CONVERSIONS.tsv" ]] || printf 'utc\tname\tedges_sha256\tcommunities_sha256\tp3convert_sha256\n' > "$out/CONVERSIONS.tsv"
printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" "$(sha "$raw/$edges")" "$(sha "$raw/$comm")" \
  "$(sha "$conv")" >> "$out/CONVERSIONS.tsv"
echo "convert_snap: $name -> $out/$name.{natural,bfs}.{csr,cmty}, $out/$name.meta.json"
