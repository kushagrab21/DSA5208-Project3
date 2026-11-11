// Structured grid on the unit square (dim 2) or unit cube (dim 3), split over a Cartesian process grid.
//
// Global problem: n interior points per direction, spacing h = 1/(n+1), zero Dirichlet values on the boundary.
// Each rank owns a box of nl[0] x nl[1] x nl[2] interior points and stores it with one ghost layer on every side.
// A ghost layer facing another rank holds that rank's boundary values after a halo exchange; a ghost layer facing
// the physical boundary stays 0, which is how the Dirichlet condition enters the stencil.
// In 2D there is no direction 2: nl[2] = 1 and it has no ghosts.
//
// Memory layout: idx(i,j,k) = (i*L[1] + j)*L[2] + k, k fastest. Interior indices run i in [1, nl0], j in [1, nl1],
// k in [g2, g2 + nl2) with g2 = 1 in 3D and 0 in 2D.
#pragma once
#include <mpi.h>
#include <cstddef>
#include <string>

struct Grid {
    int dim = 3;
    long n = 0;            // global interior points per direction
    double h = 0.0;        // 1/(n+1)
    int decomp = 3;        // number of directions split across ranks (1, 2 or 3; at most dim)
    int pdims[3] = {1, 1, 1};
    int coords[3] = {0, 0, 0};
    int nbr[3][2] = {{MPI_PROC_NULL, MPI_PROC_NULL}, {MPI_PROC_NULL, MPI_PROC_NULL}, {MPI_PROC_NULL, MPI_PROC_NULL}};
    long nl[3] = {1, 1, 1};   // local interior points per direction
    long off[3] = {0, 0, 0};  // global index (0-based) of the first local interior point
    long g[3] = {1, 1, 1};    // ghost width per direction (g[2] = 0 in 2D)
    long L[3] = {1, 1, 1};    // allocated extent per direction, nl + 2g
    long S0 = 0, S1 = 0;      // strides of directions 0 and 1; direction 2 has stride 1
    size_t ntot = 0;          // allocated points per vector, ghosts included
    MPI_Comm cart = MPI_COMM_NULL;
    int rank = 0, size = 1;

    long idx(long i, long j, long k) const { return (i * L[1] + j) * L[2] + k; }
    long local_points() const { return nl[0] * nl[1] * nl[2]; }
};

// Builds the Cartesian communicator (MPI_Dims_create + MPI_Cart_create) and the local box.
// Returns false and sets err if the requested decomposition cannot hold at least one point per rank.
bool make_grid(Grid& G, int dim, long n, int decomp, MPI_Comm world, std::string& err);

// Unknowns and nonzeros of the assembled matrix this matrix-free operator represents:
// N = n^d, nnz = n^d + 2 d (n-1) n^(d-1)  (diagonal plus two off-diagonals per grid direction).
long long unknowns(int dim, long n);
long long nonzeros(int dim, long n);
