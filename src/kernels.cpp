#include "kernels.hpp"

#include <cmath>
#include <cstdlib>
#include <new>

#include "par.hpp"

// ---------------------------------------------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------------------------------------------
static double* alloc_doubles(size_t n) {
    void* q = nullptr;
    size_t bytes = ((n * sizeof(double) + 63) / 64) * 64;
    if (bytes == 0) bytes = 64;
    if (posix_memalign(&q, 64, bytes) != 0) throw std::bad_alloc();
    return static_cast<double*>(q);
}

void Vec::alloc(size_t n_) {
    n = n_;
    p = alloc_doubles(n);
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target enter data map(alloc : q[0 : m])
#endif
    vzero(p, n);
}

Vec::~Vec() {
    if (!p) return;
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target exit data map(delete : q[0 : m])
#endif
    free(p);
}

void Vec::to_host() {
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target update from(q[0 : m])
#endif
}

void Buf::alloc(size_t n_) {
    n = n_;
    p = alloc_doubles(n);
    for (size_t i = 0; i < n; ++i) p[i] = 0.0;
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target enter data map(to : q[0 : m])
#endif
}

Buf::~Buf() {
    if (!p) return;
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target exit data map(delete : q[0 : m])
#endif
    free(p);
}

void Buf::to_host() {
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target update from(q[0 : m])
#endif
}

void Buf::to_dev() {
#if defined(P3_OFFLOAD)
    double* q = p;
    size_t m = n;
#pragma omp target update to(q[0 : m])
#endif
}

// ---------------------------------------------------------------------------------------------------------------
// Index sets
// ---------------------------------------------------------------------------------------------------------------
Rows interior_rows(const Grid& G) {
    Rows R;
    if (G.dim == 3) {
        R.R0 = G.nl[0];
        R.R1 = G.nl[1];
        R.T0 = G.S0;
        R.T1 = G.S1;
        R.base = G.idx(1, 1, 1);
        R.RL = G.nl[2];
    } else {
        R.R0 = G.nl[0];
        R.R1 = 1;
        R.T0 = G.S0;
        R.T1 = 0;
        R.base = G.idx(1, 1, 0);
        R.RL = G.nl[1];
    }
    return R;
}

Box full_box(const Grid& G) {
    Box B;
    for (int a = 0; a < 3; ++a) {
        B.lo[a] = G.g[a];
        B.hi[a] = G.g[a] + G.nl[a];
    }
    return B;
}

// ---------------------------------------------------------------------------------------------------------------
// Operator
// ---------------------------------------------------------------------------------------------------------------
double stencil_box(const Grid& G, const double* P3_RESTRICT x, double* P3_RESTRICT y, const Box& B) {
    double d = 0.0;
    if (B.empty()) return d;
    const long S0 = G.S0, S1 = G.S1;
    const long i0 = B.lo[0], i1 = B.hi[0], j0 = B.lo[1], j1 = B.hi[1], k0 = B.lo[2], k1 = B.hi[2];
    if (G.dim == 3) {
        P3_FOR3(reduction(+ : d))
        for (long i = i0; i < i1; ++i)
            for (long j = j0; j < j1; ++j)
                P3_SIMD(reduction(+ : d))
                for (long k = k0; k < k1; ++k) {
                    const long c = i * S0 + j * S1 + k;
                    const double v =
                        6.0 * x[c] - (x[c - S0] + x[c + S0]) - (x[c - S1] + x[c + S1]) - (x[c - 1] + x[c + 1]);
                    y[c] = v;
                    d += x[c] * v;
                }
    } else {
        // 2D: S1 == 1 and k == 0, so the point (i, j) is at i*S0 + j.
        P3_FOR2(reduction(+ : d))
        for (long i = i0; i < i1; ++i)
            P3_SIMD(reduction(+ : d))
            for (long j = j0; j < j1; ++j) {
                const long c = i * S0 + j;
                const double v = 4.0 * x[c] - (x[c - S0] + x[c + S0]) - (x[c - 1] + x[c + 1]);
                y[c] = v;
                d += x[c] * v;
            }
    }
    return d;
}

// ---------------------------------------------------------------------------------------------------------------
// Vector operations (interior points only; ghost layers are never written here)
// ---------------------------------------------------------------------------------------------------------------
void vzero(double* x, size_t n) {
    P3_FOR1()
    for (size_t i = 0; i < n; ++i) x[i] = 0.0;
}

#define P3_ROWS_UNPACK                                                                     \
    const long R0 = R.R0, R1 = R.R1, T0 = R.T0, T1 = R.T1, base = R.base, RL = R.RL;

void vcopy(const Rows& R, const double* P3_RESTRICT src, double* P3_RESTRICT dst) {
    P3_ROWS_UNPACK
    P3_FOR3()
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD()
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                dst[q] = src[q];
            }
}

double vdot(const Rows& R, const double* x, const double* y) {
    P3_ROWS_UNPACK
    double d = 0.0;
    P3_FOR3(reduction(+ : d))
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD(reduction(+ : d))
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                d += x[q] * y[q];
            }
    return d;
}

double cg_update_xr(const Rows& R, double* P3_RESTRICT x, double* P3_RESTRICT r, const double* P3_RESTRICT p,
                    const double* P3_RESTRICT q_, double alpha) {
    P3_ROWS_UNPACK
    double d = 0.0;
    P3_FOR3(reduction(+ : d))
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD(reduction(+ : d))
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                x[q] += alpha * p[q];
                const double rn = r[q] - alpha * q_[q];
                r[q] = rn;
                d += rn * rn;
            }
    return d;
}

void cg_update_p(const Rows& R, double* P3_RESTRICT p, const double* P3_RESTRICT r, double beta) {
    P3_ROWS_UNPACK
    P3_FOR3()
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD()
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                p[q] = r[q] + beta * p[q];
            }
}

void pcg_update(const Rows& R, double* P3_RESTRICT x, double* P3_RESTRICT r, double* P3_RESTRICT w,
                double* P3_RESTRICT p, double* P3_RESTRICT s, double* P3_RESTRICT z, const double* P3_RESTRICT nv,
                double alpha, double beta, double& gamma, double& delta) {
    P3_ROWS_UNPACK
    double g = 0.0, dl = 0.0;
    P3_FOR3(reduction(+ : g, dl))
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD(reduction(+ : g, dl))
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                const double zq = nv[q] + beta * z[q];
                const double sq = w[q] + beta * s[q];
                const double pq = r[q] + beta * p[q];
                z[q] = zq;
                s[q] = sq;
                p[q] = pq;
                x[q] += alpha * pq;
                const double rq = r[q] - alpha * sq;
                const double wq = w[q] - alpha * zq;
                r[q] = rq;
                w[q] = wq;
                g += rq * rq;
                dl += wq * rq;
            }
    gamma = g;
    delta = dl;
}

double residual(const Rows& R, const double* P3_RESTRICT bv, const double* P3_RESTRICT y, double* P3_RESTRICT r) {
    P3_ROWS_UNPACK
    double d = 0.0;
    P3_FOR3(reduction(+ : d))
    for (long a = 0; a < R0; ++a)
        for (long b = 0; b < R1; ++b)
            P3_SIMD(reduction(+ : d))
            for (long c = 0; c < RL; ++c) {
                const long q = base + a * T0 + b * T1 + c;
                const double v = bv[q] - y[q];
                r[q] = v;
                d += v * v;
            }
    return d;
}

// ---------------------------------------------------------------------------------------------------------------
// Manufactured problem
// ---------------------------------------------------------------------------------------------------------------
// Point (i, j, k) has coordinates x_a = (off_a + (index_a - g_a) + 1) h. In 2D the direction-2 factor is left out.
void set_rhs(const Grid& G, Problem pb, double* bv) {
    const double h = G.h, h2 = G.h * G.h, pi = 3.14159265358979323846;
    const long o0 = G.off[0], o1 = G.off[1], o2 = G.off[2];
    const long n0 = G.nl[0], n1 = G.nl[1], n2 = G.nl[2], g2 = G.g[2], L1 = G.L[1], L2 = G.L[2];
    const int dim = G.dim;
    const int sine = (pb == Problem::sine) ? 1 : 0;
    P3_FOR3()
    for (long i = 1; i <= n0; ++i)
        for (long j = 1; j <= n1; ++j)
            for (long k = g2; k < g2 + n2; ++k) {
                const double t0 = double(o0 + i) * h;  // (off + (i - 1) + 1) h
                const double t1 = double(o1 + j) * h;
                const double t2 = double(o2 + (k - g2) + 1) * h;
                double f;
                if (sine) {
                    double u = std::sin(pi * t0) * std::sin(pi * t1);
                    if (dim == 3) u *= std::sin(pi * t2);
                    f = double(dim) * pi * pi * u;
                } else {
                    const double e0 = std::exp(t0), e1 = std::exp(t1);
                    const double g0 = t0 * (1.0 - t0) * e0, g1 = t1 * (1.0 - t1) * e1;
                    const double m0 = t0 * (t0 + 3.0) * e0, m1 = t1 * (t1 + 3.0) * e1;  // -g''
                    if (dim == 3) {
                        const double e2 = std::exp(t2);
                        const double gg2 = t2 * (1.0 - t2) * e2, m2 = t2 * (t2 + 3.0) * e2;
                        f = m0 * g1 * gg2 + g0 * m1 * gg2 + g0 * g1 * m2;
                    } else {
                        f = m0 * g1 + g0 * m1;
                    }
                }
                bv[(i * L1 + j) * L2 + k] = h2 * f;
            }
}

void error_parts(const Grid& G, Problem pb, const double* x, double& emax, double& esq) {
    const double h = G.h, pi = 3.14159265358979323846;
    const long o0 = G.off[0], o1 = G.off[1], o2 = G.off[2];
    const long n0 = G.nl[0], n1 = G.nl[1], n2 = G.nl[2], g2 = G.g[2], L1 = G.L[1], L2 = G.L[2];
    const int dim = G.dim;
    const int sine = (pb == Problem::sine) ? 1 : 0;
    double em = 0.0, es = 0.0;
    P3_FOR3(reduction(max : em) reduction(+ : es))
    for (long i = 1; i <= n0; ++i)
        for (long j = 1; j <= n1; ++j)
            for (long k = g2; k < g2 + n2; ++k) {
                const double t0 = double(o0 + i) * h;
                const double t1 = double(o1 + j) * h;
                const double t2 = double(o2 + (k - g2) + 1) * h;
                double u;
                if (sine) {
                    u = std::sin(pi * t0) * std::sin(pi * t1);
                    if (dim == 3) u *= std::sin(pi * t2);
                } else {
                    u = t0 * (1.0 - t0) * std::exp(t0) * t1 * (1.0 - t1) * std::exp(t1);
                    if (dim == 3) u *= t2 * (1.0 - t2) * std::exp(t2);
                }
                const double e = x[(i * L1 + j) * L2 + k] - u;
                const double ae = e < 0 ? -e : e;
                em = ae > em ? ae : em;
                es += e * e;
            }
    emax = em;
    esq = es;
}
