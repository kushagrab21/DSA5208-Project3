// Run record: one CSV row per timed run, appended by rank 0 of the solver itself.
//
// cluster is "atlas" or "vanda" only inside a PBS job (PBS_JOBID set) whose P3_CLUSTER (or host name) names that
// cluster; otherwise it is "local". checks/run_record.py refuses to give "local" rows to a report figure.
#pragma once
#include <string>
#include <vector>

std::string sha256_file(const std::string& path);  // hex digest, "" on failure
std::string self_exe_path();
std::string detect_cluster(const std::string& host, std::string& warning);
std::string pbs_jobid();  // PBS_JOBID or "none"
std::string utc_now();
std::string sanitize(const std::string& s);  // no commas, quotes or newlines (CSV-safe)

// Column names, in order. The schema tag is the first column of every row.
extern const char* kRecordSchema;
const std::vector<std::string>& record_columns();

// Appends one row (values in record_columns() order); writes the header when the file is new.
// Creates parent directories. Returns false with err on failure.
bool append_record(const std::string& path, const std::vector<std::string>& values, std::string& err);
