#!/usr/bin/env bash
# Builds the report from the run records: figures -> generated values/tables -> PDF -> requirements check.
#   scripts/make_report.sh            the real report (report/DSA5208_Project3_Report.pdf)
# The requirements check runs last; its verdict is printed, and a refusal does not delete the PDF (drafts are
# rendered while cluster data are missing), but only a PASS may be released.
set -eo pipefail
cd "$(dirname "$0")/.."
python3 scripts/figures.py
python3 scripts/report_macros.py
(cd report && tectonic -X compile DSA5208_Project3_Report.tex >/tmp/p3_tectonic.out 2>&1) || {
  tail -40 /tmp/p3_tectonic.out >&2; exit 1; }
python3 checks/requirements_check.py || true
