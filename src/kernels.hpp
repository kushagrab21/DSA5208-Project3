// Vectors and the local kernels: the matrix-free stencil, the CG vector updates and the manufactured problem.
// None of these functions communicate; the MPI calls are in halo.cpp and cg.cpp.
#pragma once
#include <cstddef>

#include "grid.hpp"

// A grid vector with ghost layers. In the offload build its storage is also mapped to the device
// (target enter data) for its whole lifetime and kernels use the device copy.
struct Vec {
    double* p = nullptr;
    size_t n = 0;
    Vec() = default;
    explicit Vec(size_t n_) { alloc(n_); }
    Vec(const Vec&) = delete;
    Vec& operator=(const Vec&) = delete;
    ~Vec();
    void alloc(size_t n_);  // allocates and fills with zeros (first touch by the same threads that use it)
    void to_host();         // offload build: copy device -> host; no-op otherwise
};

// A plain buffer mapped the same way (halo send/receive buffers).
struct Buf {
    double* p = nullptr;
    size_t n = 0;
    Buf() = default;
    Buf(const Buf&) = delete;
    Buf& operator=(const Buf&) = delete;
    ~Buf();
    void alloc(size_t n_);
    void to_host();  // device -> host (after packing on the device)
    void to_dev();   // host -> device (before unpacking on the device)
};

// A box of local points [lo, hi) per direction, in ghosted index coordinates.
struct Box {
    long lo[3], hi[3];
    bool empty() const { return lo[0] >= hi[0] || lo[1] >= hi[1] || lo[2] >= hi[2]; }
};

// The interior of a ghosted vector as a set of contiguous rows: row (a, b) starts at base + a*T0 + b*T1 and has RL
// points. 3D: rows are (i, j) lines along k. 2D: rows are i-lines along j (R1 = 1).
struct Rows {
    long R0, R1, T0, T1, base, RL;
};
Rows interior_rows(const Grid& G);
Box full_box(const Grid& G);

// y = A x on the points of box B (A = h^2 times the 5- or 7-point negative Laplacian: 2d x_c - sum of neighbours).
// Returns the local partial sum of x.y over B.
double stencil_box(const Grid& G, const double* x, double* y, const Box& B);

void vzero(double* x, size_t n);                                    // all points, ghosts included
void vcopy(const Rows& R, const double* src, double* dst);          // interior only
double vdot(const Rows& R, const double* a, const double* b);
// Classic CG: x += alpha p, r -= alpha q; returns r.r (local).
double cg_update_xr(const Rows& R, double* x, double* r, const double* p, const double* q, double alpha);
// Classic CG: p = r + beta p.
void cg_update_p(const Rows& R, double* p, const double* r, double beta);
// Pipelined CG (Ghysels & Vanroose 2014, Alg. 4 with no preconditioner), all updates fused into one pass:
//   z = nv + beta z; s = w + beta s; p = r + beta p; x += alpha p; r -= alpha s; w -= alpha z
// and returns the local parts of gamma = r.r and delta = w.r for the next iteration.
void pcg_update(const Rows& R, double* x, double* r, double* w, double* p, double* s, double* z, const double* nv,
                double alpha, double beta, double& gamma, double& delta);
// r = b - y (interior), returns r.r: used once at the end for the true residual.
double residual(const Rows& R, const double* b, const double* y, double* r);

// Manufactured problem -Laplace(u) = f, u = 0 on the boundary.
//   expoly: u = prod_a g(x_a), g(t) = t(1-t)e^t,  f = sum_a t_a(t_a+3)e^{t_a} prod_{b != a} g(x_b)
//   sine:   u = prod_a sin(pi x_a),               f = d pi^2 u
// "sine" is an eigenvector of the discrete operator, so CG solves it in one iteration; it is kept only to show that.
enum class Problem { expoly, sine };
void set_rhs(const Grid& G, Problem pb, double* b);  // b = h^2 f at the interior points
// Local max |x - u| and local sum (x - u)^2 over interior points.
void error_parts(const Grid& G, Problem pb, const double* x, double& emax, double& esq);
