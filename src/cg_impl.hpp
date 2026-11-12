// The two CG solvers as templates over the operator, so the stencil (Operator, cg.cpp) and the graph Laplacian
// (CsrOperator, src/graph/) run the SAME solver code. Op needs one member:
//     double apply(double* x, double* y, Timers& t)   // y = A x on the owned entries; returns the local x.y
// R describes the owned entries of every vector (the vector kernels touch nothing else), comm is the communicator
// of the reductions. The functions were moved here unchanged from cg.cpp (Grid G -> comm = G.cart,
// R = interior_rows(G)); for the stencil they perform the same operations in the same order as before.
#pragma once
#include <mpi.h>

#include <algorithm>
#include <cmath>

#include "cg.hpp"

namespace cg_detail {
inline double allreduce_sum(double v, MPI_Comm c, Timers& t, SolveStats& st) {
    double out = 0.0;
    const double t0 = MPI_Wtime();
    MPI_Allreduce(&v, &out, 1, MPI_DOUBLE, MPI_SUM, c);
    t.reduce += MPI_Wtime() - t0;
    ++st.allreduces;
    return out;
}
inline bool finite_pos(double v) { return std::isfinite(v) && v > 0.0; }
}  // namespace cg_detail

template <class Op>
SolveStats cg_classic_t(MPI_Comm comm, const Rows& R, Op& A, const SolveOpts& o, const double* b, Work& W,
                        Timers& t) {
    using namespace cg_detail;
    SolveStats st;
    double *x = W.x.p, *r = W.r.p, *p = W.p.p, *q = W.q.p;
    const long maxit = o.fixed ? o.iters : o.maxit;

    MPI_Barrier(comm);
    const double t_start = MPI_Wtime();
    double c0 = MPI_Wtime();
    vzero(x, W.x.n);  // x0 = 0, so r0 = b and p0 = r0
    vcopy(R, b, r);
    vcopy(R, r, p);
    const double rr0_loc = vdot(R, r, r);
    t.compute += MPI_Wtime() - c0;
    double rr = allreduce_sum(rr0_loc, comm, t, st);
    st.bnorm = std::sqrt(rr);

    for (long it = 0; it < maxit; ++it) {
        const double pq_loc = A.apply(p, q, t);
        ++st.exchanges;
        const double pq = allreduce_sum(pq_loc, comm, t, st);
        if (!finite_pos(pq)) {
            st.breakdown = true;
            break;
        }
        const double alpha = rr / pq;
        c0 = MPI_Wtime();
        const double rrn_loc = cg_update_xr(R, x, r, p, q, alpha);
        t.compute += MPI_Wtime() - c0;
        const double rrn = allreduce_sum(rrn_loc, comm, t, st);
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

template <class Op>
SolveStats cg_pipelined_t(MPI_Comm comm, const Rows& R, Op& A, const SolveOpts& o, const double* b, Work& W,
                          Timers& t) {
    using namespace cg_detail;
    SolveStats st;
    double *x = W.x.p, *r = W.r.p, *p = W.p.p, *w = W.w.p, *s = W.s.p, *z = W.z.p, *nv = W.nv.p;
    const long maxit = o.fixed ? o.iters : o.maxit;

    MPI_Barrier(comm);
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
        MPI_Iallreduce(sendv, recv, 2, MPI_DOUBLE, MPI_SUM, comm, &rq);
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
        MPI_Allreduce(&gamma_loc, &rr, 1, MPI_DOUBLE, MPI_SUM, comm);
    }
    st.rnorm = std::sqrt(std::max(rr, 0.0));
    return st;
}
