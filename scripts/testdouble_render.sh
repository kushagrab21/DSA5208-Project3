#!/usr/bin/env bash
# Renders the report from FABRICATED cluster rows (TEST DOUBLE) in a scratch directory, to show that cluster rows
# drop into every slot without hand editing. Output: ${1:-/tmp/p3_testdouble}/report/DSA5208_Project3_Report.pdf.
# Nothing is written to results/, figures/ or report/ in the repository; every figure carries a TEST DOUBLE stamp.
set -eo pipefail
cd "$(dirname "$0")/.."
out="${1:-/tmp/p3_testdouble}"
rm -rf "$out" && mkdir -p "$out"
python3 - "$out" <<'PY'
import os, sys
sys.path.insert(0, "scripts"); sys.path.insert(0, "checks")
import figures as F
out = sys.argv[1]
F.fabricate(os.path.join(out, "results"))
for line in F.build(os.path.join(out, "results"), os.path.join(out, "figures"), stamp_text="TEST DOUBLE"):
    print(line)
PY
mkdir -p "$out/report"
cp report/DSA5208_Project3_Report.tex "$out/report/"
# the code appendix reads ../src, ../checks, ... relative to the report: link them (read-only use)
for x in src checks scripts cluster CMakeLists.txt README.md; do ln -s "$PWD/$x" "$out/$x"; done
python3 scripts/report_macros.py --results "$out/results" --figures "$out/figures" --out "$out/report/generated"
# the report looks for figures in ../figures relative to itself, which is $out/figures here
(cd "$out/report" && sed -i.bak 's/\\begin{document}/\\begin{document}\\noindent{\\Large\\bfseries\\sffamily\\textcolor{red}{TEST DOUBLE: every cluster number in this file is fabricated}}\\par/' DSA5208_Project3_Report.tex && rm -f *.bak && tectonic -X compile DSA5208_Project3_Report.tex >/dev/null 2>&1)
python3 checks/requirements_check.py --tex "$out/report/DSA5208_Project3_Report.tex" | tail -4 || true
echo "TEST DOUBLE render: $out/report/DSA5208_Project3_Report.pdf"
