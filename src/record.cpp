#include "record.hpp"

#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>

#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif

// ---------------------------------------------------------------------------------------------------------------
// SHA-256 (FIPS 180-4), used to identify the exact binary that produced each row.
// ---------------------------------------------------------------------------------------------------------------
namespace {
struct Sha256 {
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint64_t len = 0;
    unsigned char buf[64];
    size_t nbuf = 0;
    static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
    void block(const unsigned char* p) {
        static const uint32_t k[64] = {
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
        uint32_t w[64];
        for (int i = 0; i < 16; ++i)
            w[i] = (uint32_t(p[4 * i]) << 24) | (uint32_t(p[4 * i + 1]) << 16) | (uint32_t(p[4 * i + 2]) << 8) |
                   uint32_t(p[4 * i + 3]);
        for (int i = 16; i < 64; ++i) {
            uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 64; ++i) {
            uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = hh + S1 + ch + k[i] + w[i];
            uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + mj;
            hh = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = b;
            b = a;
            a = t1 + t2;
        }
        h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    void update(const unsigned char* p, size_t n) {
        len += n;
        while (n > 0) {
            size_t take = 64 - nbuf;
            if (take > n) take = n;
            memcpy(buf + nbuf, p, take);
            nbuf += take;
            p += take;
            n -= take;
            if (nbuf == 64) {
                block(buf);
                nbuf = 0;
            }
        }
    }
    std::string hex() {
        uint64_t bits = len * 8;
        unsigned char pad = 0x80;
        update(&pad, 1);
        unsigned char z = 0;
        while (nbuf != 56) update(&z, 1);
        unsigned char lb[8];
        for (int i = 0; i < 8; ++i) lb[i] = (unsigned char)(bits >> (56 - 8 * i));
        update(lb, 8);
        char out[65];
        for (int i = 0; i < 8; ++i) snprintf(out + 8 * i, 9, "%08x", h[i]);
        return std::string(out, 64);
    }
};
}  // namespace

std::string sha256_file(const std::string& path) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return "";
    Sha256 s;
    unsigned char b[1 << 16];
    size_t n;
    while ((n = fread(b, 1, sizeof b, f)) > 0) s.update(b, n);
    fclose(f);
    return s.hex();
}

std::string sha256_string(const std::string& data) {
    Sha256 s;
    s.update(reinterpret_cast<const unsigned char*>(data.data()), data.size());
    return s.hex();
}

std::string self_exe_path() {
    char buf[PATH_MAX];
#if defined(__APPLE__)
    uint32_t sz = sizeof buf;
    if (_NSGetExecutablePath(buf, &sz) != 0) return "";
    char real[PATH_MAX];
    if (!realpath(buf, real)) return std::string(buf);
    return std::string(real);
#else
    ssize_t n = readlink("/proc/self/exe", buf, sizeof buf - 1);
    if (n <= 0) return "";
    buf[n] = 0;
    return std::string(buf);
#endif
}

std::string sanitize(const std::string& s) {
    std::string o;
    for (char c : s) {
        if (c == ',' || c == '"' || c == '\n' || c == '\r') o += ';';
        else o += c;
    }
    return o;
}

std::string pbs_jobid() {
    const char* j = getenv("PBS_JOBID");
    if (!j || !*j) return "none";
    return sanitize(j);
}

std::string detect_cluster(const std::string& host, std::string& warning) {
    const char* env = getenv("P3_CLUSTER");
    const bool in_pbs = pbs_jobid() != "none";
    std::string want;
    if (env && *env) {
        want = env;
    } else if (host.find("atlas") != std::string::npos) {
        want = "atlas";
    } else if (host.find("vanda") != std::string::npos) {
        want = "vanda";
    } else {
        want = "local";
    }
    if (want != "atlas" && want != "vanda") {
        if (want != "local") warning = "P3_CLUSTER=" + want + " is not atlas|vanda|local; recorded as local";
        return "local";
    }
    if (!in_pbs) {
        warning = "cluster " + want + " requested but PBS_JOBID is not set; recorded as local";
        return "local";
    }
    return want;
}

std::string utc_now() {
    time_t t = time(nullptr);
    struct tm g;
    gmtime_r(&t, &g);
    char b[32];
    strftime(b, sizeof b, "%Y-%m-%dT%H:%M:%SZ", &g);
    return b;
}

const char* kRecordSchema = "p3run-1";

const std::vector<std::string>& record_columns() {
    static const std::vector<std::string> c = {
        "schema", "utc", "cluster", "host", "pbs_jobid", "cell", "tag",
        "nodes", "ranks", "threads", "gpus",
        "dim", "n", "unknowns", "nonzeros", "decomp", "pdims", "local_max", "local_min",
        "cg", "halo", "mode", "iters_req", "tol", "iters", "repeat",
        "t_total", "t_halo", "t_reduce", "t_compute", "t_other", "t_halo_max", "t_reduce_max", "t_compute_max",
        "t_setup", "msgs_per_exch", "doubles_per_exch_max", "allreduces", "exchanges",
        "rel_res", "true_rel_res", "err_max", "err_l2", "converged", "breakdown",
        "binary_sha256", "git_sha", "build", "mpi_thread", "problem"};
    return c;
}

static bool mkdirs(const std::string& dir) {
    if (dir.empty()) return true;
    std::string cur;
    for (size_t i = 0; i <= dir.size(); ++i) {
        if (i == dir.size() || dir[i] == '/') {
            if (!cur.empty() && mkdir(cur.c_str(), 0755) != 0 && errno != EEXIST) return false;
        }
        if (i < dir.size()) cur += dir[i];
    }
    return true;
}

bool append_record(const std::string& path, const std::vector<std::string>& values, std::string& err) {
    const auto& cols = record_columns();
    if (values.size() != cols.size()) {
        err = "record has " + std::to_string(values.size()) + " values for " + std::to_string(cols.size()) +
              " columns";
        return false;
    }
    size_t slash = path.find_last_of('/');
    if (slash != std::string::npos && !mkdirs(path.substr(0, slash))) {
        err = "cannot create directory for " + path;
        return false;
    }
    struct stat sb;
    const bool exists = stat(path.c_str(), &sb) == 0 && sb.st_size > 0;
    std::ofstream f(path, std::ios::app);
    if (!f) {
        err = "cannot open " + path;
        return false;
    }
    if (!exists) {
        for (size_t i = 0; i < cols.size(); ++i) f << (i ? "," : "") << cols[i];
        f << "\n";
    }
    for (size_t i = 0; i < values.size(); ++i) f << (i ? "," : "") << sanitize(values[i]);
    f << "\n";
    return bool(f);
}

bool append_csv_row(const std::string& path, const std::vector<std::string>& cols,
                    const std::vector<std::string>& values, std::string& err) {
    if (values.size() != cols.size()) {
        err = "record has " + std::to_string(values.size()) + " values for " + std::to_string(cols.size()) +
              " columns";
        return false;
    }
    size_t slash = path.find_last_of('/');
    if (slash != std::string::npos && !mkdirs(path.substr(0, slash))) {
        err = "cannot create directory for " + path;
        return false;
    }
    std::string header;
    for (size_t i = 0; i < cols.size(); ++i) header += (i ? "," : "") + cols[i];
    struct stat sb;
    const bool exists = stat(path.c_str(), &sb) == 0 && sb.st_size > 0;
    if (exists) {
        std::ifstream in(path);
        std::string first;
        std::getline(in, first);
        if (first != header) {
            err = path + " exists with a different header (another record schema); not appending";
            return false;
        }
    }
    std::ofstream f(path, std::ios::app);
    if (!f) {
        err = "cannot open " + path;
        return false;
    }
    if (!exists) f << header << "\n";
    for (size_t i = 0; i < values.size(); ++i) f << (i ? "," : "") << sanitize(values[i]);
    f << "\n";
    return bool(f);
}
