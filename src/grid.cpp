#include "grid.hpp"

#include <algorithm>

bool make_grid(Grid& G, int dim, long n, int decomp, MPI_Comm world, std::string& err) {
    G.dim = dim;
    G.n = n;
    G.h = 1.0 / double(n + 1);
    G.decomp = decomp;

    int size = 1;
    MPI_Comm_size(world, &size);

    // Directions 0..decomp-1 are free for MPI_Dims_create; the rest are fixed at 1 process.
    // MPI_Dims_create returns non-increasing factors, so direction 0 (the slowest-varying index, whose faces are
    // contiguous planes) always gets the most processes. A "1D" decomposition is a split into slabs along i.
    int pd[3] = {0, 0, 0};
    for (int a = 0; a < dim; ++a) pd[a] = (a < decomp) ? 0 : 1;
    MPI_Dims_create(size, dim, pd);
    for (int a = 0; a < 3; ++a) G.pdims[a] = (a < dim) ? pd[a] : 1;

    for (int a = 0; a < dim; ++a) {
        if (n < G.pdims[a]) {
            err = "n=" + std::to_string(n) + " is smaller than the " + std::to_string(G.pdims[a]) +
                  " processes in direction " + std::to_string(a);
            return false;
        }
    }

    int periods[3] = {0, 0, 0};
    MPI_Cart_create(world, dim, pd, periods, /*reorder=*/1, &G.cart);
    MPI_Comm_rank(G.cart, &G.rank);
    MPI_Comm_size(G.cart, &G.size);
    int c[3] = {0, 0, 0};
    MPI_Cart_coords(G.cart, G.rank, dim, c);
    for (int a = 0; a < 3; ++a) G.coords[a] = (a < dim) ? c[a] : 0;
    for (int a = 0; a < dim; ++a) MPI_Cart_shift(G.cart, a, 1, &G.nbr[a][0], &G.nbr[a][1]);

    // Block distribution: the first (n mod p) ranks in a direction get one extra point.
    for (int a = 0; a < 3; ++a) {
        if (a >= dim) {
            G.nl[a] = 1;
            G.off[a] = 0;
            continue;
        }
        long p = G.pdims[a], q = n / p, r = n % p, ca = G.coords[a];
        G.nl[a] = q + (ca < r ? 1 : 0);
        G.off[a] = ca * q + std::min<long>(ca, r);
    }
    G.g[0] = 1;
    G.g[1] = 1;
    G.g[2] = (dim == 3) ? 1 : 0;
    for (int a = 0; a < 3; ++a) G.L[a] = G.nl[a] + 2 * G.g[a];
    G.S1 = G.L[2];
    G.S0 = G.L[1] * G.L[2];
    G.ntot = size_t(G.L[0]) * size_t(G.L[1]) * size_t(G.L[2]);
    return true;
}

long long unknowns(int dim, long n) {
    long long N = 1;
    for (int a = 0; a < dim; ++a) N *= n;
    return N;
}

long long nonzeros(int dim, long n) {
    long long N = unknowns(dim, n);
    long long face = 1;
    for (int a = 0; a < dim - 1; ++a) face *= n;
    return N + 2LL * dim * (n - 1) * face;
}
