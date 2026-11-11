#!/usr/bin/env python3
"""Release check for the report: E1-E18 (circuit/CIRCUIT.md section 3) against the built report.

  python3 checks/requirements_check.py [--tex report/DSA5208_Project3_Report.tex] [--no-pdf]
  python3 checks/requirements_check.py --selftest     qualification: refuses deliberately broken copies

For each E row it prints FILLED, WAITING (and for what), UNMAPPED, or USER (an act outside the build). A row waits
while anything it depends on is unfilled: a generated value or table used in the text, a figure slot, or an
"interpretation to write" box in a section carrying that row's \\req marker. Global checks, each of which refuses:
  - hand-typed numbers in the body: 0 (numbers come from \\val{} or generated tables; see NUMBER RULES below)
  - figures: every filled figure's metadata has logarithmic axes for time, problem size and core counts, its source
    CSVs still have the recorded sha256, its rows come from atlas/vanda and from binaries qualified there
  - package: no log files or terminal output among the files the PDF includes or the repository tracks
  - authors: Kushagra Bhatnagar (A0351591A) and Pratyush Sinha (A0352482A) on the title page
  - an AI-use section naming the tool
  - the PDF is newer than every source it is built from (unless --no-pdf)
TERMS (non-standard terms used vs defined with \\term{}) is printed and does not bind: a definition sentence existing
is not the same as the grader finding the report makes sense.

NUMBER RULES. Outside math: no digit at all, except identifiers (2D/3D, 1D, 5-point/7-point, V1-V5, Lecture 12,
Project 3, DSA5208, Opus 5.5, SHA-256, student IDs). Inside math: single digits only (constants and exponents such
as 2d, h^2, P^{2/3}); a number with two or more digits or a decimal point must be a \\val. Inside \\code{}: no
free-standing number. Ignored: comments, labels/refs/cites, file arguments, lengths and widths, the bibliography.
"""
import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "checks"))
DEFAULT_TEX = os.path.join(REPO, "report", "DSA5208_Project3_Report.tex")

REQS = [
    ("E1", "the algorithm is introduced"),
    ("E2", "serial runtime vs problem size (matrix dimension and nonzeros vary)"),
    ("E3", "MPI strong scaling to >=256 cores, speedup and efficiency"),
    ("E4", "MPI weak scaling to >=256 cores, speedup and efficiency"),
    ("E5", "effect of communication on runtime (L12 model, measured split)"),
    ("E6", "MPI+X: rank x thread layouts on 72-core nodes"),
    ("E7", "at least one GPU run (X = OpenMP)"),
    ("E8", "design decisions; which parts communicate most"),
    ("E9", "validation, each test explained, the set kept small"),
    ("E10", "runtime figures from Atlas or Vanda"),
    ("E11", "synthetic data: how it is generated"),
    ("E12", "Poisson in 2D and 3D"),
    ("E13", "non-standard terminology defined"),
    ("E14", "log axes for time, size and core count"),
    ("E15", "AI use explained"),
    ("E16", "code and README in the PDF (or a public link); no log files or terminal output"),
    ("E17", "names and IDs: Kushagra Bhatnagar (A0351591A), Pratyush Sinha (A0352482A)"),
    ("E18", "upload to Canvas by 17 Nov 23:59 SGT, PDF only"),
]
USER_ROWS = {"E18": "the user's upload after release"}
INTERP_EXEMPT = {"E10", "E13", "E14"}  # provenance, terms and axes do not wait for prose
PRINTED_ONLY = {"E13"}
AUTHORS = [("Kushagra Bhatnagar", "A0351591A"), ("Pratyush Sinha", "A0352482A")]
AI_TOOL = "Claude Code"
LOG_AXES = ("time", "size", "cores")
LOG_PATTERNS = [r"\.log$", r"\.out$", r"\.err$", r"(^|/)cluster/logs/", r"(^|/)results/validation/.*\.txt$",
                r"\.o\d+$", r"\.e\d+$", r"nohup", r"(^|/)slurm-\d+"]
TERMS = ["stencil", "matrix-free", "arithmetic intensity", "memory-bound", "conjugate gradient", "condition number",
         "manufactured solution", "global reduction", "rank", "domain decomposition", "process grid", "ghost cells",
         "halo exchange", "halo", "latency", "bandwidth", "pipelined CG", "recursive residual", "true residual",
         "threads", "first touch", "offload", "load imbalance", "run record", "strong scaling", "weak scaling",
         "speedup", "parallel efficiency", "attainable accuracy"]


# ---------------------------------------------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------------------------------------------
def strip_comments(t):
    return re.sub(r"(?<!\\)%.*", "", t)


def body_of(tex):
    i, j = tex.find("\\begin{document}"), tex.find("\\end{document}")
    return tex[i:j] if i >= 0 and j > i else tex


def sections(body):
    """[(title, start, end, [E rows])] for each \\section (appendix included)."""
    marks = []
    for m in re.finditer(r"\\section\*?(?=\{)", body):
        title, _ = braced(body, m.end())
        title = re.sub(r"\\texorpdfstring\{((?:[^{}]|\{[^{}]*\})*)\}\{[^{}]*\}", r"\1", title)
        marks.append((m.start(), title))
    out = []
    for k, (pos, title) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(body)
        chunk = body[pos:end]
        out.append((re.sub(r"\\val\{[^}]*\}", "...", title), pos, end, re.findall(r"\\req\{(E\d+)\}", chunk)))
    return out


def braced(s, i):
    """Returns (content, index after) for the brace group starting at s[i] == '{'."""
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def remove_cmd(s, name, nargs=1):
    """Removes \\name{..}{..} (nargs groups) wherever it occurs."""
    out, i = [], 0
    pat = re.compile(r"\\%s\*?(?![A-Za-z])" % re.escape(name))
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:m.start()])
        j = m.end()
        for _ in range(nargs):
            while j < len(s) and s[j] in " \t\n":
                j += 1
            if j < len(s) and s[j] == "[":
                j = s.index("]", j) + 1
            if j < len(s) and s[j] == "{":
                _, j = braced(s, j)
        out.append(" ")
        i = j


WHITELIST = [r"\b[123]D\b", r"\b[57]-point\b", r"\bV[1-5]\b", r"Lecture~?\s?\d+", r"\bProject\s3\b", r"\bDSA5208\b",
             r"\bOpus\s5\.5\b", r"\bSHA-256\b", r"\b[A-Z]\d{7}[A-Z]\b"]


def hand_typed_numbers(tex):
    b = strip_comments(body_of(tex))
    b = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", " ", b, flags=re.S)
    for name, n in (("val", 1), ("req", 1), ("label", 1), ("ref", 1), ("eqref", 1), ("cite", 1), ("input", 1),
                    ("includegraphics", 1), ("lstinputlisting", 1), ("hspace", 1), ("vspace", 1), ("setlength", 2),
                    ("algotitle", 1), ("figslot", 2), ("interpslot", 1), ("src", 1), ("pending", 1),
                    ("texorpdfstring", 0)):
        b = remove_cmd(b, name, n)
    b = re.sub(r"\\begin\{(?:tabular|tabularx|minipage|thebibliography)\}(?:\{[^}]*\})+", " ", b)
    b = re.sub(r"\\begin\{(?:figure|table)\}\[[^\]]*\]", " ", b)
    b = re.sub(r"\\\\\[[0-9.]+(?:pt|ex|em|mm|cm)\]", " ", b)
    b = re.sub(r"[0-9.]+\\(?:textwidth|linewidth|columnwidth|textheight)", " ", b)
    b = re.sub(r"\\@for\\pf:=\\appendixfiles\\do", " ", b)
    hits = []
    # \code{}: no free-standing number
    for m in re.finditer(r"\\code\{((?:[^{}]|\{[^{}]*\})*)\}", b):
        for n in re.finditer(r"(?<![A-Za-z0-9_.\-/])\d+(?:\.\d+)?(?![A-Za-z0-9_])", m.group(1)):
            hits.append(("code", n.group(0), m.group(0)[:80]))
    b = re.sub(r"\\code\{(?:[^{}]|\{[^{}]*\})*\}", " ", b)
    b = re.sub(r"\\texttt\{(?:[^{}]|\{[^{}]*\})*\}", " ", b)
    # math: single digits only
    math_pat = re.compile(r"\$\$.*?\$\$|\$[^$]*\$|\\\[.*?\\\]|\\begin\{(equation|align)\*?\}.*?\\end\{\1\*?\}", re.S)
    for m in math_pat.finditer(b):
        seg = m.group(0)
        for n in re.finditer(r"\d{2,}|\d+\.\d+", seg):
            hits.append(("math", n.group(0), " ".join(seg.split())[:80]))
    b = math_pat.sub(" ", b)
    for w in WHITELIST:
        b = re.sub(w, " ", b)
    for ln, line in enumerate(b.splitlines(), 1):
        for m in re.finditer(r"\d+(?:[.,]\d+)*", line):
            hits.append(("text", m.group(0), " ".join(line.split())[:80]))
    return hits


# ---------------------------------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------------------------------
def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 16), b""):
            h.update(c)
    return h.hexdigest()


def check_figure(meta_path, results, validated):
    """Problems with a filled figure (empty list = fine)."""
    bad = []
    m = json.load(open(meta_path))
    for a in m.get("axes", []):
        if a["quantity"] in LOG_AXES and a["scale"] != "log":
            bad.append("%s: %s axis of panel %s (%s) is %s, not logarithmic" %
                       (m["figure"], a["axis"], a["panel"], a["quantity"], a["scale"]))
    if not m.get("axes"):
        bad.append("%s: metadata lists no axes" % m["figure"])
    for s in m.get("sources", []):
        p = s["path"] if os.path.isabs(s["path"]) else os.path.join(REPO, s["path"])
        if not os.path.exists(p) or sha256(p) != s["sha256"]:
            bad.append("%s: source %s changed or missing since the figure was drawn" % (m["figure"], s["path"]))
    if set(m.get("clusters", [])) - {"atlas", "vanda"}:
        bad.append("%s: rows from %s" % (m["figure"], m.get("clusters")))
    ok = set((e["binary_sha256"], e["cluster"]) for e in validated)
    for b in m.get("binaries", []):
        if not any((b, c) in ok for c in m.get("clusters", [])):
            bad.append("%s: binary %s not qualified on %s" % (m["figure"], b[:12], m.get("clusters")))
    img = os.path.join(os.path.dirname(meta_path), m["figure"] + ".pdf")
    if not os.path.exists(img) or sha256(img) != m.get("image_sha256"):
        bad.append("%s: image missing or not the one the metadata describes" % m["figure"])
    return bad


def package_files(tex_path, status):
    """Files the PDF is built from or includes, plus the files git tracks (the code package)."""
    rdir = os.path.dirname(os.path.abspath(tex_path))
    files = set()
    tex = strip_comments(open(tex_path).read())
    for m in re.finditer(r"\\input\{([^}]*)\}", tex):
        files.add(os.path.normpath(os.path.join(rdir, m.group(1) + ("" if m.group(1).endswith(".tex") else ".tex"))))
    for f in status.get("appendix_files", []):
        files.add(os.path.join(REPO, f))
    for name, info in status.get("figures", {}).items():
        if info.get("filled"):
            files.add(os.path.join(status.get("figures_dir", ""), name + ".pdf"))
    for root, _, fs in os.walk(rdir):  # the report folder itself may be shipped as it is
        files |= set(os.path.join(root, f) for f in fs)
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO, stdout=subprocess.PIPE, universal_newlines=True).stdout
        files |= set(os.path.join(REPO, x) for x in out.split())
    except Exception:
        pass
    return sorted(files)


def terms_report(tex):
    b = strip_comments(body_of(tex))
    b = b.split("\\appendix")[0]
    b = b[b.find("\\end{center}"):] if "\\end{center}" in b else b  # the title is not a use
    b = re.sub(r"\\(?:val|ref|label|req|figslot|interpslot|input)\{[^}]*\}", " ", b)  # macro keys are not uses
    out = []
    for t in TERMS:
        dm = re.search(r"\\term\{%s\}" % re.escape(t), b, re.I)
        plain = re.sub(r"\\term\{([^}]*)\}", r"\1", b)
        uses = [m.start() for m in re.finditer(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(t), plain, re.I)]
        first_def = None
        if dm:
            first_def = len(re.sub(r"\\term\{([^}]*)\}", r"\1", b[:dm.start()]))
        out.append((t, len(uses), dm is not None, (first_def is not None and uses and first_def <= uses[0])))
    return out


def run(tex_path, no_pdf=False, quiet=False):
    say = (lambda *a: None) if quiet else print
    tex = open(tex_path).read()
    gen = os.path.join(os.path.dirname(os.path.abspath(tex_path)), "generated")
    status = json.load(open(os.path.join(gen, "status.json")))
    body = strip_comments(body_of(tex))
    secs = sections(body)
    problems = []

    # what the text actually uses
    used_vals = set(re.findall(r"\\val\{([^}]*)\}", body))
    used_tabs = set(re.findall(r"\\input\{generated/tab_([^}]*)\.tex\}", body))
    used_figs = set(re.findall(r"\\figslot\{([^}]*)\}", body))
    undefined = sorted(v for v in used_vals if v not in status["values"])
    if undefined:
        problems.append("%d \\val keys not generated: %s" % (len(undefined), undefined[:6]))
    missing_tabs = sorted(t for t in used_tabs if t not in status["tables"])
    if missing_tabs:
        problems.append("tables not generated: %s" % missing_tabs)

    waiting = {}  # E row -> set of reasons

    def wait(rows, why):
        kind, _, what = why.partition(": ")
        parts = [p for p in what.split("; ") if p] if kind == "cluster data" else [what or why]
        for r in rows:
            for p in parts:
                waiting.setdefault(r, set()).add("%s: %s" % (kind, p) if kind == "cluster data" else why)

    for k in used_vals & set(status["values"]):
        v = status["values"][k]
        if not v["filled"]:
            wait(v["reqs"], "cluster data: " + (v["waiting_for"] or k))
    for t in used_tabs & set(status["tables"]):
        v = status["tables"][t]
        if not v["filled"]:
            wait(v["reqs"], "cluster data: " + v["waiting_for"])
    fig_bad = []
    validated = []
    vpath = os.path.join(status.get("results", os.path.join(REPO, "results")), "validated_binaries.csv")
    if os.path.exists(vpath):
        import csv
        validated = [r for r in csv.DictReader(open(vpath)) if r.get("verdict") == "QUALIFIED"]
    for f in used_figs:
        info = status["figures"].get(f)
        if info is None:
            problems.append("figure slot %s has no generated state" % f)
            continue
        if not info["filled"]:
            wait(info["reqs"], "cluster data: " + info["waiting_for"])
        else:
            mp = info["meta"] if os.path.isabs(info["meta"]) else os.path.join(REPO, info["meta"])
            fig_bad += check_figure(mp, status.get("results", ""), validated)
    # interpretation boxes and figure slots attach to the section they sit in
    for title, s, e, rows in secs:
        chunk = body[s:e]
        for m in re.finditer(r"\\interpslot\{([^}]*)\}", chunk):
            wait([r for r in rows if r not in INTERP_EXEMPT], "interpretation to write (%s)" % m.group(1))
    if not used_figs:
        wait(["E14", "E10"], "no figures in the report")

    # E rows
    rowmap = {}
    for title, s, e, rows in secs:
        for r in rows:
            rowmap.setdefault(r, []).append(title)
    say("REQUIREMENTS CHECK  %s" % os.path.relpath(tex_path, REPO))
    rowprob = {}
    # global checks
    hits = hand_typed_numbers(tex)
    say("  hand-typed numbers in the body: %d" % len(hits))
    for kind, num, ctx in hits[:12]:
        say("     %s %r in: %s" % (kind, num, ctx))
    if hits:
        problems.append("%d hand-typed numbers" % len(hits))
    say("  figures included: %d, filled: %d; problems in filled figures: %d" %
        (len(used_figs), sum(1 for f in used_figs if status["figures"].get(f, {}).get("filled")), len(fig_bad)))
    for b in fig_bad:
        say("     %s" % b)
    problems += fig_bad
    if fig_bad:
        rowprob.setdefault("E14", []).append("figure axes or sources")
    files = package_files(tex_path, status)
    logs = [f for f in files for p in LOG_PATTERNS if re.search(p, os.path.relpath(f, REPO))]
    verb = len(re.findall(r"\\begin\{(?:verbatim|lstlisting)\}", body))
    say("  log files or terminal output in the package: %d files, %d verbatim blocks (%d files checked)" %
        (len(logs), verb, len(files)))
    for f in logs[:5]:
        say("     %s" % os.path.relpath(f, REPO))
    if logs or verb:
        problems.append("log files or terminal output in the package")
        rowprob.setdefault("E16", []).append("log files or terminal output in the package")
    head = tex[tex.find("\\begin{document}"):][:3000]
    for name, sid in AUTHORS:
        ok = name in head and sid in head
        say("  author %s (%s): %s" % (name, sid, "on the title page" if ok else "MISSING"))
        if not ok:
            problems.append("author %s missing" % name)
            rowprob.setdefault("E17", []).append("author %s missing" % name)
    ai = re.search(r"\\section\*?\{[^}]*\bAI\b[^}]*\}(.*?)(?=\\section|\\appendix|\\end\{document\})", body, re.S)
    ai_ok = bool(ai) and AI_TOOL in ai.group(1)
    say("  AI-use section naming %s: %s" % (AI_TOOL, "present" if ai_ok else "MISSING"))
    if not ai_ok:
        problems.append("AI-use section missing or does not name the tool")
        rowprob.setdefault("E15", []).append("AI-use section missing or does not name the tool")
    if not no_pdf:
        pdf = os.path.splitext(tex_path)[0] + ".pdf"
        srcs = [tex_path] + glob.glob(os.path.join(gen, "*")) + \
            [os.path.join(status.get("figures_dir", ""), f + ".pdf") for f in used_figs
             if status["figures"].get(f, {}).get("filled")]
        fresh = os.path.exists(pdf) and all(os.path.getmtime(pdf) >= os.path.getmtime(s) for s in srcs
                                            if os.path.exists(s))
        say("  PDF built after its sources: %s" % ("yes" if fresh else "NO (rebuild)"))
        if not fresh:
            problems.append("PDF missing or older than its sources")
    # terms
    say("  TERMS (printed, not binding):")
    tr = terms_report(tex)
    nd = [t for t in tr if t[1] and not t[2]]
    late = [t for t in tr if t[2] and not t[3]]
    say("     %d terms used; defined %d; used without a definition: %s; defined after first use: %s" %
        (sum(1 for t in tr if t[1]), sum(1 for t in tr if t[2]), ", ".join(t[0] for t in nd) or "none",
         ", ".join(t[0] for t in late) or "none"))

    unfilled = []
    for rid, prop in REQS:
        where = "; ".join(rowmap.get(rid, [])) or "-"
        if rid in USER_ROWS:
            state = "USER (%s)" % USER_ROWS[rid]
        elif rid in rowprob:
            state = "REFUSED: " + "; ".join(rowprob[rid])
            unfilled.append(rid)
        elif rid not in rowmap:
            state = "UNMAPPED"
            unfilled.append(rid)
        elif rid in waiting:
            state = "WAITING: " + "; ".join(sorted(waiting[rid]))
            unfilled.append(rid)
        elif rid in PRINTED_ONLY:
            state = "PRINTED (see TERMS; not binding)"
        else:
            state = "FILLED"
        say("  %-4s %-62s %s" % (rid, prop[:62], state))
        if rid in rowmap:
            say("       in: %s" % where)

    if problems:
        verdict = "REFUSED"
    elif unfilled:
        verdict = "REFUSED (incomplete)"
    else:
        verdict = "PASS"
    for p in problems:
        say("  PROBLEM: %s" % p)
    waiting_rows = [r for r in unfilled if any(w.startswith("cluster data") for w in waiting.get(r, ()))]
    say("  E rows waiting for cluster data: %s" % (", ".join(waiting_rows) or "none"))
    interp_rows = [r for r in unfilled if any(w.startswith("interpretation") for w in waiting.get(r, ()))]
    say("  E rows waiting for an interpretation to be written: %s" % (", ".join(interp_rows) or "none"))
    say("REQUIREMENTS: %s" % verdict)
    say("  qualification: refuses broken copies (--selftest); pass example: none yet - it will be the first full "
        "render the user accepts")
    return verdict, problems, unfilled, waiting


# ---------------------------------------------------------------------------------------------------------------
# selftest: fabricated cluster rows (TEST DOUBLE) in a scratch directory, then deliberately broken copies
# ---------------------------------------------------------------------------------------------------------------
def selftest():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import figures as F
    guard = {d: F.snapshot(os.path.join(REPO, d)) for d in ("figures", "report")}
    results = []
    with tempfile.TemporaryDirectory(prefix="p3req_") as td:
        res, figs, rep = os.path.join(td, "results"), os.path.join(td, "figures"), os.path.join(td, "report")
        F.fabricate(res)
        F.build(res, figs, stamp_text="TEST DOUBLE")
        shutil.copytree(os.path.join(REPO, "report"), rep, ignore=shutil.ignore_patterns("*.pdf", "generated"))
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "report_macros.py"), "--results", res,
                        "--figures", figs, "--out", os.path.join(rep, "generated")], stdout=subprocess.PIPE, check=True)
        texp = os.path.join(rep, "DSA5208_Project3_Report.tex")
        base = open(texp).read()

        def attempt(label, expect, tex_text=None, fig_patch=None):
            if tex_text is not None:
                open(texp, "w").write(tex_text)
            v, probs, unfilled, waiting = run(texp, no_pdf=True, quiet=True)
            open(texp, "w").write(base)
            ok = expect(v, probs, unfilled, waiting)
            results.append((label, v, probs, ok))

        # 0) fabricated cluster rows fill every cluster slot; only the interpretation boxes remain
        attempt("TEST-DOUBLE rows: every cluster slot fills", lambda v, p, u, w: not p and all(
            all(x.startswith("interpretation") for x in w.get(r, ())) for r in u))
        # 1) a hand-typed number in the body
        attempt("a hand-typed number in the text", lambda v, p, u, w: any("hand-typed" in x for x in p),
                base.replace("\\subsection{Strong scaling}", "\\subsection{Strong scaling}\nThe speedup was 3.7 "
                             "on four nodes.", 1))
        # 2) the AI section removed
        attempt("the AI-use section removed", lambda v, p, u, w: any("AI-use" in x for x in p),
                re.sub(r"\\section\{Declaration of AI use\}.*?(?=\\section)", "", base, flags=re.S))
        # 3) a figure drawn with a linear core axis (the figure script itself changed)
        orig = F.count_axis

        def linear(ax, ticks, axis="x"):
            orig(ax, ticks, axis)
            getattr(ax, "set_%sscale" % axis)("linear")
        F.count_axis = linear
        F.build(res, figs, names=["fig_strong"], stamp_text="TEST DOUBLE")
        F.count_axis = orig
        attempt("fig_strong drawn with a linear core axis", lambda v, p, u, w: any("not logarithmic" in x for x in p))
        F.build(res, figs, names=["fig_strong"], stamp_text="TEST DOUBLE")
        # 4) a figure whose source rows changed after drawing
        src = sorted(glob.glob(os.path.join(res, "vanda", "*.csv")))[0]
        with open(src, "a") as f:
            f.write("")
        os.utime(src)
        with open(src) as f:
            content = f.read()
        with open(src, "w") as f:
            f.write(content.replace("TEST-DOUBLE", "TEST-DOUBLX", 1))
        attempt("a source CSV edited after the figures were drawn",
                lambda v, p, u, w: any("changed or missing" in x for x in p))
        # 5) the real (unfilled) report must list cluster-data rows, not pass
    real = run(DEFAULT_TEX, no_pdf=True, quiet=True)
    results.append(("the real report today (no cluster rows)", real[0], real[1],
                    real[0] != "PASS" and any(any(x.startswith("cluster data") for x in real[3].get(r, ()))
                                              for r in real[2])))
    after = {d: F.snapshot(os.path.join(REPO, d)) for d in ("figures", "report")}
    clean = guard == after
    ok = all(r[3] for r in results) and clean
    print("REQUIREMENTS CHECK SELFTEST")
    for label, v, probs, good in results:
        detail = "; ".join(probs[:2]) if probs else ""
        print("  %-50s -> %-21s %s%s" % (label, v, "ok" if good else "WRONG", (" (" + detail[:110] + ")") if detail
                                          else ""))
    print("  figures/ and report/ untouched (fabricated rows stayed in a scratch directory): %s" %
          ("yes" if clean else "NO"))
    print("SELFTEST: %s. Pass example: none yet - the first full render the user accepts." %
          ("QUALIFIED on refusals" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tex", default=DEFAULT_TEX)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    verdict, _, _, _ = run(a.tex, a.no_pdf)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
