// Binary CSR file of an undirected simple graph: written by p3convert (convert.cpp), read by p3graph (dcsr.cpp).
//
//   offset 0        char[8]  magic "P3CSR001"
//   offset 8        int64    V      vertices, numbered 0..V-1
//                   int64    nnz    stored entries = 2E (both directions of every edge; no self-loops, no duplicates)
//                   int64    E      undirected edges
//                   int64    order  0 = natural (SNAP ids ascending), 1 = BFS (Cuthill-McKee) order
//   offset 40       int64    rowptr[V+1]
//                   int32    col[nnz]   neighbours of each row, ascending
//                   int64    orig[V]    the SNAP id of each vertex (communities and seeds are defined on these ids)
//
// Next to it, PREFIX.<order>.cmty: text, line 1 "# p3cmty-1 ...", then one community per line (vertex numbers of the
// same file, ascending), in the order of the SNAP community file.
#pragma once
#include <cstdint>

namespace csrfile {
constexpr char kMagic[9] = "P3CSR001";
constexpr int64_t kHeaderBytes = 40;
inline int64_t rowptr_offset() { return kHeaderBytes; }
inline int64_t col_offset(int64_t V) { return kHeaderBytes + 8 * (V + 1); }
inline int64_t orig_offset(int64_t V, int64_t nnz) { return col_offset(V) + 4 * nnz; }
inline int64_t file_bytes(int64_t V, int64_t nnz) { return orig_offset(V, nnz) + 8 * V; }

// Deterministic 64-bit mixing (splitmix64 finaliser): seeds and the edge-sparsification test use it on SNAP ids, so
// they are the same in every vertex order, at every rank count and with every compiler and C++ library.
inline uint64_t mix64(uint64_t z) {
    z += 0x9e3779b97f4a7c15ULL;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}
}  // namespace csrfile
