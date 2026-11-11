#!/usr/bin/env python3
"""Logic behind the cluster-operation scripts in cluster/ops/ (the shell scripts only move bytes and run ssh).

  opslib.py cluster ALIAS                         atlas8 -> atlas, vanda -> vanda
  opslib.py submit-check --cluster C --job J --remote-commit X --remote-plan Y --remote-bin Z
  opslib.py record-submit --cluster C --job J --pbs-id ID --commit X
  opslib.py pending --cluster C                    PBS ids submitted and not yet seen finished
  opslib.py poll-parse --cluster C < probe.txt     job states; appends a 'final' ledger row per finished job
  opslib.py merge-fetched --cluster C --staging D  merges fetched rows, ledger events and validated binaries
  opslib.py calibrate --cluster C                  bandwidths from finished rows -> results/<C>/calibration.json
  opslib.py plan-sha --cluster C

Every check prints one line per decision and REFUSED with the reason when it refuses (exit 1).
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys

OPS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(OPS))
sys.path.insert(0, os.path.join(REPO, "checks"))
import p3common as C  # noqa: E402
import run_plan as RP  # noqa: E402
import run_record  # noqa: E402

FINISHED = ("F", "X")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cluster_of(alias):
    a = os.environ.get("P3_CLUSTER_NAME") or alias
    if "atlas" in a:
        return "atlas"
    if "vanda" in a:
        return "vanda"
    raise SystemExit("cannot tell the cluster from alias %r (set P3_CLUSTER_NAME=atlas|vanda)" % alias)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def ledger_path(cl):
    return os.path.join(C.RESULTS, cl, "jobs.csv")


def ledger(cl):
    p = ledger_path(cl)
    return C.read_csv(p) if os.path.exists(p) else []


def append_ledger(cl, row):
    C.append_csv(ledger_path(cl), RP.JOBS_COLUMNS, dict((k, row.get(k, "")) for k in RP.JOBS_COLUMNS))


def head_commit():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def kind_of(job):
    if not job.get("cells"):
        return "validate"
    if job.get("calibration"):
        return "calibration"
    return "timed"


def estimate(plan, job):
    secs, cores = RP.job_estimate(plan, job)
    safety = RP.model_of(plan)["safety"]
    return secs, cores, secs * cores / 3600.0, secs * safety * cores / 3600.0, RP.walltime(secs, safety)


def budget_lines(plan, extra_worst=0.0, extra_job=None):
    """(budget, used, pending worst, lines)."""
    cl = plan["cluster"]
    rows = ledger(cl)
    used = RP.used_core_hours(rows)
    finals = set(r["pbs_jobid"] for r in rows if r["event"] == "final")
    pending = [r for r in rows if r["event"] == "submit" and r["pbs_jobid"] not in finals]
    pend_worst = 0.0
    for r in pending:
        try:
            pend_worst += float(r["note"].split("worst=")[1].split()[0])
        except (IndexError, ValueError):
            pend_worst += float(r.get("est_core_hours") or 0)
    b = plan.get("core_hour_budget")
    lines = ["  core-hours: used %.1f; queued/running (worst case) %.1f%s" %
             (used, pend_worst, "; this job (worst case) %.1f" % extra_worst if extra_job else "")]
    if b in (None, ""):
        lines.append("  budget: UNKNOWN (set core_hour_budget in config/run_plan.%s.json)" % plan["plan"])
    elif str(b).lower() == "unlimited":
        lines.append("  budget: unlimited (%s)" % plan.get("budget_source", ""))
    else:
        rem = float(b) - used - pend_worst - extra_worst
        lines.append("  budget %.1f -> remaining after %s, worst case: %.1f core-hours" %
                     (float(b), "this job" if extra_job else "jobs in flight", rem))
    return b, used, pend_worst, lines


# ---------------------------------------------------------------------------------------------------------------
def cmd_submit_check(a):
    cl = a.cluster
    plan = RP.load_plan(cl)
    job = RP.job_of(plan, a.job)
    say = print
    if job is None:
        say("SUBMIT: REFUSED job %s is not in plan %s (an extra job needs an \"unplanned\" entry with a reason and a "
            "spec, committed and synced)" % (a.job, plan["plan"]))
        return 1
    kind = kind_of(job)
    secs, cores, ch, worst, wt = estimate(plan, job)
    say("SUBMIT CHECK %s on %s: %s job, %d cells, %d node%s x %d cpus, walltime %s, estimate %.1f core-h (worst "
        "case %.1f)" % (a.job, cl, kind, len(job["cells"]), job["nodes"], "s" if job["nodes"] > 1 else "",
                        job["ncpus_per_node"], wt, ch, worst))
    # the cluster must hold exactly this code and this plan
    head = head_commit()
    if a.remote_commit != head:
        say("SUBMIT: REFUSED the cluster has commit %s, local HEAD is %s: run cluster/ops/sync.sh first" %
            (a.remote_commit[:12] or "none", head[:12]))
        return 1
    local_plan = sha256(RP.plan_path(cl))
    if a.remote_plan != local_plan:
        say("SUBMIT: REFUSED the plan on the cluster (%s) differs from the local plan (%s): commit it and run sync.sh" %
            ((a.remote_plan or "none")[:12], local_plan[:12]))
        return 1
    say("  cluster holds commit %s and the same plan file" % head[:12])
    # one submission per planned job; more only with a recorded rerun reason
    prev = [r for r in ledger(cl) if r["event"] == "submit" and r["job"] == a.job]
    allowed = 1 + sum(1 for x in plan.get("reruns", []) if x.get("job") == a.job and x.get("reason"))
    if len(prev) >= allowed:
        say("SUBMIT: REFUSED %s was already submitted (%s); a resubmission is a rerun: add {\"job\": \"%s\", "
            "\"reason\": \"...\"} to \"reruns\" in the plan, commit and sync" %
            (a.job, ", ".join(r["pbs_jobid"] for r in prev), a.job))
        return 1
    if prev:
        say("  rerun %d of %s, reason recorded in the plan" % (len(prev), a.job))
    if kind != "validate":
        if kind == "timed" and not plan.get("frozen"):
            say("SUBMIT: REFUSED plan %s is not frozen: freeze it (\"frozen\": true) after the calibration job, commit "
                "and sync, then submit timed jobs" % plan["plan"])
            return 1
        val = [e for e in C.validated_entries() if e["cluster"] == cl]
        if not val:
            say("SUBMIT: REFUSED no binary has been qualified on %s yet: submit %s-validate, then poll.sh and "
                "fetch.sh" % (cl, cl))
            return 1
        if a.remote_bin not in set(e["binary_sha256"] for e in val):
            say("SUBMIT: REFUSED bin/p3cg on %s (sha256 %s) is not a binary qualified there (qualified: %s)" %
                (cl, (a.remote_bin or "missing")[:12], ", ".join(e["binary_sha256"][:12] for e in val)))
            return 1
        say("  bin/p3cg on the cluster is the qualified binary %s" % a.remote_bin[:12])
        b, used, pend, lines = budget_lines(plan, worst, a.job)
        if b in (None, ""):
            say("SUBMIT: REFUSED the core-hour budget of %s is unknown: set core_hour_budget (a number, or "
                "\"unlimited\" for Atlas) from `hpc project`, commit and sync" % cl)
            return 1
        if str(b).lower() != "unlimited" and used + pend + worst > float(b):
            for line in lines:
                say(line)
            say("SUBMIT: REFUSED the worst case (walltime x cores) would exceed the budget")
            return 1
    say("SUBMIT CHECK: ALLOWED")
    return 0


def cmd_record_submit(a):
    cl = a.cluster
    plan = RP.load_plan(cl)
    job = RP.job_of(plan, a.job)
    secs, cores, ch, worst, wt = estimate(plan, job)
    pbs = plan.get("pbs", {})
    select = "select=%d:ncpus=%d:mpiprocs=%d" % (job["nodes"], job["ncpus_per_node"], job["ncpus_per_node"])
    if job.get("gpus_per_node"):
        select += ":ngpus=%d" % job["gpus_per_node"] + pbs.get("select_extra_gpu", "")
    else:
        select += pbs.get("select_extra", "")
    append_ledger(cl, {"pbs_jobid": a.pbs_id, "plan": plan["plan"], "job": a.job, "event": "submit", "utc": now(),
                       "nodes": job["nodes"], "ncpus_per_node": job["ncpus_per_node"],
                       "gpus_per_node": job.get("gpus_per_node", 0), "host": a.alias or cl, "commit": a.commit,
                       "cells": ";".join(job["cells"]), "select": select, "walltime": wt,
                       "est_core_hours": "%.2f" % ch, "note": "worst=%.2f kind=%s" % (worst, kind_of(job))})
    print("SUBMITTED %s as %s (commit %s, %d cells, walltime %s, estimate %.1f core-h, worst case %.1f)" %
          (a.job, a.pbs_id, a.commit[:12], len(job["cells"]), wt, ch, worst))
    for line in budget_lines(plan)[3]:
        print(line)
    return 0


def pending_ids(cl):
    rows = ledger(cl)
    finals = set(r["pbs_jobid"] for r in rows if r["event"] == "final")
    seen, out = set(), []
    for r in rows:
        if r["event"] == "submit" and r["pbs_jobid"] not in finals and r["pbs_jobid"] not in seen:
            seen.add(r["pbs_jobid"])
            out.append(r["pbs_jobid"])
    return out


def cmd_pending(a):
    print(" ".join(pending_ids(a.cluster)))
    return 0


# ---------------------------------------------------------------------------------------------------------------
def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^=== (.+?) ===\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return dict((k, "\n".join(v)) for k, v in out.items())


def parse_qstat_f(text):
    """PBS Pro `qstat -x -f` -> {job id: {attribute: value}}; continuation lines start with a tab."""
    jobs, cur, last = {}, None, None
    for line in text.splitlines():
        m = re.match(r"^Job Id:\s*(\S+)", line)
        if m:
            cur = jobs.setdefault(m.group(1), {})
            last = None
            continue
        if cur is None:
            continue
        m = re.match(r"^\s{4}([A-Za-z_.]+)\s=\s(.*)$", line)
        if m:
            last = m.group(1)
            cur[last] = m.group(2).strip()
        elif line.startswith("\t") and last:
            cur[last] += line.strip()
    return jobs


def hms(s):
    try:
        h, m, sec = (int(x) for x in s.split(":"))
        return h * 3600 + m * 60 + sec
    except (ValueError, AttributeError):
        return None


def match_job(qs, pbs_id):
    if pbs_id in qs:
        return qs[pbs_id]
    short = pbs_id.split(".")[0]
    for k, v in qs.items():
        if k.split(".")[0] == short:
            return v
    return None


def cmd_poll_parse(a):
    cl = a.cluster
    plan = RP.load_plan(cl)
    S = sections(sys.stdin.read())
    qs = parse_qstat_f(S.get("QSTAT", ""))
    events = list(csv.DictReader([l for l in S.get("EVENTS", "").splitlines() if l.strip()]))
    val = list(csv.DictReader([l for l in S.get("VALIDATED", "").splitlines() if l.strip()]))
    subs = dict((r["pbs_jobid"], r) for r in ledger(cl) if r["event"] == "submit")
    failures = 0
    print("POLL %s  %s" % (cl, now()))
    print("  %-26s %-24s %-9s %-5s %-21s %-8s %s" % ("job", "PBS id", "state", "exit", "walltime used/req",
                                                    "core-h", "records / flags"))
    for pid in pending_ids(cl):
        sub = subs.get(pid, {})
        job = RP.job_of(plan, sub.get("job", "")) or {"cells": []}
        q = match_job(qs, pid)
        ev = [e for e in events if e.get("pbs_jobid") == pid]
        flags = []
        state, exitst, wused, wreq, ncpus = "?", "", None, hms(sub.get("walltime", "")), None
        if q:
            state = q.get("job_state", "?")
            exitst = q.get("Exit_status", "")
            wused = hms(q.get("resources_used.walltime", ""))
            wreq = hms(q.get("Resource_List.walltime", "")) or wreq
            try:
                ncpus = int(q.get("Resource_List.ncpus", "") or 0) or None
            except ValueError:
                ncpus = None
            source = "qstat"
        else:
            st = [e for e in ev if e["event"] == "start"]
            en = [e for e in ev if e["event"] == "end"]
            if st and en:
                state = "F"
                t0 = datetime.datetime.strptime(st[0]["utc"], "%Y-%m-%dT%H:%M:%SZ")
                t1 = datetime.datetime.strptime(en[-1]["utc"], "%Y-%m-%dT%H:%M:%SZ")
                wused = int((t1 - t0).total_seconds())
                flags.append("not in qstat history: from the job's own record, exit status unknown")
            elif st:
                state = "lost?"
                flags.append("started but no end record and not in qstat")
            else:
                state = "unknown"
                flags.append("not in qstat and no record (queued before history? purged?)")
            source = "record"
        if ncpus is None:
            ncpus = int(sub.get("nodes") or 0) * int(sub.get("ncpus_per_node") or 0)
        finished = state in FINISHED
        ch = (wused or 0) * ncpus / 3600.0 if finished else None
        records = ""
        if finished:
            if exitst not in ("", "0"):
                flags.append("FAILED (exit %s)" % exitst)
            if exitst in ("271", "-29", "-11") or (wused and wreq and wused >= wreq - 30):
                flags.append("walltime exceeded")
            if job["cells"]:
                want = sum(plan["cells"][c].get("repeats", 1) for c in job["cells"])
                try:
                    got = int(S.get("ROWS %s" % pid, "0").strip() or 0)
                except ValueError:
                    got = 0
                records = "%d/%d rows" % (got, want)
                if got < want:
                    flags.append("missing records")
            else:
                ok = [v for v in val if v.get("cluster") == cl and v.get("verdict") == "QUALIFIED"]
                records = "%d qualified binar%s" % (len(ok), "y" if len(ok) == 1 else "ies")
                if not ok:
                    flags.append("no qualified binary recorded")
        bad = any(f.startswith(("FAILED", "walltime", "missing", "no qualified", "started but")) for f in flags)
        failures += bad
        print("  %-26s %-24s %-9s %-5s %-21s %-8s %s" % (
            sub.get("job", "?"), pid, {"Q": "queued", "R": "running", "H": "held", "E": "exiting", "F": "finished",
                                       "X": "finished"}.get(state, state), exitst or "-",
            "%s/%s" % (fmt_hms(wused), fmt_hms(wreq)), "%.1f" % ch if ch is not None else "-",
            "; ".join([records] + flags if records else flags) or "-"))
        if finished:
            append_ledger(cl, {"pbs_jobid": pid, "plan": plan["plan"], "job": sub.get("job", ""), "event": "final",
                               "utc": now(), "nodes": sub.get("nodes", ""), "ncpus_per_node": sub.get("ncpus_per_node", ""),
                               "state": state, "exit_status": exitst, "walltime_used": fmt_hms(wused),
                               "core_hours_used": "%.2f" % ch, "note": ("%s; " % source) + "; ".join([records] + flags)})
    if not pending_ids(cl) and not subs:
        print("  no submitted jobs recorded")
    for line in budget_lines(plan)[3]:
        print(line)
    print("POLL: %s" % ("%d job(s) need attention (see flags; RUNBOOK.md 'Failures')" % failures if failures
                         else "no failures"))
    return 2 if failures else 0


def fmt_hms(s):
    if s is None:
        return "-"
    return "%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


# ---------------------------------------------------------------------------------------------------------------
def cmd_merge_fetched(a):
    cl, st = a.cluster, a.staging
    dst = os.path.join(C.RESULTS, cl)
    os.makedirs(dst, exist_ok=True)
    copied = 0
    src = os.path.join(st, "cluster")
    for root, _, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for f in files:
            if rel == "." and f in ("jobs.csv", "calibration.json"):
                continue
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
            s, d = os.path.join(root, f), os.path.join(dst, rel, f)
            if not os.path.exists(d) or sha256(s) != sha256(d):
                shutil.copy2(s, d)
                copied += 1
    # ledger: append the cluster's start/end rows that are not here yet
    new_ev = 0
    rj = os.path.join(src, "jobs.csv")
    if os.path.exists(rj):
        have = set((r["pbs_jobid"], r["event"], r["utc"]) for r in ledger(cl))
        for r in C.read_csv(rj):
            if (r["pbs_jobid"], r["event"], r["utc"]) not in have:
                append_ledger(cl, r)
                new_ev += 1
    # validated binaries: append this cluster's qualified entries
    new_val = 0
    rv = os.path.join(st, "validated_binaries.csv")
    if os.path.exists(rv):
        have = set((e["utc"], e["binary_sha256"], e["cluster"]) for e in
                   (C.read_csv(C.VALIDATED) if os.path.exists(C.VALIDATED) else []))
        for e in C.read_csv(rv):
            if e.get("cluster") == cl and (e["utc"], e["binary_sha256"], e["cluster"]) not in have:
                C.append_csv(C.VALIDATED, C.VALIDATED_COLUMNS, e)
                new_val += 1
    print("FETCH %s: %d files new or changed, %d ledger events added, %d qualified binaries added" %
          (cl, copied, new_ev, new_val))
    return 0


# ---------------------------------------------------------------------------------------------------------------
def cmd_calibrate(a):
    cl = a.cluster
    plan = RP.load_plan(cl)
    d = os.path.join(C.RESULTS, cl)
    rows = [r for r in run_record.load_rows([d]) if r["mode"] == "fixed" and r["breakdown"] == "0"
            and r["cluster"] == cl and int(r["gpus"]) == 0] if os.path.isdir(d) else []
    B = plan["model"]["bytes_per_point_iter"]
    cpn = plan["cores_per_node"]

    def bw(rs):
        by = {}
        for r in rs:
            by.setdefault(r["cell"], []).append(r)
        vals = []
        for cid, xs in by.items():
            t = statistics.median(float(x["t_total"]) for x in xs)
            r = xs[0]
            vals.append(int(r["unknowns"]) * B[r["cg"]] * int(r["iters"]) / t / 1e9)
        return (statistics.median(vals), sorted(by)) if vals else (None, [])

    serial = [r for r in rows if r["ranks"] == "1" and r["threads"] == "1" and int(r["unknowns"]) >= 4000000]
    node = [r for r in rows if r["nodes"] == "1" and int(r["ranks"]) * int(r["threads"]) == cpn]
    bc, cs = bw(serial)
    bn, cn = bw(node)
    if bc is None and bn is None:
        print("CALIBRATION %s: not enough rows yet (needs a serial run with >= 4e6 unknowns or a full-node run; the "
              "%s-calibrate job provides both)" % (cl, cl))
        return 0
    old = dict((j["id"], estimate(plan, j)) for j in plan["jobs"])
    oldM = RP.model_of(plan)
    cal = {"utc": now(), "from_jobs": sorted(set(r["pbs_jobid"] for r in serial + node)),
           "from_cells": cs + cn, "bw_core_gbs": round(bc, 3) if bc else None,
           "bw_node_gbs": round(bn, 3) if bn else None,
           "note": "bytes per point and iteration from the plan model; median over cells and repeats"}
    with open(os.path.join(d, "calibration.json"), "w") as f:
        json.dump(cal, f, indent=1)
    newM = RP.model_of(plan)
    print("CALIBRATION %s from %s (%d serial cells, %d full-node cells):" % (cl, ", ".join(cal["from_jobs"]),
                                                                         len(cs), len(cn)))
    print("  bandwidth of one core: %.2f -> %.2f GB/s;  of one %d-core node: %.1f -> %.1f GB/s" %
          (oldM["bw_core_gbs"], newM["bw_core_gbs"], cpn, oldM["bw_node_gbs"], newM["bw_node_gbs"]))
    submitted = set(r["job"] for r in ledger(cl) if r["event"] == "submit")
    tot_o = tot_n = 0.0
    print("  estimates for jobs not yet submitted (core-h expected / worst case; walltime):")
    for j in plan["jobs"]:
        if j["id"] in submitted:
            continue
        o, n = old[j["id"]], estimate(plan, j)
        tot_o += o[3]
        tot_n += n[3]
        print("    %-30s %6.1f / %6.1f  %s   ->  %6.1f / %6.1f  %s" % (j["id"], o[2], o[3], o[4], n[2], n[3], n[4]))
    print("  remaining jobs, worst case: %.1f -> %.1f core-hours" % (tot_o, tot_n))
    for line in budget_lines(plan)[3]:
        print(line)
    print("  generated PBS scripts now request the recalibrated walltimes (run_plan.py pbs uses calibration.json)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("cluster")
    p.add_argument("alias")
    for name in ("submit-check", "record-submit", "pending", "poll-parse", "merge-fetched", "calibrate", "plan-sha"):
        p = sub.add_parser(name)
        p.add_argument("--cluster", required=True)
        p.add_argument("--job")
        p.add_argument("--alias")
        p.add_argument("--pbs-id")
        p.add_argument("--commit", default="")
        p.add_argument("--remote-commit", default="")
        p.add_argument("--remote-plan", default="")
        p.add_argument("--remote-bin", default="")
        p.add_argument("--staging")
    a = ap.parse_args()
    if a.cmd == "cluster":
        print(cluster_of(a.alias))
        return 0
    if a.cmd == "plan-sha":
        print(sha256(RP.plan_path(a.cluster)))
        return 0
    return {"submit-check": cmd_submit_check, "record-submit": cmd_record_submit, "pending": cmd_pending,
            "poll-parse": cmd_poll_parse, "merge-fetched": cmd_merge_fetched, "calibrate": cmd_calibrate}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
