// Halo exchange: each rank sends its boundary layer to each neighbour and receives the neighbour's layer into its
// ghost layer. The 5- and 7-point stencils have no diagonal terms, so only faces are exchanged (no edges/corners).
//
// Two variants, chosen at run time (--halo):
//   blocking: for each split direction, two MPI_Sendrecv calls (up, then down); the stencil runs afterwards.
//   overlap:  MPI_Irecv/MPI_Isend for all faces, then the stencil on the interior points that need no ghost value,
//             then MPI_Waitall, then the stencil on the boundary shell.
//
// Planted bug for qualifying checks/validate.py (CMake -DPLANT_HALO_BUG=1 or 2; 0 = correct build):
//   1 (skip):  the high-side ghost layer in direction 0 is never written after receiving it (it keeps zeros);
//   2 (shift): the face sent to the high neighbour in direction 0 is the ghost layer, one plane too far, instead of
//              the last interior plane.
// Both affect only faces between ranks, so 1-rank runs are unchanged.
#pragma once
#include <mpi.h>

#include <vector>

#include "grid.hpp"
#include "kernels.hpp"

enum class HaloMode { blocking, overlap };

class Halo {
public:
    explicit Halo(const Grid& G);
    void exchange_blocking(double* x);
    void start(double* x);   // overlap: post receives, pack, post sends
    void finish(double* x);  // overlap: wait, unpack
    long messages_per_exchange() const;  // faces with a real neighbour (sent and received)
    long doubles_per_exchange() const;   // values sent per exchange

private:
    struct Face {
        int a = 0, side = 0, nbr = MPI_PROC_NULL;
        long cnt = 0;
        Buf send, recv;
    };
    const Grid& G;
    Face faces[6];  // index 2a + side (side 0 = low, 1 = high)
    std::vector<MPI_Request> req;
    void pack(const double* x, Face& f);
    void unpack(double* x, Face& f);
    Face& face(int a, int side) { return faces[2 * a + side]; }
};
