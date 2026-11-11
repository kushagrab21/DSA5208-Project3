"""Shared helpers for the Project 3 checks. Standard library only, Python >= 3.6 (cluster login nodes)."""
import csv
import hashlib
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# P3_RESULTS redirects all check outputs (used for scratch qualifications that must not touch results/).
RESULTS = os.environ.get("P3_RESULTS") or os.path.join(REPO, "results")
# P3_CONFIG / P3_GENERATED redirect the run plans and the generated PBS scripts (fake-cluster tests use scratch copies).
CONFIG = os.environ.get("P3_CONFIG") or os.path.join(REPO, "config")
GENERATED = os.environ.get("P3_GENERATED") or os.path.join(REPO, "cluster", "generated")
VALIDATED = os.path.join(RESULTS, "validated_binaries.csv")
CLUSTERS = ("atlas", "vanda")  # the only clusters whose rows may reach a report figure

# Must match record_columns() in src/record.cpp.
RECORD_COLUMNS = [
    "schema", "utc", "cluster", "host", "pbs_jobid", "cell", "tag",
    "nodes", "ranks", "threads", "gpus",
    "dim", "n", "unknowns", "nonzeros", "decomp", "pdims", "local_max", "local_min",
    "cg", "halo", "mode", "iters_req", "tol", "iters", "repeat",
    "t_total", "t_halo", "t_reduce", "t_compute", "t_other", "t_halo_max", "t_reduce_max", "t_compute_max",
    "t_setup", "msgs_per_exch", "doubles_per_exch_max", "allreduces", "exchanges",
    "rel_res", "true_rel_res", "err_max", "err_l2", "converged", "breakdown",
    "binary_sha256", "git_sha", "build", "mpi_thread", "problem",
]
RECORD_SCHEMA = "p3run-1"

VALIDATED_COLUMNS = ["utc", "cluster", "host", "binary_sha256", "binary", "build", "validate_sha256",
                     "cases", "bug_binaries_refused", "verdict"]


class Refused(Exception):
    """A check refuses the next step."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path, columns, row):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new:
            w.writeheader()
        w.writerow(row)


def validated_entries():
    if not os.path.exists(VALIDATED):
        return []
    return [r for r in read_csv(VALIDATED) if r.get("verdict") == "QUALIFIED"]


def is_validated(sha, cluster=None):
    for r in validated_entries():
        if r["binary_sha256"] == sha and (cluster is None or r["cluster"] == cluster):
            return True
    return False


def default_launcher():
    """mpirun prefix for checks. Override with P3_MPIRUN (the cluster env scripts set it)."""
    env = os.environ.get("P3_MPIRUN")
    if env:
        return env.split()
    try:
        out = subprocess.run(["mpirun", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True, timeout=30).stdout
    except Exception:
        out = ""
    if "Open MPI" in out:
        # Forward the thread count, allow more ranks than cores on a laptop, and do not pin threads to one core.
        return ["mpirun", "--oversubscribe", "--bind-to", "none", "-x", "OMP_NUM_THREADS"]
    return ["mpirun"]


def binary_version(binary, launcher=None):
    """Runs `binary --version` (1 rank) and returns its key=value fields."""
    cmd = (launcher or default_launcher()) + ["-np", "1", binary, "--version"]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                         timeout=120).stdout
    fields = {}
    for line in out.splitlines():
        if line.startswith("p3cg "):
            head, _, build = line.partition(" build=")  # build is last and may contain spaces
            fields["build"] = build.strip()
            for tok in head.split()[1:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    fields[k] = v
    return fields


def eprint(*a):
    print(*a, file=sys.stderr)
