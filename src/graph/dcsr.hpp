// Distributed CSR graph with a 1D row partition, its ghost exchange, and the operator y = (L + aI) x, L = D - A the
// graph Laplacian. CsrOperator has the same apply() as the stencil Operator, so the CG solvers of cg_impl.hpp run on
// it unchanged.
//
// Vector layout on each rank (every vector the solver uses has n_alloc entries):
//     [0, n_own)                 owned rows, in global order (global id = row0 + local index)
//     [n_own, n_pad)             padding to a whole number of RL-chunks; always zero (A writes zeros there)
//     [n_pad, n_pad + n_ghost)   ghosts: values of neighbours owned by other ranks, sorted by global id, so the
//                                ghosts of one owner rank are contiguous; the exchange receives straight into them
// The vector kernels see [0, n_pad) as R0 contiguous rows of RL entries (rows()), so they run in parallel chunks.
#pragma once
#include <mpi.h>

#include <cstdint>
#include <string>
#include <vector>

#include "../cg.hpp"
#include "../kernels.hpp"

#ifndef PLANT_GHOST_BUG
#  define PLANT_GHOST_BUG 0  // 1: the ghosts from each rank's first source neighbour are never stored (validation)
#endif

enum class Part { rows, nnz };                        // equal rows, or equal nonzeros of L + aI (degree + 1)
enum class Exchange { alltoallv, neighbor, overlap };  // MPI_Alltoallv; MPI_Neighbor_alltoallv; the non-blocking
                                                      // MPI_Ineighbor_alltoallv overlapped with the interior rows

struct DistGraph {
    MPI_Comm comm = MPI_COMM_NULL, gcomm = MPI_COMM_NULL;  // gcomm: distributed graph communicator (MPI-3)
    int rank = 0, size = 1;
    int64_t V = 0, nnz_file = 0, E_file = 0;  // as stored in the file
    int order = 0;                            // 0 natural, 1 bfs
    int64_t E_kept = 0;                       // undirected edges after the keep filter (global)
    std::vector<int64_t> bounds;              // rank p owns global rows [bounds[p], bounds[p+1])
    int64_t row0 = 0, row1 = 0;
    long n_own = 0, n_pad = 0, n_ghost = 0, n_alloc = 0, RL = 256;
    std::vector<int64_t> rowptr;  // local CSR (off-diagonal entries only; every value is -1)
    std::vector<int32_t> col;     // local column index: < n_own owned, >= n_pad ghost
    std::vector<double> deg;      // degree of each owned row (after the keep filter)
    std::vector<int64_t> orig;    // SNAP id of each owned row
    std::vector<int64_t> ghost_gid;
    std::vector<int> src, dst;                        // ranks we receive from / send to
    std::vector<int> rcnt, rdsp, scnt, sdsp;          // per src / dst entry (neighbour collectives)
    std::vector<int> rcnt_all, rdsp_all, scnt_all, sdsp_all;  // per rank (MPI_Alltoallv)
    std::vector<int32_t> send_idx;                    // owned local indices to pack, grouped by dst
    std::vector<int32_t> rows_inner, rows_bnd;        // owned rows without / with a ghost neighbour
    long cut_entries = 0;                             // local entries whose column is a ghost
    double t_read = 0, t_build = 0;
    std::vector<int64_t> orig_all;                    // rank 0 only, until release_global(): SNAP id of every vertex

    // Collective. Reads PATH (.csr), partitions the rows, keeps each undirected edge with probability `keep`
    // (decided from the two SNAP ids, so the same edges are kept in every order and at every rank count), and
    // builds the ghost lists and the graph communicator once.
    bool load(const std::string& path, Part part, double keep, uint64_t keep_seed, MPI_Comm comm, std::string& err);
    Rows rows() const;  // [0, n_pad) as R0 x RL contiguous chunks
    int owner(int64_t gid) const;
    void release_global() { std::vector<int64_t>().swap(orig_all); }
    ~DistGraph();
};

class CsrOperator {
public:
    CsrOperator(DistGraph& g, double a, Exchange ex);
    double apply(double* x, double* y, Timers& t);  // y = (L + aI) x on the owned rows; returns the local x.y
    long messages_per_exchange() const { return long(g.dst.size()); }
    long doubles_per_exchange() const { return long(g.send_idx.size()); }

private:
    DistGraph& g;
    double a;
    Exchange ex;
    std::vector<double> sendbuf;
    std::vector<long> tb_all, tb_inner, tb_bnd;  // per-thread chunk boundaries, balanced by nonzeros
    void pack(const double* x);
    double rows_range(const double* x, double* y) const;
    double rows_list(const std::vector<int32_t>& L, const std::vector<long>& tb, const double* x, double* y) const;
};
