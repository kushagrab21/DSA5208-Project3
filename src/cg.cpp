#include "cg.hpp"
#include "cg_impl.hpp"

#include <mpi.h>

#include <algorithm>
#include <cmath>

Operator::Operator(const Grid& g, Halo& h, HaloMode m) : G(g), H(h), mode(m) {
    full = full_box(G);
    // In each direction the full range [lo, hi) splits into [lo, ilo) U [ilo, ihi) U [ihi, hi): the first and
    // last planes are held back only on a side that faces another rank (their stencil reads a ghost value that
    // arrives by message). A side facing the physical boundary reads zeros that are always valid.
    long ilo[3], ihi[3];
    for (int a = 0; a < 3; ++a) {
        const bool lo_n = (a < G.dim) && G.nbr[a][0] != MPI_PROC_NULL;
        const bool hi_n = (a < G.dim) && G.nbr[a][1] != MPI_PROC_NULL;
        ilo[a] = full.lo[a] + (lo_n ? 1 : 0);
        ihi[a] = std::max(ilo[a], full.hi[a] - (hi_n ? 1 : 0));
        inner.lo[a] = ilo[a];
        inner.hi[a] = ihi[a];
    }
    // Shell = full minus interior, as disjoint slabs: slab for direction a uses the interior range in directions
    // before a and the full range in directions after a.
    for (int a = 0; a < G.dim; ++a) {
        for (int side = 0; side < 2; ++side) {
            Box B;
            for (int b = 0; b < 3; ++b) {
                if (b < a) {
                    B.lo[b] = ilo[b];
                    B.hi[b] = ihi[b];
                } else {
                    B.lo[b] = full.lo[b];
                    B.hi[b] = full.hi[b];
                }
            }
            if (side == 0) {
                B.lo[a] = full.lo[a];
                B.hi[a] = ilo[a];
            } else {
                B.lo[a] = ihi[a];
                B.hi[a] = full.hi[a];
            }
            if (!B.empty()) shellv.push_back(B);
        }
    }
}

double Operator::apply(double* x, double* y, Timers& t) {
    double d = 0.0;
    const double t0 = MPI_Wtime();
    if (mode == HaloMode::blocking) {
        H.exchange_blocking(x);
        const double t1 = MPI_Wtime();
        d = stencil_box(G, x, y, full);
        t.halo += t1 - t0;
        t.compute += MPI_Wtime() - t1;
    } else {
        H.start(x);
        const double t1 = MPI_Wtime();
        d = stencil_box(G, x, y, inner);
        const double t2 = MPI_Wtime();
        H.finish(x);
        const double t3 = MPI_Wtime();
        for (const Box& B : shellv) d += stencil_box(G, x, y, B);
        const double t4 = MPI_Wtime();
        t.halo += (t1 - t0) + (t3 - t2);
        t.compute += (t2 - t1) + (t4 - t3);
    }
    return d;
}

SolveStats cg_classic(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t) {
    return cg_classic_t(G.cart, interior_rows(G), A, o, b, W, t);
}

SolveStats cg_pipelined(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t) {
    return cg_pipelined_t(G.cart, interior_rows(G), A, o, b, W, t);
}
