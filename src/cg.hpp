// Conjugate gradient solvers for A x = b, A the scaled 5-/7-point negative Laplacian, with time split into
// halo exchange, global reductions and local computation (MPI_Wtime on every rank).
//
//   classic:   Hestenes-Stiefel CG. Per iteration: one halo exchange + stencil (q = A p, fused with p.q), two
//              blocking MPI_Allreduce calls (p.q and r.r), two vector passes.
//   pipelined: Ghysels & Vanroose (2014) pipelined CG without preconditioner. Per iteration: ONE non-blocking
//              MPI_Iallreduce of (r.r, w.r), overlapped with the halo exchange + stencil n = A w; then one fused
//              vector pass. It needs 3 more vectors and more memory traffic per iteration, and its recursively
//              updated residual drifts further from the true residual b - A x (lower attainable accuracy).
#pragma once
#include <vector>

#include "grid.hpp"
#include "halo.hpp"
#include "kernels.hpp"

struct Timers {
    double halo = 0, reduce = 0, compute = 0;
};

// y = A x with the chosen halo variant. Overlap: interior box while messages are in flight, shell afterwards.
class Operator {
public:
    Operator(const Grid& G, Halo& H, HaloMode mode);
    double apply(double* x, double* y, Timers& t);  // returns the local part of x.y
    const Box& interior() const { return inner; }
    const std::vector<Box>& shell() const { return shellv; }

private:
    const Grid& G;
    Halo& H;
    HaloMode mode;
    Box full, inner;
    std::vector<Box> shellv;
};

enum class CgVariant { classic, pipelined };

struct SolveOpts {
    bool fixed = false;  // true: exactly `iters` iterations (timing runs); false: stop at ||r|| <= tol ||b||
    long iters = 100;
    double tol = 1e-8;
    long maxit = 100000;
};

struct SolveStats {
    long iters = 0;
    bool converged = false;
    bool breakdown = false;  // a zero or non-finite step (e.g. exact convergence inside a fixed-iteration run)
    double bnorm = 0, rnorm = 0;  // ||b|| and the recursively updated ||r|| at exit
    double t_total = 0;           // this rank's wall time for the whole solve
    long allreduces = 0, exchanges = 0;
};

// Vectors needed by either variant (allocated by the caller; unused ones may stay empty).
struct Work {
    Vec x, r, p, q;      // classic: q = A p.   pipelined uses x, r, p too
    Vec w, s, z, nv;     // pipelined only: w = A r, s = A p, z = A s, nv = A w
};

// The stencil solvers (thin wrappers over the templates in cg_impl.hpp).
SolveStats cg_classic(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t);
SolveStats cg_pipelined(const Grid& G, Operator& A, const SolveOpts& o, const double* b, Work& W, Timers& t);
