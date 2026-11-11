// p3cg: matrix-free conjugate gradient for -Laplace(u) = f on the unit square/cube, MPI + OpenMP.
// Usage: p3cg --help
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
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "cg.hpp"
#include "grid.hpp"
#include "halo.hpp"
#include "kernels.hpp"
#include "par.hpp"
#include "record.hpp"

#ifndef P3_GIT_SHA
#define P3_GIT_SHA "unknown"
#endif

namespace {

const char* kUsage =
    "p3cg --dim 2|3 --n N [options]\n"
    "  --decomp D           directions split across ranks, 1..dim (default dim)\n"
    "  --cg classic|pipelined         (default classic)\n"
    "  --halo blocking|overlap        (default blocking)\n"
    "  --iters K            fixed K iterations (timing runs)\n"
    "  --tol T              stop at ||r|| <= T ||b|| (default 1e-8 when --iters is absent)\n"
    "  --maxit M            iteration cap in tolerance mode (default 100000)\n"
    "  --repeats R          solve R times in this process, one record row each (default 1)\n"
    "  --problem expoly|sine (default expoly)\n"
    "  --record PATH        CSV to append to (default results/<cluster>/<job>.csv)\n"
    "  --no-record          do not write a record row\n"
    "  --cell ID            plan cell id written to the record (default -)\n"
    "  --tag TAG            free label written to the record (default -)\n"
    "  --dump PATH          write the final solution (interior points, global C order, float64) for checks\n"
    "  --quiet              no RUN line on stdout\n"
    "  --version            print sha256 of this binary and the build options, then exit\n";

struct Options {
    int dim = 0;
    long n = 0;
    int decomp = -1;
    CgVariant cg = CgVariant::classic;
    HaloMode halo = HaloMode::blocking;
    bool fixed = false;
    long iters = 0;
    double tol = 1e-8;
    long maxit = 100000;
    int repeats = 1;
    Problem problem = Problem::expoly;
    std::string record, cell = "-", tag = "-", dump;
    bool no_record = false, quiet = false, version = false, help = false;
};

bool parse(int argc, char** argv, Options& o, std::string& err) {
    bool tol_given = false;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto val = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                err = std::string("missing value for ") + name;
                return "";
            }
            return argv[++i];
        };
        try {
            if (a == "--dim") o.dim = std::stoi(val("--dim"));
            else if (a == "--n") o.n = std::stol(val("--n"));
            else if (a == "--decomp") o.decomp = std::stoi(val("--decomp"));
            else if (a == "--cg") {
                std::string v = val("--cg");
                if (v == "classic") o.cg = CgVariant::classic;
                else if (v == "pipelined") o.cg = CgVariant::pipelined;
                else err = "--cg must be classic or pipelined";
            } else if (a == "--halo") {
                std::string v = val("--halo");
                if (v == "blocking") o.halo = HaloMode::blocking;
                else if (v == "overlap") o.halo = HaloMode::overlap;
                else err = "--halo must be blocking or overlap";
            } else if (a == "--iters") {
                o.iters = std::stol(val("--iters"));
                o.fixed = true;
            } else if (a == "--tol") {
                o.tol = std::stod(val("--tol"));
                tol_given = true;
            } else if (a == "--maxit") o.maxit = std::stol(val("--maxit"));
            else if (a == "--repeats") o.repeats = std::stoi(val("--repeats"));
            else if (a == "--problem") {
                std::string v = val("--problem");
                if (v == "expoly") o.problem = Problem::expoly;
                else if (v == "sine") o.problem = Problem::sine;
                else err = "--problem must be expoly or sine";
            } else if (a == "--record") o.record = val("--record");
            else if (a == "--no-record") o.no_record = true;
            else if (a == "--cell") o.cell = val("--cell");
            else if (a == "--tag") o.tag = val("--tag");
            else if (a == "--dump") o.dump = val("--dump");
            else if (a == "--quiet") o.quiet = true;
            else if (a == "--version") o.version = true;
            else if (a == "--help" || a == "-h") o.help = true;
            else err = "unknown option " + a;
        } catch (...) {
            err = "bad value for " + a;
        }
        if (!err.empty()) return false;
    }
    if (o.version || o.help) return true;
    if (o.dim != 2 && o.dim != 3) err = "--dim must be 2 or 3";
    else if (o.n < 1) err = "--n must be >= 1";
    else if (o.fixed && tol_given) err = "--iters (fixed) and --tol (tolerance) are exclusive";
    else if (o.fixed && o.iters < 1) err = "--iters must be >= 1";
    else if (o.repeats < 1) err = "--repeats must be >= 1";
    if (o.decomp < 0) o.decomp = o.dim;
    if (err.empty() && (o.decomp < 1 || o.decomp > o.dim)) err = "--decomp must be in 1..dim";
    return err.empty();
}

std::string build_string() {
    std::ostringstream s;
#if defined(_OPENMP)
    s << "omp=" << _OPENMP;
#else
    s << "omp=0";
#endif
#if defined(P3_OFFLOAD)
    s << ";offload=1";
#else
    s << ";offload=0";
#endif
    s << ";bug=" << PLANT_HALO_BUG;
#if defined(__VERSION__)
    s << ";cxx=" << __VERSION__;
#endif
    char lib[MPI_MAX_LIBRARY_VERSION_STRING];
    int len = 0;
    MPI_Get_library_version(lib, &len);
    std::string l(lib, len);
    size_t nl = l.find_first_of(",\n\r");  // "Open MPI v5.0.11, package: ..." -> "Open MPI v5.0.11"
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

std::string thread_level(int provided) {
    switch (provided) {
        case MPI_THREAD_SINGLE: return "single";
        case MPI_THREAD_FUNNELED: return "funneled";
        case MPI_THREAD_SERIALIZED: return "serialized";
        case MPI_THREAD_MULTIPLE: return "multiple";
    }
    return "unknown";
}

// Gathers the interior of x to rank 0 in global C order (k fastest) and writes it as raw float64.
bool dump_solution(const Grid& G, Vec& x, const std::string& path) {
    x.to_host();
    const long nloc = G.local_points();
    std::vector<double> mine(static_cast<size_t>(nloc));
    long m = 0;
    for (long i = 1; i <= G.nl[0]; ++i)
        for (long j = 1; j <= G.nl[1]; ++j)
            for (long k = G.g[2]; k < G.g[2] + G.nl[2]; ++k) mine[size_t(m++)] = x.p[G.idx(i, j, k)];
    long meta[6] = {G.off[0], G.off[1], G.off[2], G.nl[0], G.nl[1], G.nl[2]};
    std::vector<long> all(size_t(6 * G.size));
    MPI_Gather(meta, 6, MPI_LONG, all.data(), 6, MPI_LONG, 0, G.cart);
    std::vector<int> counts(size_t(G.size)), displs(size_t(G.size));
    int cnt = int(nloc);
    MPI_Gather(&cnt, 1, MPI_INT, counts.data(), 1, MPI_INT, 0, G.cart);
    std::vector<double> recv;
    if (G.rank == 0) {
        long tot = 0;
        for (int r = 0; r < G.size; ++r) {
            displs[size_t(r)] = int(tot);
            tot += counts[size_t(r)];
        }
        recv.resize(size_t(tot));
    }
    MPI_Gatherv(mine.data(), cnt, MPI_DOUBLE, recv.data(), counts.data(), displs.data(), MPI_DOUBLE, 0, G.cart);
    if (G.rank != 0) return true;
    const long n = G.n, n2 = (G.dim == 3) ? n : 1;
    std::vector<double> glob(size_t(n * n * n2), 0.0);
    for (int r = 0; r < G.size; ++r) {
        const long* md = &all[size_t(6 * r)];
        long q = displs[size_t(r)];
        for (long i = 0; i < md[3]; ++i)
            for (long j = 0; j < md[4]; ++j)
                for (long k = 0; k < md[5]; ++k)
                    glob[size_t(((md[0] + i) * n + (md[1] + j)) * n2 + (md[2] + k))] = recv[size_t(q++)];
    }
    std::ofstream f(path, std::ios::binary);
    f.write(reinterpret_cast<const char*>(glob.data()), std::streamsize(glob.size() * sizeof(double)));
    return bool(f);
}

}  // namespace

int main(int argc, char** argv) {
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    int wrank = 0, wsize = 1;
    MPI_Comm_rank(MPI_COMM_WORLD, &wrank);
    MPI_Comm_size(MPI_COMM_WORLD, &wsize);

    Options o;
    std::string err;
    if (!parse(argc, argv, o, err)) {
        if (wrank == 0) fprintf(stderr, "p3cg: %s\n%s", err.c_str(), kUsage);
        MPI_Finalize();
        return 2;
    }
    const std::string exe = self_exe_path();
    const std::string sha = (wrank == 0) ? sha256_file(exe) : "";
    if (o.help || o.version) {
        if (wrank == 0) {
            if (o.help) printf("%s", kUsage);
            else printf("p3cg sha256=%s git=%s path=%s build=%s\n", sha.c_str(), P3_GIT_SHA, exe.c_str(),
                        build_string().c_str());  // build last: it may contain spaces
        }
        MPI_Finalize();
        return 0;
    }
    if (provided < MPI_THREAD_FUNNELED) {
        if (wrank == 0) fprintf(stderr, "p3cg: MPI provides %s, FUNNELED needed\n", thread_level(provided).c_str());
        MPI_Finalize();
        return 3;
    }

    // Node count and node-local rank (for GPU selection).
    MPI_Comm node;
    MPI_Comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED, wrank, MPI_INFO_NULL, &node);
    int lrank = 0;
    MPI_Comm_rank(node, &lrank);
    int is_leader = (lrank == 0) ? 1 : 0, nodes = 0;
    MPI_Allreduce(&is_leader, &nodes, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);
    MPI_Comm_free(&node);

    int threads = 1;
#if defined(_OPENMP)
    threads = omp_get_max_threads();
#endif
    int gpu_here = 0;
#if defined(P3_OFFLOAD)
    {
        const int ndev = omp_get_num_devices();
        if (ndev > 0) omp_set_default_device(lrank % ndev);
        int on_dev = 0;
#pragma omp target map(from : on_dev)
        { on_dev = omp_is_initial_device() ? 0 : 1; }
        gpu_here = (on_dev && lrank < ndev) ? 1 : 0;
        if (!on_dev && wrank == 0) fprintf(stderr, "p3cg: WARNING offload build is running on the host\n");
    }
#endif
    int gpus = 0;
    MPI_Allreduce(&gpu_here, &gpus, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);

    char hostc[MPI_MAX_PROCESSOR_NAME];
    int hl = 0;
    MPI_Get_processor_name(hostc, &hl);
    const std::string host(hostc, hl);
    std::string cl_warn;
    const std::string cluster = detect_cluster(host, cl_warn);
    const std::string job = pbs_jobid();
    if (wrank == 0 && !cl_warn.empty()) fprintf(stderr, "p3cg: %s\n", cl_warn.c_str());

    const double ts0 = MPI_Wtime();
    Grid G;
    if (!make_grid(G, o.dim, o.n, o.decomp, MPI_COMM_WORLD, err)) {
        if (wrank == 0) fprintf(stderr, "p3cg: %s\n", err.c_str());
        MPI_Finalize();
        return 2;
    }
    Vec b(G.ntot);
    Work W;
    W.x.alloc(G.ntot);
    W.r.alloc(G.ntot);
    W.p.alloc(G.ntot);
    if (o.cg == CgVariant::classic) {
        W.q.alloc(G.ntot);
    } else {
        W.w.alloc(G.ntot);
        W.s.alloc(G.ntot);
        W.z.alloc(G.ntot);
        W.nv.alloc(G.ntot);
    }
    set_rhs(G, o.problem, b.p);
    Halo H(G);
    Operator A(G, H, o.halo);
    MPI_Barrier(G.cart);
    double t_setup = MPI_Wtime() - ts0, t_setup_max = 0;
    MPI_Allreduce(&t_setup, &t_setup_max, 1, MPI_DOUBLE, MPI_MAX, G.cart);

    long lp = G.local_points(), lmax = 0, lmin = 0;
    MPI_Allreduce(&lp, &lmax, 1, MPI_LONG, MPI_MAX, G.cart);
    MPI_Allreduce(&lp, &lmin, 1, MPI_LONG, MPI_MIN, G.cart);
    long msgs = H.messages_per_exchange(), msgs_max = 0, dbl = H.doubles_per_exchange(), dbl_max = 0;
    MPI_Allreduce(&msgs, &msgs_max, 1, MPI_LONG, MPI_MAX, G.cart);
    MPI_Allreduce(&dbl, &dbl_max, 1, MPI_LONG, MPI_MAX, G.cart);

    std::string pd = std::to_string(G.pdims[0]) + "x" + std::to_string(G.pdims[1]);
    if (o.dim == 3) pd += "x" + std::to_string(G.pdims[2]);
    const std::string rec_path =
        o.record.empty() ? ("results/" + cluster + "/" + (job == "none" ? std::string("local") : job) + ".csv")
                         : o.record;

    SolveOpts so;
    so.fixed = o.fixed;
    so.iters = o.iters;
    so.tol = o.tol;
    so.maxit = o.maxit;
    const Rows R = interior_rows(G);
    int rc = 0;

    for (int rep = 1; rep <= o.repeats; ++rep) {
        Timers t;
        SolveStats st = (o.cg == CgVariant::classic) ? cg_classic(G, A, so, b.p, W, t)
                                                     : cg_pipelined(G, A, so, b.p, W, t);
        // Per-rank times -> mean and max over ranks; t_total is the slowest rank's wall time.
        double loc[4] = {t.halo, t.reduce, t.compute, st.t_total}, sum[4], mx[4];
        MPI_Allreduce(loc, sum, 4, MPI_DOUBLE, MPI_SUM, G.cart);
        MPI_Allreduce(loc, mx, 4, MPI_DOUBLE, MPI_MAX, G.cart);
        const double P = double(G.size);
        const double th = sum[0] / P, tr = sum[1] / P, tc = sum[2] / P, ttot = mx[3];

        // True residual ||b - A x|| / ||b|| and error against the exact solution (not timed).
        double* y = (o.cg == CgVariant::classic) ? W.q.p : W.nv.p;
        double* rt = (o.cg == CgVariant::classic) ? W.p.p : W.s.p;
        Timers scratch;
        A.apply(W.x.p, y, scratch);
        double rr_loc = residual(R, b.p, y, rt), rr = 0;
        MPI_Allreduce(&rr_loc, &rr, 1, MPI_DOUBLE, MPI_SUM, G.cart);
        double em_loc = 0, es_loc = 0, em = 0, es = 0;
        error_parts(G, o.problem, W.x.p, em_loc, es_loc);
        MPI_Allreduce(&em_loc, &em, 1, MPI_DOUBLE, MPI_MAX, G.cart);
        MPI_Allreduce(&es_loc, &es, 1, MPI_DOUBLE, MPI_SUM, G.cart);
        const double hd = std::pow(G.h, double(o.dim));
        const double el2 = std::sqrt(hd * es);
        const double bn = st.bnorm > 0 ? st.bnorm : 1.0;

        if (G.rank == 0) {
            std::vector<std::string> v = {
                kRecordSchema, utc_now(), cluster, host, job, o.cell, o.tag,
                std::to_string(nodes), std::to_string(G.size), std::to_string(threads), std::to_string(gpus),
                std::to_string(o.dim), std::to_string(o.n), std::to_string(unknowns(o.dim, o.n)),
                std::to_string(nonzeros(o.dim, o.n)), std::to_string(o.decomp) + "D", pd, std::to_string(lmax),
                std::to_string(lmin), o.cg == CgVariant::classic ? "classic" : "pipelined",
                o.halo == HaloMode::blocking ? "blocking" : "overlap", o.fixed ? "fixed" : "tol",
                std::to_string(o.fixed ? o.iters : o.maxit), o.fixed ? "na" : fmt(o.tol), std::to_string(st.iters),
                std::to_string(rep), fmt(ttot), fmt(th), fmt(tr), fmt(tc), fmt(ttot - th - tr - tc), fmt(mx[0]),
                fmt(mx[1]), fmt(mx[2]), fmt(t_setup_max), std::to_string(msgs_max), std::to_string(dbl_max),
                std::to_string(st.allreduces), std::to_string(st.exchanges), fmt(st.rnorm / bn),
                fmt(std::sqrt(rr) / bn), fmt(em), fmt(el2), o.fixed ? "na" : (st.converged ? "1" : "0"),
                st.breakdown ? "1" : "0", sha, P3_GIT_SHA, build_string(), thread_level(provided),
                o.problem == Problem::expoly ? "expoly" : "sine"};
            if (!o.no_record) {
                std::string e2;
                if (!append_record(rec_path, v, e2)) {
                    fprintf(stderr, "p3cg: record not written: %s\n", e2.c_str());
                    rc = 4;
                }
            }
            if (!o.quiet) {
                printf("RUN cluster=%s job=%s cell=%s nodes=%d ranks=%d threads=%d gpus=%d dim=%d n=%ld N=%lld "
                       "decomp=%dD pdims=%s cg=%s halo=%s iters=%ld rep=%d t_total=%.4e t_halo=%.4e t_reduce=%.4e "
                       "t_compute=%.4e rel_res=%.3e true_rel_res=%.3e err_max=%.4e%s%s\n",
                       cluster.c_str(), job.c_str(), o.cell.c_str(), nodes, G.size, threads, gpus, o.dim, o.n,
                       unknowns(o.dim, o.n), o.decomp, pd.c_str(), v[19].c_str(), v[20].c_str(), st.iters, rep, ttot,
                       th, tr, tc, st.rnorm / bn, std::sqrt(rr) / bn, em,
                       (!o.fixed && !st.converged) ? " NOT_CONVERGED" : "", st.breakdown ? " BREAKDOWN" : "");
                fflush(stdout);
            }
        }
    }
    if (!o.dump.empty()) {
        if (o.n > 4096 && o.dim == 2) {
            if (G.rank == 0) fprintf(stderr, "p3cg: --dump is for small grids only\n");
        } else if (o.n > 256 && o.dim == 3) {
            if (G.rank == 0) fprintf(stderr, "p3cg: --dump is for small grids only\n");
        } else if (!dump_solution(G, W.x, o.dump)) {
            if (G.rank == 0) fprintf(stderr, "p3cg: cannot write %s\n", o.dump.c_str());
            rc = 4;
        }
    }
    MPI_Comm_free(&G.cart);
    MPI_Finalize();
    return rc;
}
