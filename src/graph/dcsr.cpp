#include "dcsr.hpp"

#if defined(_OPENMP)
#include <omp.h>
#endif

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "../par.hpp"
#include "csrfile.hpp"

#if defined(P3_OFFLOAD)
#error "the graph solver is CPU only (MPI + OpenMP threads); build it without P3_OFFLOAD"
#endif

namespace {
int nthreads() {
#if defined(_OPENMP)
    return omp_get_max_threads();
#else
    return 1;
#endif
}
int thread_id() {
#if defined(_OPENMP)
    return omp_get_thread_num();
#else
    return 0;
#endif
}

// Reads n items of `bytes` each at `offset` with independent MPI-IO reads (chunks below 2^31 bytes).
bool read_at(MPI_File fh, int64_t offset, void* buf, int64_t n, int bytes) {
    char* p = static_cast<char*>(buf);
    const int64_t chunk = (int64_t(1) << 30) / bytes;
    while (n > 0) {
        const int64_t m = std::min(n, chunk);
        MPI_Status st;
        if (MPI_File_read_at(fh, MPI_Offset(offset), p, int(m * bytes), MPI_BYTE, &st) != MPI_SUCCESS) return false;
        int got = 0;
        MPI_Get_count(&st, MPI_BYTE, &got);
        if (got != int(m * bytes)) return false;
        offset += m * bytes;
        p += m * bytes;
        n -= m;
    }
    return true;
}

// Thread boundaries over a sequence of rows with the given prefix of nonzeros: thread t gets [tb[t], tb[t+1]).
std::vector<long> balance(long n, int T, const std::vector<long>& prefix) {
    std::vector<long> tb(T + 1, 0);
    const long total = prefix[n];
    for (int t = 1; t < T; ++t) {
        const long goal = total * t / T;
        tb[t] = long(std::lower_bound(prefix.begin(), prefix.begin() + n + 1, goal) - prefix.begin());
        tb[t] = std::max(tb[t], tb[t - 1]);
    }
    tb[T] = n;
    return tb;
}

const int kDummy = 0;
const int* ptr_or_dummy(const std::vector<int>& v) { return v.empty() ? &kDummy : v.data(); }
}  // namespace

DistGraph::~DistGraph() {
    if (gcomm != MPI_COMM_NULL) MPI_Comm_free(&gcomm);
}

int DistGraph::owner(int64_t gid) const {
    return int(std::upper_bound(bounds.begin(), bounds.end(), gid) - bounds.begin()) - 1;
}

Rows DistGraph::rows() const {
    Rows R;
    R.R0 = n_pad / RL;
    R.R1 = 1;
    R.T0 = RL;
    R.T1 = 0;
    R.base = 0;
    R.RL = RL;
    return R;
}

bool DistGraph::load(const std::string& path, Part part, double keep, uint64_t keep_seed, MPI_Comm c,
                     std::string& err) {
    comm = c;
    MPI_Comm_rank(comm, &rank);
    MPI_Comm_size(comm, &size);
    const double t0 = MPI_Wtime();

    // Header, rowptr and the SNAP ids: read by rank 0, broadcast (every rank needs the degrees to partition and the
    // SNAP ids of its neighbours for the keep filter).
    int64_t hdr[5] = {0, 0, 0, 0, 0};  // V, nnz, E, order, ok
    std::vector<int64_t> rowptr_g, orig_g;
    if (rank == 0) {
        FILE* f = fopen(path.c_str(), "rb");
        char magic[8];
        if (f && fread(magic, 1, 8, f) == 8 && memcmp(magic, csrfile::kMagic, 8) == 0 && fread(hdr, 8, 4, f) == 4) {
            fseek(f, 0, SEEK_END);
            const long long bytes = ftell(f);
            if (hdr[0] > 0 && hdr[0] < (int64_t(1) << 31) && bytes == csrfile::file_bytes(hdr[0], hdr[1])) {
                rowptr_g.resize(hdr[0] + 1);
                orig_g.resize(hdr[0]);
                fseek(f, long(csrfile::rowptr_offset()), SEEK_SET);
                bool ok = fread(rowptr_g.data(), 8, rowptr_g.size(), f) == rowptr_g.size();
                fseek(f, long(csrfile::orig_offset(hdr[0], hdr[1])), SEEK_SET);
                ok = ok && fread(orig_g.data(), 8, orig_g.size(), f) == orig_g.size();
                hdr[4] = (ok && rowptr_g[0] == 0 && rowptr_g[hdr[0]] == hdr[1]) ? 1 : 0;
            }
        }
        if (f) fclose(f);
    }
    MPI_Bcast(hdr, 5, MPI_INT64_T, 0, comm);
    if (!hdr[4]) {
        err = "cannot read " + path + " (missing, not a P3CSR001 file, or truncated)";
        return false;
    }
    V = hdr[0];
    nnz_file = hdr[1];
    E_file = hdr[2];
    order = int(hdr[3]);
    if (V < size) {
        err = "fewer vertices than ranks";
        return false;
    }
    rowptr_g.resize(V + 1);
    orig_g.resize(V);
    MPI_Bcast(rowptr_g.data(), int(V + 1), MPI_INT64_T, 0, comm);
    MPI_Bcast(orig_g.data(), int(V), MPI_INT64_T, 0, comm);

    // Partition. rows: equal row counts. nnz: equal (degree + 1) sums, i.e. equal nonzeros of L + aI per rank.
    bounds.assign(size + 1, 0);
    bounds[size] = V;
    for (int p = 1; p < size; ++p) {
        int64_t b;
        if (part == Part::rows) {
            b = V * p / size;
        } else {
            const int64_t W = nnz_file + V, goal = W * p / size;  // weight of rows [0, i) = rowptr[i] + i
            int64_t lo = 0, hi = V;
            while (lo < hi) {
                const int64_t mid = (lo + hi) / 2;
                if (rowptr_g[mid] + mid < goal) lo = mid + 1;
                else hi = mid;
            }
            b = lo;
        }
        bounds[p] = std::min(std::max(b, bounds[p - 1] + 1), V - (size - p));  // at least one row per rank
    }
    row0 = bounds[rank];
    row1 = bounds[rank + 1];
    n_own = long(row1 - row0);
    n_pad = ((n_own + RL - 1) / RL) * RL;

    // My rows' neighbours (global ids), straight from the file.
    const int64_t e0 = rowptr_g[row0], e1 = rowptr_g[row1];
    std::vector<int32_t> colg(size_t(e1 - e0));
    {
        MPI_File fh;
        if (MPI_File_open(comm, path.c_str(), MPI_MODE_RDONLY, MPI_INFO_NULL, &fh) != MPI_SUCCESS) {
            err = "MPI_File_open failed on " + path;
            return false;
        }
        int ok = read_at(fh, csrfile::col_offset(V) + 4 * e0, colg.data(), e1 - e0, 4) ? 1 : 0, all = 0;
        MPI_File_close(&fh);
        MPI_Allreduce(&ok, &all, 1, MPI_INT, MPI_MIN, comm);
        if (!all) {
            err = "MPI_File_read_at failed on " + path;
            return false;
        }
    }
    t_read = MPI_Wtime() - t0;

    // Keep filter (edge sparsification), symmetric in the two endpoints' SNAP ids.
    const bool filter = keep < 1.0;
    const uint64_t thresh = filter ? uint64_t(keep * 18446744073709551615.0) : ~uint64_t(0);
    const uint64_t salt = csrfile::mix64(keep_seed ^ 0x5eedULL);
    rowptr.assign(n_own + 1, 0);
    std::vector<int64_t> nb;  // kept neighbours, global ids
    nb.reserve(colg.size());
    for (long i = 0; i < n_own; ++i) {
        const int64_t gi = row0 + i;
        for (int64_t k = rowptr_g[gi] - e0; k < rowptr_g[gi + 1] - e0; ++k) {
            const int64_t gj = colg[k];
            if (filter) {
                const uint64_t u = uint64_t(std::min(orig_g[gi], orig_g[gj])),
                               v = uint64_t(std::max(orig_g[gi], orig_g[gj]));
                if (csrfile::mix64(csrfile::mix64(u ^ salt) ^ v) > thresh) continue;
            }
            nb.push_back(gj);
        }
        rowptr[i + 1] = int64_t(nb.size());
    }
    std::vector<int32_t>().swap(colg);
    orig.assign(orig_g.begin() + row0, orig_g.begin() + row1);
    deg.resize(n_own);
    for (long i = 0; i < n_own; ++i) deg[i] = double(rowptr[i + 1] - rowptr[i]);
    int64_t ekept_loc = int64_t(nb.size()), ekept = 0;
    MPI_Allreduce(&ekept_loc, &ekept, 1, MPI_INT64_T, MPI_SUM, comm);
    E_kept = ekept / 2;
    if (rank == 0) orig_all.swap(orig_g);
    std::vector<int64_t>().swap(orig_g);
    std::vector<int64_t>().swap(rowptr_g);

    // Ghosts: distinct non-owned neighbours, ascending global id (= grouped by owner rank, ascending).
    ghost_gid.clear();
    for (int64_t gj : nb)
        if (gj < row0 || gj >= row1) ghost_gid.push_back(gj);
    std::sort(ghost_gid.begin(), ghost_gid.end());
    ghost_gid.erase(std::unique(ghost_gid.begin(), ghost_gid.end()), ghost_gid.end());
    n_ghost = long(ghost_gid.size());
    col.resize(nb.size());
    cut_entries = 0;
    std::vector<char> has_ghost(n_own, 0);
    for (long i = 0; i < n_own; ++i)
        for (int64_t k = rowptr[i]; k < rowptr[i + 1]; ++k) {
            const int64_t gj = nb[k];
            if (gj >= row0 && gj < row1) {
                col[k] = int32_t(gj - row0);
            } else {
                col[k] = int32_t(n_pad + (std::lower_bound(ghost_gid.begin(), ghost_gid.end(), gj) -
                                          ghost_gid.begin()));
                ++cut_entries;
                has_ghost[i] = 1;
            }
        }
    std::vector<int64_t>().swap(nb);
    rows_inner.clear();
    rows_bnd.clear();
    for (long i = 0; i < n_own; ++i) (has_ghost[i] ? rows_bnd : rows_inner).push_back(int32_t(i));

    // Receive lists (what I need from whom) -> send lists (what others need from me), built once.
    rcnt_all.assign(size, 0);
    for (int64_t gj : ghost_gid) rcnt_all[owner(gj)]++;
    scnt_all.assign(size, 0);
    MPI_Alltoall(rcnt_all.data(), 1, MPI_INT, scnt_all.data(), 1, MPI_INT, comm);
    rdsp_all.assign(size, 0);
    sdsp_all.assign(size, 0);
    for (int p = 1; p < size; ++p) {
        rdsp_all[p] = rdsp_all[p - 1] + rcnt_all[p - 1];
        sdsp_all[p] = sdsp_all[p - 1] + scnt_all[p - 1];
    }
    const long nsend = size ? long(sdsp_all[size - 1] + scnt_all[size - 1]) : 0;
    std::vector<int64_t> want(nsend);
    MPI_Alltoallv(ghost_gid.data(), rcnt_all.data(), rdsp_all.data(), MPI_INT64_T, want.data(), scnt_all.data(),
                  sdsp_all.data(), MPI_INT64_T, comm);
    send_idx.resize(nsend);
    int bad = 0, anybad = 0;
    for (long k = 0; k < nsend; ++k) {
        if (want[k] < row0 || want[k] >= row1) bad = 1;
        send_idx[k] = int32_t(want[k] - row0);
    }
    MPI_Allreduce(&bad, &anybad, 1, MPI_INT, MPI_MAX, comm);
    if (anybad) {
        err = "ghost request for a row this rank does not own (send lists inconsistent)";
        return false;
    }
    src.clear();
    dst.clear();
    rcnt.clear();
    rdsp.clear();
    scnt.clear();
    sdsp.clear();
    for (int p = 0; p < size; ++p) {
        if (rcnt_all[p] > 0) {
            src.push_back(p);
            rcnt.push_back(rcnt_all[p]);
            rdsp.push_back(rdsp_all[p]);
        }
        if (scnt_all[p] > 0) {
            dst.push_back(p);
            scnt.push_back(scnt_all[p]);
            sdsp.push_back(sdsp_all[p]);
        }
    }
    long scratch = 0;
#if PLANT_GHOST_BUG == 1
    // PLANTED BUG (validation only): the first source neighbour's ghosts are received into a scratch area behind
    // the ghost region, so the ghost values from that neighbour are never stored where the operator reads them.
    if (!src.empty()) {
        scratch = rcnt[0];
        rdsp[0] = int(n_ghost);
        rdsp_all[src[0]] = int(n_ghost);
    }
#endif
    n_alloc = n_pad + n_ghost + scratch;
    if (gcomm != MPI_COMM_NULL) MPI_Comm_free(&gcomm);
    MPI_Dist_graph_create_adjacent(comm, int(src.size()), ptr_or_dummy(src), MPI_UNWEIGHTED, int(dst.size()),
                                   ptr_or_dummy(dst), MPI_UNWEIGHTED, MPI_INFO_NULL, 0, &gcomm);
    t_build = MPI_Wtime() - t0 - t_read;
    return true;
}

CsrOperator::CsrOperator(DistGraph& gr, double a_, Exchange e) : g(gr), a(a_), ex(e) {
    sendbuf.assign(g.send_idx.size() + 1, 0.0);
    const int T = nthreads();
    std::vector<long> pre(g.n_own + 1, 0);
    for (long i = 0; i < g.n_own; ++i) pre[i + 1] = pre[i] + long(g.rowptr[i + 1] - g.rowptr[i]) + 1;
    tb_all = balance(g.n_own, T, pre);
    auto lpre = [&](const std::vector<int32_t>& L) {
        std::vector<long> p(L.size() + 1, 0);
        for (size_t k = 0; k < L.size(); ++k) p[k + 1] = p[k] + long(g.rowptr[L[k] + 1] - g.rowptr[L[k]]) + 1;
        return p;
    };
    tb_inner = balance(long(g.rows_inner.size()), T, lpre(g.rows_inner));
    tb_bnd = balance(long(g.rows_bnd.size()), T, lpre(g.rows_bnd));
}

void CsrOperator::pack(const double* x) {
    const long n = long(g.send_idx.size());
    const int32_t* idx = g.send_idx.data();
    double* sb = sendbuf.data();
    P3_FOR1()
    for (long k = 0; k < n; ++k) sb[k] = x[idx[k]];
}

// Rows [0, n_own), each thread a contiguous range with about the same number of nonzeros.
double CsrOperator::rows_range(const double* x, double* y) const {
    const int64_t* rp = g.rowptr.data();
    const int32_t* cl = g.col.data();
    const double* dg = g.deg.data();
    const long* tb = tb_all.data();
    const double aa = a;
    double d = 0.0;
#if defined(_OPENMP)
#pragma omp parallel reduction(+ : d)
#endif
    {
        const int t = thread_id();
        for (long i = tb[t]; i < tb[t + 1]; ++i) {
            double s = (dg[i] + aa) * x[i];
            for (int64_t k = rp[i]; k < rp[i + 1]; ++k) s -= x[cl[k]];
            y[i] = s;
            d += x[i] * s;
        }
    }
    for (long i = g.n_own; i < g.n_pad; ++i) y[i] = 0.0;
    return d;
}

double CsrOperator::rows_list(const std::vector<int32_t>& L, const std::vector<long>& tbv, const double* x,
                              double* y) const {
    const int64_t* rp = g.rowptr.data();
    const int32_t* cl = g.col.data();
    const double* dg = g.deg.data();
    const int32_t* li = L.data();
    const long* tb = tbv.data();
    const double aa = a;
    double d = 0.0;
#if defined(_OPENMP)
#pragma omp parallel reduction(+ : d)
#endif
    {
        const int t = thread_id();
        for (long q = tb[t]; q < tb[t + 1]; ++q) {
            const long i = li[q];
            double s = (dg[i] + aa) * x[i];
            for (int64_t k = rp[i]; k < rp[i + 1]; ++k) s -= x[cl[k]];
            y[i] = s;
            d += x[i] * s;
        }
    }
    return d;
}

double CsrOperator::apply(double* x, double* y, Timers& t) {
    double d = 0.0;
    const double t0 = MPI_Wtime();
    if (g.size == 1) {
        d = rows_range(x, y);
        t.compute += MPI_Wtime() - t0;
        return d;
    }
    pack(x);
    double* ghosts = x + g.n_pad;
    if (ex == Exchange::alltoallv) {
        MPI_Alltoallv(sendbuf.data(), g.scnt_all.data(), g.sdsp_all.data(), MPI_DOUBLE, ghosts, g.rcnt_all.data(),
                      g.rdsp_all.data(), MPI_DOUBLE, g.comm);
    } else if (ex == Exchange::neighbor) {
        MPI_Neighbor_alltoallv(sendbuf.data(), ptr_or_dummy(g.scnt), ptr_or_dummy(g.sdsp), MPI_DOUBLE, ghosts,
                               ptr_or_dummy(g.rcnt), ptr_or_dummy(g.rdsp), MPI_DOUBLE, g.gcomm);
    } else {
        MPI_Request rq;
        MPI_Ineighbor_alltoallv(sendbuf.data(), ptr_or_dummy(g.scnt), ptr_or_dummy(g.sdsp), MPI_DOUBLE, ghosts,
                                ptr_or_dummy(g.rcnt), ptr_or_dummy(g.rdsp), MPI_DOUBLE, g.gcomm, &rq);
        const double t1 = MPI_Wtime();
        d = rows_list(g.rows_inner, tb_inner, x, y);
        const double t2 = MPI_Wtime();
        MPI_Wait(&rq, MPI_STATUS_IGNORE);
        const double t3 = MPI_Wtime();
        d += rows_list(g.rows_bnd, tb_bnd, x, y);
        for (long i = g.n_own; i < g.n_pad; ++i) y[i] = 0.0;
        const double t4 = MPI_Wtime();
        t.halo += (t1 - t0) + (t3 - t2);
        t.compute += (t2 - t1) + (t4 - t3);
        return d;
    }
    const double t1 = MPI_Wtime();
    d = rows_range(x, y);
    t.halo += t1 - t0;
    t.compute += MPI_Wtime() - t1;
    return d;
}
