#include "cg.hpp"

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

namespace {
double allreduce_sum(double v, MPI_Comm c, Timers& t, SolveStats& st) {
    double out = 0.0;
    const double t0 = MPI_Wtime();
    MPI_Allreduce(&v, &out, 1, MPI_DOUBLE, MPI_SUM, c);
    t.reduce += MPI_Wtime() - t0;
    ++st.allreduces;
    return out;
}
bool finite_pos(double v) { return std::isfinite(v) && v > 0.0; }
}  // namespace

SolveStats cg_classic(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t) {
    SolveStats st;
    const Rows R = interior_rows(G);
    double *x = W.x.p, *r = W.r.p, *p = W.p.p, *q = W.q.p;
    const long maxit = o.fixed ? o.iters : o.maxit;

    MPI_Barrier(G.cart);
    const double t_start = MPI_Wtime();
    double c0 = MPI_Wtime();
    vzero(x, W.x.n);  // x0 = 0, so r0 = b and p0 = r0
    vcopy(R, b, r);
    vcopy(R, r, p);
    const double rr0_loc = vdot(R, r, r);
    t.compute += MPI_Wtime() - c0;
    double rr = allreduce_sum(rr0_loc, G.cart, t, st);
    st.bnorm = std::sqrt(rr);

    for (long it = 0; it < maxit; ++it) {
        const double pq_loc = A.apply(p, q, t);
        ++st.exchanges;
        const double pq = allreduce_sum(pq_loc, G.cart, t, st);
        if (!finite_pos(pq)) {
            st.breakdown = true;
            break;
        }
        const double alpha = rr / pq;
        c0 = MPI_Wtime();
        const double rrn_loc = cg_update_xr(R, x, r, p, q, alpha);
        t.compute += MPI_Wtime() - c0;
        const double rrn = allreduce_sum(rrn_loc, G.cart, t, st);
        ++st.iters;
        if (!o.fixed && std::sqrt(rrn) <= o.tol * st.bnorm) {
            rr = rrn;
            st.converged = true;
            break;
        }
        if (!finite_pos(rrn)) {
            rr = rrn;
            st.breakdown = true;
            break;
        }
        const double beta = rrn / rr;
        rr = rrn;
        c0 = MPI_Wtime();
        cg_update_p(R, p, r, beta);
        t.compute += MPI_Wtime() - c0;
    }
    st.t_total = MPI_Wtime() - t_start;
    st.rnorm = std::sqrt(std::max(rr, 0.0));
    return st;
}

SolveStats cg_pipelined(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t) {
    SolveStats st;
    const Rows R = interior_rows(G);
    double *x = W.x.p, *r = W.r.p, *p = W.p.p, *w = W.w.p, *s = W.s.p, *z = W.z.p, *nv = W.nv.p;
    const long maxit = o.fixed ? o.iters : o.maxit;

    MPI_Barrier(G.cart);
    const double t_start = MPI_Wtime();
    double c0 = MPI_Wtime();
    vzero(x, W.x.n);
    vzero(p, W.p.n);
    vzero(s, W.s.n);
    vzero(z, W.z.n);
    vcopy(R, b, r);  // r0 = b - A*0
    t.compute += MPI_Wtime() - c0;
    A.apply(r, w, t);  // w0 = A r0
    ++st.exchanges;
    c0 = MPI_Wtime();
    double gamma_loc = vdot(R, r, r), delta_loc = vdot(R, w, r);
    t.compute += MPI_Wtime() - c0;

    double gamma = 0, gamma_old = 0, alpha_old = 0;
    for (long it = 0; it < maxit; ++it) {
        double sendv[2] = {gamma_loc, delta_loc}, recv[2] = {0, 0};
        MPI_Request rq;
        double r0 = MPI_Wtime();
        MPI_Iallreduce(sendv, recv, 2, MPI_DOUBLE, MPI_SUM, G.cart, &rq);
        t.reduce += MPI_Wtime() - r0;
        ++st.allreduces;
        A.apply(w, nv, t);  // n = A w, overlapped with the reduction
        ++st.exchanges;
        r0 = MPI_Wtime();
        MPI_Wait(&rq, MPI_STATUS_IGNORE);
        t.reduce += MPI_Wtime() - r0;
        gamma = recv[0];
        const double delta = recv[1];
        if (it == 0) st.bnorm = std::sqrt(gamma);
        if (!o.fixed && std::sqrt(gamma) <= o.tol * st.bnorm) {
            st.converged = true;
            break;
        }
        double alpha, beta;
        if (it == 0) {
            beta = 0.0;
            alpha = gamma / delta;
        } else {
            beta = gamma / gamma_old;
            alpha = gamma / (delta - beta * gamma / alpha_old);
        }
        if (!finite_pos(gamma) || !std::isfinite(alpha) || alpha == 0.0) {
            st.breakdown = true;
            break;
        }
        c0 = MPI_Wtime();
        pcg_update(R, x, r, w, p, s, z, nv, alpha, beta, gamma_loc, delta_loc);
        t.compute += MPI_Wtime() - c0;
        ++st.iters;
        gamma_old = gamma;
        alpha_old = alpha;
    }
    st.t_total = MPI_Wtime() - t_start;
    // ||r|| of the final recursively updated residual (outside the timed region).
    double rr = 0.0;
    if (st.converged || st.breakdown) {
        rr = gamma;
    } else {
        MPI_Allreduce(&gamma_loc, &rr, 1, MPI_DOUBLE, MPI_SUM, G.cart);
    }
    st.rnorm = std::sqrt(std::max(rr, 0.0));
    return st;
}
