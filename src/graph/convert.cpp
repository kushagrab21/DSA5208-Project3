// p3convert: SNAP edge list (+ community or label file) -> binary CSR files for p3graph. Serial, no MPI.
//
//   gzip -dc com-amazon.ungraph.txt.gz | p3convert --edges - --cmty <(gzip -dc com-amazon.top5000.cmty.txt.gz) \
//       --out DATA/com-amazon --name com-amazon
//   (scripts/convert_snap.sh does exactly this for each dataset.)
//
// What it does, in order (every count is printed and written to PREFIX.meta.json):
//   1. reads "u v" lines (lines starting with '#' are comments); the graph is treated as UNDIRECTED (email-Eu-core is
//      directed: an edge in either direction becomes one undirected edge);
//   2. relabels the SNAP ids to 0..V-1 in ascending SNAP-id order ("natural" order); V counts every id that appears
//      in an edge line, so a vertex whose only edge was a self-loop stays as an isolated vertex;
//   3. drops self-loops, stores both directions of every edge, and drops duplicates (u v listed twice, or u v and v u);
//   4. writes PREFIX.natural.csr, and PREFIX.bfs.csr with the vertices renumbered in BFS (Cuthill-McKee) order:
//      components in order of their lowest-degree unvisited vertex, neighbours visited in ascending degree. BFS
//      order puts neighbours at nearby numbers, so a 1D row partition cuts fewer edges;
//   5. maps the communities (--cmty: one community per line, SNAP ids; --labels: "vertex label" lines, one community
//      per label) to the vertex numbers of each order: PREFIX.natural.cmty, PREFIX.bfs.cmty. Ids that are not in the
//      graph are dropped and counted.
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "csrfile.hpp"

namespace {

// Streaming parser for whitespace-separated unsigned integers, line by line.
struct Reader {
    FILE* f;
    std::vector<char> buf;
    size_t pos = 0, len = 0;
    bool eof = false;
    explicit Reader(FILE* f_) : f(f_), buf(1 << 22) {}
    int get() {
        if (pos == len) {
            if (eof) return -1;
            len = fread(buf.data(), 1, buf.size(), f);
            pos = 0;
            if (len == 0) {
                eof = true;
                return -1;
            }
        }
        return (unsigned char)buf[pos++];
    }
    // Reads one line into out (numbers only). Returns false at end of input. Comment lines give an empty list.
    bool line(std::vector<uint64_t>& out, bool& bad) {
        out.clear();
        bad = false;
        int c = get();
        if (c < 0) return false;
        if (c == '#') {
            while (c >= 0 && c != '\n') c = get();
            return true;
        }
        while (c >= 0 && c != '\n') {
            if (c >= '0' && c <= '9') {
                uint64_t v = 0;
                while (c >= '0' && c <= '9') {
                    v = v * 10 + uint64_t(c - '0');
                    c = get();
                }
                out.push_back(v);
                continue;
            }
            if (c != ' ' && c != '\t' && c != '\r') bad = true;
            c = get();
        }
        return true;
    }
};

FILE* open_in(const std::string& p) {
    if (p == "-") return stdin;
    FILE* f = fopen(p.c_str(), "rb");
    if (!f) {
        fprintf(stderr, "p3convert: cannot open %s: %s\n", p.c_str(), strerror(errno));
        exit(2);
    }
    return f;
}

struct Csr {
    int64_t V = 0, nnz = 0;
    std::vector<int64_t> rowptr;
    std::vector<int32_t> col;
    std::vector<int64_t> orig;
};

bool write_csr(const std::string& path, const Csr& g, int order) {
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    int64_t hdr[4] = {g.V, g.nnz, g.nnz / 2, order};
    bool ok = fwrite(csrfile::kMagic, 1, 8, f) == 8 && fwrite(hdr, 8, 4, f) == 4 &&
              fwrite(g.rowptr.data(), 8, g.rowptr.size(), f) == g.rowptr.size() &&
              fwrite(g.col.data(), 4, g.col.size(), f) == g.col.size() &&
              fwrite(g.orig.data(), 8, g.orig.size(), f) == g.orig.size();
    return fclose(f) == 0 && ok;
}

// Cuthill-McKee order: perm[new] = old.
std::vector<int32_t> bfs_order(const Csr& g) {
    const int64_t V = g.V;
    std::vector<int32_t> byDeg(V), perm;
    perm.reserve(V);
    for (int64_t i = 0; i < V; ++i) byDeg[i] = int32_t(i);
    auto deg = [&](int32_t v) { return g.rowptr[v + 1] - g.rowptr[v]; };
    std::stable_sort(byDeg.begin(), byDeg.end(), [&](int32_t a, int32_t b) { return deg(a) < deg(b); });
    std::vector<char> seen(V, 0);
    std::vector<int32_t> nb;
    for (int32_t s : byDeg) {
        if (seen[s]) continue;
        seen[s] = 1;
        size_t head = perm.size();
        perm.push_back(s);
        while (head < perm.size()) {
            const int32_t u = perm[head++];
            nb.clear();
            for (int64_t k = g.rowptr[u]; k < g.rowptr[u + 1]; ++k)
                if (!seen[g.col[k]]) {
                    seen[g.col[k]] = 1;
                    nb.push_back(g.col[k]);
                }
            std::stable_sort(nb.begin(), nb.end(), [&](int32_t a, int32_t b) { return deg(a) < deg(b); });
            perm.insert(perm.end(), nb.begin(), nb.end());
        }
    }
    return perm;
}

Csr permute(const Csr& g, const std::vector<int32_t>& perm, std::vector<int32_t>& inv) {
    Csr h;
    h.V = g.V;
    h.nnz = g.nnz;
    inv.assign(g.V, 0);
    for (int64_t i = 0; i < g.V; ++i) inv[perm[i]] = int32_t(i);
    h.rowptr.assign(g.V + 1, 0);
    for (int64_t i = 0; i < g.V; ++i) h.rowptr[i + 1] = h.rowptr[i] + (g.rowptr[perm[i] + 1] - g.rowptr[perm[i]]);
    h.col.resize(g.nnz);
    h.orig.resize(g.V);
    for (int64_t i = 0; i < g.V; ++i) {
        const int32_t o = perm[i];
        int64_t w = h.rowptr[i];
        for (int64_t k = g.rowptr[o]; k < g.rowptr[o + 1]; ++k) h.col[w++] = inv[g.col[k]];
        std::sort(h.col.begin() + h.rowptr[i], h.col.begin() + h.rowptr[i + 1]);
        h.orig[i] = g.orig[o];
    }
    return h;
}

// Mean and max |i - j| over the stored entries (how far apart neighbours are numbered).
void spread(const Csr& g, double& mean, int64_t& mx) {
    double s = 0;
    mx = 0;
    for (int64_t i = 0; i < g.V; ++i)
        for (int64_t k = g.rowptr[i]; k < g.rowptr[i + 1]; ++k) {
            const int64_t d = std::llabs(int64_t(g.col[k]) - i);
            s += double(d);
            mx = std::max(mx, d);
        }
    mean = g.nnz ? s / double(g.nnz) : 0.0;
}

bool write_cmty(const std::string& path, const std::vector<std::vector<int32_t>>& cm, const std::string& note) {
    FILE* f = fopen(path.c_str(), "w");
    if (!f) return false;
    fprintf(f, "# p3cmty-1 communities=%zu %s\n", cm.size(), note.c_str());
    for (const auto& c : cm) {
        for (size_t i = 0; i < c.size(); ++i) fprintf(f, i ? " %d" : "%d", c[i]);
        fprintf(f, "\n");
    }
    return fclose(f) == 0;
}

void usage() {
    fprintf(stderr,
            "usage: p3convert --edges FILE|- --out PREFIX [--name NAME] [--cmty FILE | --labels FILE] [--source-label S]\n"
            "  writes PREFIX.natural.csr PREFIX.bfs.csr (+ .cmty for each) and PREFIX.meta.json\n");
}

}  // namespace

int main(int argc, char** argv) {
    std::string edges, out, name = "graph", cmty, labels, cmty_label;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto val = [&]() -> std::string {
            if (i + 1 >= argc) {
                usage();
                exit(2);
            }
            return argv[++i];
        };
        if (a == "--edges") edges = val();
        else if (a == "--out") out = val();
        else if (a == "--name") name = val();
        else if (a == "--cmty") cmty = val();
        else if (a == "--labels") labels = val();
        else if (a == "--source-label") cmty_label = val();  // how the community file is named in the outputs
        else {
            usage();
            return 2;
        }
    }
    if (edges.empty() || out.empty() || (!cmty.empty() && !labels.empty())) {
        usage();
        return 2;
    }

    // 1. edge lines
    std::vector<uint64_t> raw;  // (u << 32) | v, SNAP ids
    long long lines = 0, comments = 0, badlines = 0;
    {
        FILE* f = open_in(edges);
        Reader rd(f);
        std::vector<uint64_t> nums;
        bool bad;
        while (rd.line(nums, bad)) {
            if (nums.empty()) {
                ++comments;
                continue;
            }
            if (nums.size() < 2 || bad) {
                ++badlines;
                continue;
            }
            if (nums[0] >= (1ULL << 32) || nums[1] >= (1ULL << 32)) {
                fprintf(stderr, "p3convert: vertex id >= 2^32 on line %lld; not supported\n", lines + comments + 1);
                return 3;
            }
            raw.push_back((nums[0] << 32) | nums[1]);
            ++lines;
        }
        if (f != stdin) fclose(f);
    }
    if (badlines) fprintf(stderr, "p3convert: WARNING %lld malformed lines skipped\n", badlines);

    // 2. relabel: natural order = ascending SNAP id
    std::vector<uint32_t> ids;
    ids.reserve(2 * raw.size());
    for (uint64_t e : raw) {
        ids.push_back(uint32_t(e >> 32));
        ids.push_back(uint32_t(e & 0xffffffffULL));
    }
    std::sort(ids.begin(), ids.end());
    ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
    const int64_t V = int64_t(ids.size());
    if (V >= (1LL << 31)) {
        fprintf(stderr, "p3convert: more than 2^31 vertices; not supported\n");
        return 3;
    }
    auto newid = [&](uint32_t s) { return int32_t(std::lower_bound(ids.begin(), ids.end(), s) - ids.begin()); };

    // 3. both directions, no self-loops, no duplicates
    long long self_loops = 0;
    std::vector<uint64_t> ent;
    ent.reserve(2 * raw.size());
    for (uint64_t e : raw) {
        const int32_t a = newid(uint32_t(e >> 32)), b = newid(uint32_t(e & 0xffffffffULL));
        if (a == b) {
            ++self_loops;
            continue;
        }
        ent.push_back((uint64_t(a) << 32) | uint64_t(uint32_t(b)));
        ent.push_back((uint64_t(b) << 32) | uint64_t(uint32_t(a)));
    }
    std::vector<uint64_t>().swap(raw);
    std::sort(ent.begin(), ent.end());
    const size_t before = ent.size();
    ent.erase(std::unique(ent.begin(), ent.end()), ent.end());
    const long long dup_entries = (long long)(before - ent.size());

    Csr g;
    g.V = V;
    g.nnz = int64_t(ent.size());
    g.rowptr.assign(V + 1, 0);
    g.col.resize(ent.size());
    for (size_t k = 0; k < ent.size(); ++k) {
        g.rowptr[(ent[k] >> 32) + 1]++;
        g.col[k] = int32_t(ent[k] & 0xffffffffULL);
    }
    std::vector<uint64_t>().swap(ent);
    for (int64_t i = 0; i < V; ++i) g.rowptr[i + 1] += g.rowptr[i];
    g.orig.resize(V);
    for (int64_t i = 0; i < V; ++i) g.orig[i] = int64_t(ids[i]);
    int64_t dmax = 0, isolated = 0;
    for (int64_t i = 0; i < V; ++i) {
        const int64_t d = g.rowptr[i + 1] - g.rowptr[i];
        dmax = std::max(dmax, d);
        if (d == 0) ++isolated;
    }

    // 4. BFS order
    std::vector<int32_t> perm = bfs_order(g), inv;
    Csr h = permute(g, perm, inv);
    double sp_nat = 0, sp_bfs = 0;
    int64_t bw_nat = 0, bw_bfs = 0;
    spread(g, sp_nat, bw_nat);
    spread(h, sp_bfs, bw_bfs);

    // 5. communities
    std::vector<std::vector<int32_t>> cm;
    long long cm_lines = 0, cm_members = 0, cm_dropped = 0;
    std::string cm_src = cmty.empty() ? labels : cmty;
    const std::string cm_name = cmty_label.empty() ? cm_src : cmty_label;
    if (!cm_src.empty()) {
        FILE* f = open_in(cm_src);
        Reader rd(f);
        std::vector<uint64_t> nums;
        bool bad;
        std::map<uint64_t, std::vector<int32_t>> bylabel;
        while (rd.line(nums, bad)) {
            if (nums.empty()) continue;
            ++cm_lines;
            if (!labels.empty()) {
                if (nums.size() != 2) {
                    ++badlines;
                    continue;
                }
                ++cm_members;
                auto it = std::lower_bound(ids.begin(), ids.end(), uint32_t(nums[0]));
                if (nums[0] >= (1ULL << 32) || it == ids.end() || *it != uint32_t(nums[0])) {
                    ++cm_dropped;
                    continue;
                }
                bylabel[nums[1]].push_back(int32_t(it - ids.begin()));
            } else {
                std::vector<int32_t> c;
                for (uint64_t s : nums) {
                    ++cm_members;
                    auto it = std::lower_bound(ids.begin(), ids.end(), uint32_t(s));
                    if (s >= (1ULL << 32) || it == ids.end() || *it != uint32_t(s)) {
                        ++cm_dropped;
                        continue;
                    }
                    c.push_back(int32_t(it - ids.begin()));
                }
                std::sort(c.begin(), c.end());
                c.erase(std::unique(c.begin(), c.end()), c.end());
                cm.push_back(c);  // kept even if empty, so line numbers stay the community numbers
            }
        }
        for (auto& kv : bylabel) {
            std::sort(kv.second.begin(), kv.second.end());
            cm.push_back(kv.second);
        }
        if (f != stdin) fclose(f);
    }
    std::vector<std::vector<int32_t>> cmb(cm.size());
    for (size_t c = 0; c < cm.size(); ++c) {
        for (int32_t v : cm[c]) cmb[c].push_back(inv[v]);
        std::sort(cmb[c].begin(), cmb[c].end());
    }

    const std::string note = "source=" + (cm_src.empty() ? std::string("none") : cm_name) +
                             (labels.empty() ? " kind=cmty" : " kind=labels");
    bool ok = write_csr(out + ".natural.csr", g, 0) && write_csr(out + ".bfs.csr", h, 1);
    if (!cm_src.empty())
        ok = ok && write_cmty(out + ".natural.cmty", cm, note + " order=natural") &&
             write_cmty(out + ".bfs.cmty", cmb, note + " order=bfs");
    if (!ok) {
        fprintf(stderr, "p3convert: cannot write %s.*\n", out.c_str());
        return 4;
    }
    size_t cmax = 0, cmin = cm.empty() ? 0 : SIZE_MAX;
    for (const auto& c : cm) {
        cmax = std::max(cmax, c.size());
        cmin = std::min(cmin, c.size());
    }
    FILE* m = fopen((out + ".meta.json").c_str(), "w");
    if (!m) return 4;
    fprintf(m,
            "{\n \"schema\": \"p3graphmeta-1\", \"name\": \"%s\",\n \"edge_lines\": %lld, \"comment_lines\": %lld, "
            "\"malformed_lines\": %lld,\n \"self_loops_dropped\": %lld, \"duplicate_entries_dropped\": %lld,\n"
            " \"vertices\": %lld, \"edges\": %lld, \"nonzeros_offdiag\": %lld, \"isolated_vertices\": %lld,\n"
            " \"avg_degree\": %.6f, \"max_degree\": %lld,\n"
            " \"neighbour_spread_natural\": {\"mean\": %.3f, \"max\": %lld},\n"
            " \"neighbour_spread_bfs\": {\"mean\": %.3f, \"max\": %lld},\n"
            " \"communities\": %zu, \"community_lines\": %lld, \"community_members\": %lld, "
            "\"community_members_dropped\": %lld,\n \"community_size_max\": %zu, \"community_size_min\": %zu,\n"
            " \"community_kind\": \"%s\"\n}\n",
            name.c_str(), lines, comments, badlines, self_loops, dup_entries, (long long)V, (long long)(g.nnz / 2),
            (long long)g.nnz, (long long)isolated, V ? double(g.nnz) / double(V) : 0.0, (long long)dmax, sp_nat,
            (long long)bw_nat, sp_bfs, (long long)bw_bfs, cm.size(), cm_lines, cm_members, cm_dropped, cmax,
            cm.empty() ? 0 : cmin, cm_src.empty() ? "none" : (labels.empty() ? "cmty" : "labels"));
    fclose(m);
    printf("p3convert %s: edge_lines=%lld self_loops=%lld duplicate_entries=%lld V=%lld E=%lld avg_degree=%.3f "
           "max_degree=%lld isolated=%lld communities=%zu members_dropped=%lld spread_natural=%.1f spread_bfs=%.1f\n",
           name.c_str(), lines, self_loops, dup_entries, (long long)V, (long long)(g.nnz / 2),
           V ? double(g.nnz) / double(V) : 0.0, (long long)dmax, (long long)isolated, cm.size(), cm_dropped, sp_nat,
           sp_bfs);
    return 0;
}
