// p3graph: semi-supervised community labelling on a SNAP graph with the distributed CG of p3cg.
// For each of K communities c: solve (L + aI) x_c = b_c, b_c the indicator of s seed vertices of c, with classic or
// pipelined CG (cg_impl.hpp, the same code as the Poisson solver); label each evaluated vertex by argmax_c x_c.
// Usage: p3graph --help
#include <mpi.h>
#if defined(_OPENMP)
#include <omp.h>
#endif

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include "../cg_impl.hpp"
#include "../par.hpp"
#include "../record.hpp"
#include "dcsr.hpp"
#include "label.hpp"

#ifndef P3_GIT_SHA
#define P3_GIT_SHA "unknown"
#endif

namespace {
const char* kGraphSchema = "p3graph-1";

const std::vector<std::string>& graph_columns() {
    static const std::vector<std::string> c = {
        "schema", "utc", "cluster", "host", "pbs_jobid", "cell", "tag", "nodes", "ranks", "threads",
        "dataset", "order", "keep", "vertices", "edges", "nonzeros", "avg_degree", "max_degree",
        "part", "exchange", "cg", "a", "K", "s", "theta", "seed", "rhs", "mode", "iters_req", "tol",
        "iters", "iters_min", "iters_max", "repeat",
        "t_total", "t_solve", "t_iter", "t_halo", "t_reduce", "t_compute", "t_other", "t_halo_max", "t_reduce_max",
        "t_compute_max", "t_setup", "t_read",
        "rows_max", "rows_min", "nnz_max", "nnz_min", "nnz_imbalance", "ghosts_max", "ghosts_sum", "edge_cut",
        "cut_fraction", "neighbors_max", "doubles_per_exch_max", "allreduces", "exchanges",
        "rel_res", "true_rel_res", "converged", "breakdown",
        "accuracy", "eval_vertices", "unreached", "majority", "random", "seeds_sha", "communities",
        "binary_sha256", "git_sha", "build", "mpi_thread"};
    return c;
}

struct Opts {
    std::string graph, order = "natural", dataset, record, cell = "-", tag = "-", dump, spmv_dump, write_seeds;
    Part part = Part::nnz;
    Exchange ex = Exchange::neighbor;
    CgVariant cg = CgVariant::classic;
    double a = 1.0, theta = 0.1, keep = 1.0, tol = 1e-8;
    int K = 10, s = 5, repeats = 1, rhs = -1;
    long iters = 0, maxit = 100000;
    bool fixed = false;
    uint64_t seed = 1;
    bool no_record = false, quiet = false, version = false, help = false;
};

const char* kUsage =
    "p3graph --graph DATA/NAME [options]     (reads DATA/NAME.<order>.csr and DATA/NAME.<order>.cmty)\n"
    "  --order natural|bfs       vertex numbering of the files (default natural)\n"
    "  --part rows|nnz           1D row partition: equal rows or equal nonzeros (default nnz)\n"
    "  --exchange alltoallv|neighbor|overlap   ghost exchange (default neighbor)\n"
    "  --cg classic|pipelined    (default classic)\n"
    "  --a A                     shift in L + aI (default 1)\n"
    "  --K K --s S               communities and seeds per community (default 10, 5)\n"
    "  --theta T                 overlap allowed between chosen communities (default 0.1)\n"
    "  --seed N                  seed of the seed choice (default 1)\n"
    "  --keep P                  keep each edge with probability P (sparsified graph; default 1)\n"
    "  --tol T | --iters N       stop at ||r|| <= T ||b|| (default 1e-8), or exactly N iterations (timing)\n"
    "  --maxit M                 iteration cap in tolerance mode (default 100000)\n"
    "  --rhs R                   solve only the first R of the K systems (default K; accuracy needs all K)\n"
    "  --repeats R               repeat the R solves, one record row each (default 1)\n"
    "  --record PATH --no-record --cell ID --tag TAG --quiet\n"
    "  --dump PATH               after repeat 1: the solutions x_c, c < R, in global vertex order (float64)\n"
    "  --spmv-dump PATH          y = (L + aI) v, v_i = 1 + (snap_id_i mod 1000)/1000, global order (float64)\n"
    "  --write-seeds PATH        the chosen communities and seeds (SNAP ids) as text\n"
    "  --version\n";

bool parse(int argc, char** argv, Opts& o, std::string& err) {
    bool tol_given = false;
    for (int i = 1; i < argc && err.empty(); ++i) {
        const std::string a = argv[i];
        auto val = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                err = std::string(name) + " needs a value";
                return "0";
            }
            return argv[++i];
        };
        try {
            if (a == "--graph") o.graph = val("--graph");
            else if (a == "--order") o.order = val("--order");
            else if (a == "--dataset") o.dataset = val("--dataset");
            else if (a == "--part") {
                const std::string v = val("--part");
                if (v == "rows") o.part = Part::rows;
                else if (v == "nnz") o.part = Part::nnz;
                else err = "--part must be rows or nnz";
            } else if (a == "--exchange") {
                const std::string v = val("--exchange");
                if (v == "alltoallv") o.ex = Exchange::alltoallv;
                else if (v == "neighbor") o.ex = Exchange::neighbor;
                else if (v == "overlap") o.ex = Exchange::overlap;
                else err = "--exchange must be alltoallv, neighbor or overlap";
            } else if (a == "--cg") {
                const std::string v = val("--cg");
                if (v == "classic") o.cg = CgVariant::classic;
                else if (v == "pipelined") o.cg = CgVariant::pipelined;
                else err = "--cg must be classic or pipelined";
            } else if (a == "--a") o.a = std::stod(val("--a"));
            else if (a == "--K") o.K = std::stoi(val("--K"));
            else if (a == "--s") o.s = std::stoi(val("--s"));
            else if (a == "--theta") o.theta = std::stod(val("--theta"));
            else if (a == "--seed") o.seed = std::stoull(val("--seed"));
            else if (a == "--keep") o.keep = std::stod(val("--keep"));
            else if (a == "--tol") {
                o.tol = std::stod(val("--tol"));
                tol_given = true;
            } else if (a == "--iters") {
                o.iters = std::stol(val("--iters"));
                o.fixed = true;
            } else if (a == "--maxit") o.maxit = std::stol(val("--maxit"));
            else if (a == "--rhs") o.rhs = std::stoi(val("--rhs"));
            else if (a == "--repeats") o.repeats = std::stoi(val("--repeats"));
            else if (a == "--record") o.record = val("--record");
            else if (a == "--no-record") o.no_record = true;
            else if (a == "--cell") o.cell = val("--cell");
            else if (a == "--tag") o.tag = val("--tag");
            else if (a == "--dump") o.dump = val("--dump");
            else if (a == "--spmv-dump") o.spmv_dump = val("--spmv-dump");
            else if (a == "--write-seeds") o.write_seeds = val("--write-seeds");
            else if (a == "--quiet") o.quiet = true;
            else if (a == "--version") o.version = true;
            else if (a == "--help" || a == "-h") o.help = true;
            else err = "unknown option " + a;
        } catch (const std::exception&) {
            err = "bad value for " + a;
        }
    }
    if (!err.empty() || o.version || o.help) return err.empty();
    if (o.graph.empty()) err = "--graph is required";
    else if (o.order != "natural" && o.order != "bfs") err = "--order must be natural or bfs";
    else if (!(o.a > 0)) err = "--a must be > 0 (L + aI is then symmetric positive definite)";
    else if (o.K < 2) err = "--K must be >= 2";
    else if (o.s < 1) err = "--s must be >= 1";
    else if (!(o.keep > 0 && o.keep <= 1)) err = "--keep must be in (0, 1]";
    else if (o.fixed && tol_given) err = "--iters (fixed) and --tol (tolerance) are exclusive";
    else if (o.fixed && o.iters < 1) err = "--iters must be >= 1";
    else if (o.repeats < 1) err = "--repeats must be >= 1";
    if (o.rhs < 0) o.rhs = o.K;
    if (err.empty() && (o.rhs < 1 || o.rhs > o.K)) err = "--rhs must be in 1..K";
    if (o.dataset.empty()) {
        const size_t sl = o.graph.find_last_of('/');
        o.dataset = sl == std::string::npos ? o.graph : o.graph.substr(sl + 1);
    }
    return err.empty();
}

std::string build_string() {
    std::ostringstream s;
#if defined(_OPENMP)
    s << "omp=" << _OPENMP;
#else
    s << "omp=0";
#endif
    s << ";offload=0;graph=1;bug=" << PLANT_GHOST_BUG;
#if defined(__VERSION__)
    s << ";cxx=" << __VERSION__;
#endif
    char lib[MPI_MAX_LIBRARY_VERSION_STRING];
    int len = 0;
    MPI_Get_library_version(lib, &len);
    std::string l(lib, len);
    const size_t nl = l.find_first_of(",\n\r");
    if (nl != std::string::npos) l = l.substr(0, nl);
    if (l.size() > 60) l = l.substr(0, 60);
    s << ";mpi=" << l;
    return sanitize(s.str());
}

std::string fmt(double v) {
    char b[40];
    snprintf(b, sizeof b, "%.6e", v);
    return b;
}
std::string thread_level(int p) {
    switch (p) {
        case MPI_THREAD_SINGLE: return "single";
        case MPI_THREAD_FUNNELED: return "funneled";
        case MPI_THREAD_SERIALIZED: return "serialized";
        default: return "multiple";
    }
}
const char* part_name(Part p) { return p == Part::rows ? "rows" : "nnz"; }
const char* ex_name(Exchange e) {
    return e == Exchange::alltoallv ? "alltoallv" : e == Exchange::neighbor ? "neighbor" : "overlap";
}

// Gathers the owned entries of x (global order = rank order) to rank 0 and appends them to f there.
bool gather_append(const DistGraph& g, const double* x, FILE* f) {
    std::vector<int> cnt(g.size), dsp(g.size);
    for (int p = 0; p < g.size; ++p) {
        cnt[p] = int(g.bounds[p + 1] - g.bounds[p]);
        dsp[p] = int(g.bounds[p]);
    }
    std::vector<double> all(g.rank == 0 ? size_t(g.V) : 1);
    MPI_Gatherv(x, int(g.n_own), MPI_DOUBLE, all.data(), cnt.data(), dsp.data(), MPI_DOUBLE, 0, g.comm);
    int ok = 1;
    if (g.rank == 0) ok = fwrite(all.data(), 8, size_t(g.V), f) == size_t(g.V) ? 1 : 0;
    MPI_Bcast(&ok, 1, MPI_INT, 0, g.comm);
    return ok == 1;
}
}  // namespace

int main(int argc, char** argv) {
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    int wrank = 0, wsize = 1;
    MPI_Comm_rank(MPI_COMM_WORLD, &wrank);
    MPI_Comm_size(MPI_COMM_WORLD, &wsize);
    Opts o;
    std::string err;
    const bool ok = parse(argc, argv, o, err);
    const std::string sha = sha256_file(self_exe_path());
    if (o.version) {
        if (wrank == 0)
            printf("p3graph sha256=%s git=%s path=%s build=%s\n", sha.c_str(), P3_GIT_SHA, self_exe_path().c_str(),
                   build_string().c_str());
        MPI_Finalize();
        return 0;
    }
    if (!ok || o.help) {
        if (wrank == 0) {
            if (!ok) fprintf(stderr, "p3graph: %s\n", err.c_str());
            fputs(kUsage, ok ? stdout : stderr);
        }
        MPI_Finalize();
        return ok ? 0 : 2;
    }
    if (provided < MPI_THREAD_FUNNELED) {
        if (wrank == 0) fprintf(stderr, "p3graph: MPI provides %s, FUNNELED needed\n", thread_level(provided).c_str());
        MPI_Finalize();
        return 3;
    }
    // Everything that owns MPI objects lives inside this scope, so it is destroyed before MPI_Finalize.
    auto run = [&]() -> int {
        MPI_Comm node;
        MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, wrank, MPI_INFO_NULL, &node);
        int lrank = 0;
        MPI_Comm_rank(node, &lrank);
        int is_leader = lrank == 0 ? 1 : 0, nodes = 0;
        MPI_Allreduce(&is_leader, &nodes, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);
        MPI_Comm_free(&node);
        int threads = 1;
    #if defined(_OPENMP)
        threads = omp_get_max_threads();
    #endif
        char hostc[MPI_MAX_PROCESSOR_NAME];
        int hl = 0;
        MPI_Get_processor_name(hostc, &hl);
        const std::string host(hostc, hl);
        std::string cl_warn;
        const std::string cluster = detect_cluster(host, cl_warn);
        const std::string job = pbs_jobid();
        if (wrank == 0 && !cl_warn.empty()) fprintf(stderr, "p3graph: %s\n", cl_warn.c_str());

        // Load and partition (collective), then the labelling problem (rank 0, broadcast).
        MPI_Barrier(MPI_COMM_WORLD);
        const double ts0 = MPI_Wtime();
        DistGraph G;
        const std::string base = o.graph + "." + o.order;
        if (!G.load(base + ".csr", o.part, o.keep, o.seed, MPI_COMM_WORLD, err)) {
            if (wrank == 0) fprintf(stderr, "p3graph: %s\n", err.c_str());
            return 2;
        }
        Labelling L;
        int lab_ok = 1;
        if (wrank == 0 && !choose_labelling(base + ".cmty", G.V, G.orig_all, o.K, o.s, o.theta, o.seed, o.dataset, L,
                                            err)) {
            fprintf(stderr, "p3graph: %s\n", err.c_str());
            lab_ok = 0;
        }
        MPI_Bcast(&lab_ok, 1, MPI_INT, 0, MPI_COMM_WORLD);
        if (!lab_ok) {
            return 2;
        }
        // seeds (global ids) to every rank; the truth labels scattered by the partition
        std::vector<int64_t> seeds(size_t(o.K) * o.s);
        if (wrank == 0)
            for (int c = 0; c < o.K; ++c)
                for (int i = 0; i < o.s; ++i) seeds[size_t(c) * o.s + i] = L.seeds[c][i];
        MPI_Bcast(seeds.data(), int(seeds.size()), MPI_INT64_T, 0, MPI_COMM_WORLD);
        std::vector<int32_t> truth(G.n_own);
        {
            std::vector<int> cnt(G.size), dsp(G.size);
            for (int p = 0; p < G.size; ++p) {
                cnt[p] = int(G.bounds[p + 1] - G.bounds[p]);
                dsp[p] = int(G.bounds[p]);
            }
            MPI_Scatterv(wrank == 0 ? L.truth.data() : nullptr, cnt.data(), dsp.data(), MPI_INT32_T, truth.data(),
                         int(G.n_own), MPI_INT32_T, 0, MPI_COMM_WORLD);
        }
        double majority = L.majority;
        long n_eval = L.n_eval;
        MPI_Bcast(&majority, 1, MPI_DOUBLE, 0, MPI_COMM_WORLD);
        MPI_Bcast(&n_eval, 1, MPI_LONG, 0, MPI_COMM_WORLD);
        std::string seeds_sha = wrank == 0 ? sha256_string(L.record) : std::string(64, '0');
        std::string comms;
        if (wrank == 0)
            for (int c = 0; c < o.K; ++c) comms += (c ? ";" : "") + std::to_string(L.lines[c]);
        {
            char b[65];
            memcpy(b, seeds_sha.c_str(), 64);
            b[64] = 0;
            MPI_Bcast(b, 65, MPI_CHAR, 0, MPI_COMM_WORLD);
            seeds_sha = b;
        }
        if (wrank == 0 && !o.write_seeds.empty()) {
            std::ofstream f(o.write_seeds);
            f << L.record;
        }
        G.release_global();
        std::vector<int32_t>().swap(L.truth);

        CsrOperator A(G, o.a, o.ex);
        const long n = G.n_alloc;
        Vec b(n);
        Work W;
        W.x.alloc(n);
        W.r.alloc(n);
        W.p.alloc(n);
        if (o.cg == CgVariant::classic) {
            W.q.alloc(n);
        } else {
            W.w.alloc(n);
            W.s.alloc(n);
            W.z.alloc(n);
            W.nv.alloc(n);
        }
        MPI_Barrier(MPI_COMM_WORLD);
        double t_setup = MPI_Wtime() - ts0, t_setup_max = 0, t_read_max = 0;
        MPI_Allreduce(&t_setup, &t_setup_max, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&G.t_read, &t_read_max, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);

        // Partition statistics.
        long rows = G.n_own, rows_max = 0, rows_min = 0;
        long nnz_l = long(G.rowptr[G.n_own]) + G.n_own, nnz_max = 0, nnz_min = 0, nnz_sum = 0;
        long gh = G.n_ghost, gh_max = 0, gh_sum = 0, cut = G.cut_entries, cut_sum = 0;
        long nbrs = long(G.dst.size()), nbrs_max = 0, dbl = A.doubles_per_exchange(), dbl_max = 0;
        double dmax_l = 0, dmax = 0;
        for (long i = 0; i < G.n_own; ++i) dmax_l = std::max(dmax_l, G.deg[i]);
        MPI_Allreduce(&rows, &rows_max, 1, MPI_LONG, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&rows, &rows_min, 1, MPI_LONG, MPI_MIN, MPI_COMM_WORLD);
        MPI_Allreduce(&nnz_l, &nnz_max, 1, MPI_LONG, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&nnz_l, &nnz_min, 1, MPI_LONG, MPI_MIN, MPI_COMM_WORLD);
        MPI_Allreduce(&nnz_l, &nnz_sum, 1, MPI_LONG, MPI_SUM, MPI_COMM_WORLD);
        MPI_Allreduce(&gh, &gh_max, 1, MPI_LONG, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&gh, &gh_sum, 1, MPI_LONG, MPI_SUM, MPI_COMM_WORLD);
        MPI_Allreduce(&cut, &cut_sum, 1, MPI_LONG, MPI_SUM, MPI_COMM_WORLD);
        MPI_Allreduce(&nbrs, &nbrs_max, 1, MPI_LONG, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&dbl, &dbl_max, 1, MPI_LONG, MPI_MAX, MPI_COMM_WORLD);
        MPI_Allreduce(&dmax_l, &dmax, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
        const long edge_cut = cut_sum / 2;
        const double imbalance = double(nnz_max) * G.size / double(std::max(1L, nnz_sum));
        const double avg_deg = 2.0 * double(G.E_kept) / double(G.V);

        const std::string rec_path =
            o.record.empty() ? ("results/" + cluster + "/" + (job == "none" ? std::string("local") : job) + ".graph.csv")
                             : o.record;
        SolveOpts so;
        so.fixed = o.fixed;
        so.iters = o.iters;
        so.tol = o.tol;
        so.maxit = o.maxit;
        const Rows R = G.rows();
        const bool labelling = o.rhs == o.K;
        int rc = 0;

        // y = A v for the SpMV check (not timed).
        if (!o.spmv_dump.empty()) {
            Vec v(n), y(n);
            for (long i = 0; i < G.n_own; ++i) v.p[i] = 1.0 + double(G.orig[i] % 1000) / 1000.0;
            Timers scratch;
            A.apply(v.p, y.p, scratch);
            FILE* f = wrank == 0 ? fopen(o.spmv_dump.c_str(), "wb") : nullptr;
            int fok = wrank == 0 ? (f != nullptr) : 1;
            MPI_Bcast(&fok, 1, MPI_INT, 0, MPI_COMM_WORLD);
            if (!fok || !gather_append(G, y.p, f)) rc = 4;
            if (f) fclose(f);
        }

        std::vector<double> best(G.n_own), sol;
        std::vector<int32_t> pred(G.n_own);
        for (int rep = 1; rep <= o.repeats; ++rep) {
            Timers t;
            double t_solves = 0;  // this rank's wall time over the R solves
            long it_sum = 0, it_min = std::numeric_limits<long>::max(), it_max = 0, allred = 0, exch = 0;
            double relres = 0, truerel = 0;
            bool all_conv = true, any_break = false;
            std::fill(best.begin(), best.end(), 0.0);
            std::fill(pred.begin(), pred.end(), -1);
            FILE* df = nullptr;
            int dok = 1;
            if (rep == 1 && !o.dump.empty()) {
                df = wrank == 0 ? fopen(o.dump.c_str(), "wb") : nullptr;
                dok = wrank == 0 ? (df != nullptr) : 1;
                MPI_Bcast(&dok, 1, MPI_INT, 0, MPI_COMM_WORLD);
            }
            for (int c = 0; c < o.rhs; ++c) {
                vzero(b.p, b.n);
                for (int i = 0; i < o.s; ++i) {
                    const int64_t gv = seeds[size_t(c) * o.s + i];
                    if (gv >= G.row0 && gv < G.row1) b.p[gv - G.row0] = 1.0;
                }
                SolveStats st = o.cg == CgVariant::classic ? cg_classic_t(G.comm, R, A, so, b.p, W, t)
                                                            : cg_pipelined_t(G.comm, R, A, so, b.p, W, t);
                t_solves += st.t_total;
                it_sum += st.iters;
                it_min = std::min(it_min, st.iters);
                it_max = std::max(it_max, st.iters);
                allred += st.allreduces;
                exch += st.exchanges;
                all_conv = all_conv && st.converged;
                any_break = any_break || st.breakdown;
                // true residual (not timed)
                double* y = o.cg == CgVariant::classic ? W.q.p : W.nv.p;
                double* rt = o.cg == CgVariant::classic ? W.p.p : W.s.p;
                Timers scratch;
                A.apply(W.x.p, y, scratch);
                double rr_loc = residual(R, b.p, y, rt), rr = 0;
                MPI_Allreduce(&rr_loc, &rr, 1, MPI_DOUBLE, MPI_SUM, MPI_COMM_WORLD);
                const double bn = st.bnorm > 0 ? st.bnorm : 1.0;
                relres = std::max(relres, st.rnorm / bn);
                truerel = std::max(truerel, std::sqrt(rr) / bn);
                for (long i = 0; i < G.n_own; ++i)
                    if (W.x.p[i] > best[i]) {
                        best[i] = W.x.p[i];
                        pred[i] = c;
                    }
                if (rep == 1 && !o.dump.empty() && dok)  // collective
                    if (!gather_append(G, W.x.p, df)) dok = 0;
            }
            if (df) fclose(df);
            if (!dok) rc = 4;
            double accuracy = -1, unreached_frac = -1;
            if (labelling) {
                long loc[3] = {0, 0, 0}, sum[3] = {0, 0, 0};  // evaluated, correct, unreached
                for (long i = 0; i < G.n_own; ++i)
                    if (truth[i] >= 0) {
                        loc[0]++;
                        if (pred[i] < 0) loc[2]++;
                        else if (pred[i] == truth[i]) loc[1]++;
                    }
                MPI_Allreduce(loc, sum, 3, MPI_LONG, MPI_SUM, MPI_COMM_WORLD);
                accuracy = sum[0] ? double(sum[1]) / double(sum[0]) : 0;
                unreached_frac = sum[0] ? double(sum[2]) / double(sum[0]) : 0;
            }
            double loc[4] = {t.halo, t.reduce, t.compute, t_solves}, sum[4], mx[4];
            MPI_Allreduce(loc, sum, 4, MPI_DOUBLE, MPI_SUM, MPI_COMM_WORLD);
            MPI_Allreduce(loc, mx, 4, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
            const double P = double(G.size);
            const double th = sum[0] / P, tr = sum[1] / P, tc = sum[2] / P, ttot = mx[3];
            if (wrank == 0) {
                const std::vector<std::string> v = {
                    kGraphSchema, utc_now(), cluster, host, job, o.cell, o.tag, std::to_string(nodes),
                    std::to_string(G.size), std::to_string(threads), o.dataset, o.order, fmt(o.keep),
                    std::to_string(G.V), std::to_string(G.E_kept), std::to_string(2 * G.E_kept + G.V), fmt(avg_deg),
                    std::to_string(long(dmax)), part_name(o.part), ex_name(o.ex),
                    o.cg == CgVariant::classic ? "classic" : "pipelined", fmt(o.a), std::to_string(o.K),
                    std::to_string(o.s), fmt(o.theta), std::to_string(o.seed), std::to_string(o.rhs),
                    o.fixed ? "fixed" : "tol", std::to_string(o.fixed ? o.iters : o.maxit), o.fixed ? "na" : fmt(o.tol),
                    std::to_string(it_sum), std::to_string(it_min), std::to_string(it_max), std::to_string(rep),
                    fmt(ttot), fmt(ttot / o.rhs), fmt(it_sum ? ttot / double(it_sum) : 0.0), fmt(th), fmt(tr), fmt(tc),
                    fmt(ttot - th - tr - tc), fmt(mx[0]), fmt(mx[1]), fmt(mx[2]), fmt(t_setup_max), fmt(t_read_max),
                    std::to_string(rows_max), std::to_string(rows_min), std::to_string(nnz_max), std::to_string(nnz_min),
                    fmt(imbalance), std::to_string(gh_max), std::to_string(gh_sum), std::to_string(edge_cut),
                    fmt(G.E_kept ? double(edge_cut) / double(G.E_kept) : 0.0), std::to_string(nbrs_max),
                    std::to_string(dbl_max), std::to_string(allred), std::to_string(exch), fmt(relres), fmt(truerel),
                    o.fixed ? "na" : (all_conv ? "1" : "0"), any_break ? "1" : "0", fmt(accuracy),
                    std::to_string(n_eval), fmt(unreached_frac), fmt(majority), fmt(1.0 / o.K), seeds_sha, comms, sha,
                    P3_GIT_SHA, build_string(), thread_level(provided)};
                if (v.size() != graph_columns().size()) {
                    fprintf(stderr, "p3graph: internal error: %zu values for %zu columns\n", v.size(),
                            graph_columns().size());
                    rc = 5;
                } else if (!o.no_record) {
                    std::string e2;
                    if (!append_csv_row(rec_path, graph_columns(), v, e2)) {
                        fprintf(stderr, "p3graph: record not written: %s\n", e2.c_str());
                        rc = 4;
                    }
                }
                if (!o.quiet) {
                    printf("RUN cluster=%s job=%s cell=%s dataset=%s order=%s keep=%g V=%lld E=%lld ranks=%d threads=%d "
                           "part=%s exchange=%s cg=%s a=%g K=%d s=%d iters=%ld [%ld..%ld] rep=%d t_total=%.4e "
                           "t_iter=%.4e t_halo=%.4e t_reduce=%.4e t_compute=%.4e true_rel_res=%.2e edge_cut=%ld "
                           "ghosts_max=%ld imbalance=%.3f accuracy=%.4f unreached=%.4f majority=%.4f random=%.4f%s%s\n",
                           cluster.c_str(), job.c_str(), o.cell.c_str(), o.dataset.c_str(), o.order.c_str(), o.keep,
                           (long long)G.V, (long long)G.E_kept, G.size, threads, part_name(o.part), ex_name(o.ex),
                           v[20].c_str(), o.a, o.K, o.s, it_sum, it_min, it_max, rep, ttot,
                           it_sum ? ttot / double(it_sum) : 0.0, th, tr, tc, truerel, edge_cut, gh_max, imbalance,
                           accuracy, unreached_frac, majority, 1.0 / o.K, (!o.fixed && !all_conv) ? " NOT_CONVERGED" : "",
                           any_break ? " BREAKDOWN" : "");
                    fflush(stdout);
                }
            }
        }
        return rc;
    };
    const int rc = run();
    MPI_Finalize();
    return rc;
}
