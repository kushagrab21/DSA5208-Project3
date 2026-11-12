// Semi-supervised community labelling: choice of the K communities, the seed vertices, and the evaluation set.
// Rank 0 does this once from the .cmty file (it is small); the result is broadcast.
//
//   communities  the K largest communities of the file that are "disjoint enough": taken greedily by size (file order
//                breaks ties); a community is taken if at most theta of its members are already in a taken one
//                AND at most theta of each taken community's members are in it.
//   exclusive    a vertex in exactly one of the K taken communities; only exclusive vertices are seeds or evaluated.
//   seeds        for community c, the s exclusive members with the smallest key mix64(snap_id ^ mix64(seed)); the
//                key does not depend on s, c, the vertex order or the rank count, so the seeds for s = 5 are the
//                first 5 of the seeds for s = 20, and both vertex orders and every rank count use the same seeds.
//   evaluated    exclusive vertices that are not seeds; their ground-truth label is their community.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

struct Labelling {
    int K = 0, s = 0;
    double theta = 0.1;
    uint64_t seed = 1;
    std::vector<int> lines;                 // file line (0-based community number) of each taken community
    std::vector<long> sizes, exclusive;     // members, exclusive members
    std::vector<std::vector<int64_t>> seeds;  // global vertex numbers, per community
    std::vector<int32_t> truth;             // per vertex (global): community 0..K-1 if evaluated, -1 otherwise
    long n_eval = 0;
    double majority = 0;                    // share of the largest class among the evaluated vertices
    std::string record;                     // the seed list as text (SNAP ids), recorded and hashed
};

// Rank 0. Returns false with err (unreadable file, fewer than K communities, or s >= exclusive members).
bool choose_labelling(const std::string& cmty_path, int64_t V, const std::vector<int64_t>& orig, int K, int s,
                      double theta, uint64_t seed, const std::string& dataset, Labelling& L, std::string& err);
