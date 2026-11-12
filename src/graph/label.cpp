#include "label.hpp"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <numeric>
#include <sstream>

#include "csrfile.hpp"

bool choose_labelling(const std::string& cmty_path, int64_t V, const std::vector<int64_t>& orig, int K, int s,
                      double theta, uint64_t seed, const std::string& dataset, Labelling& L, std::string& err) {
    std::ifstream f(cmty_path);
    if (!f) {
        err = "cannot read " + cmty_path;
        return false;
    }
    std::vector<std::vector<int64_t>> cm;
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') {
            if (line.empty()) cm.emplace_back();
            continue;
        }
        std::istringstream is(line);
        std::vector<int64_t> c;
        int64_t v;
        while (is >> v) {
            if (v < 0 || v >= V) {
                err = cmty_path + ": vertex out of range";
                return false;
            }
            c.push_back(v);
        }
        cm.push_back(c);
    }
    std::vector<int> idx(cm.size());
    std::iota(idx.begin(), idx.end(), 0);
    std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) { return cm[a].size() > cm[b].size(); });

    // Greedy choice of K disjoint-enough communities.
    std::vector<int32_t> who(V, -1);  // first taken community containing the vertex
    std::vector<int32_t> cnt(V, 0);   // number of taken communities containing it
    L = Labelling();
    L.K = K;
    L.s = s;
    L.theta = theta;
    L.seed = seed;
    for (int c : idx) {
        if (int(L.lines.size()) == K) break;
        if (cm[c].empty()) continue;
        std::vector<long> shared(L.lines.size(), 0);
        long overlap = 0;
        for (int64_t v : cm[c])
            if (cnt[v] > 0) {
                ++overlap;
                shared[who[v]]++;
            }
        bool ok = overlap <= theta * double(cm[c].size());
        for (size_t d = 0; ok && d < L.lines.size(); ++d)
            if (shared[d] > theta * double(L.sizes[d])) ok = false;
        if (!ok) continue;
        const int id = int(L.lines.size());
        L.lines.push_back(c);
        L.sizes.push_back(long(cm[c].size()));
        for (int64_t v : cm[c]) {
            if (cnt[v] == 0) who[v] = id;
            cnt[v]++;
        }
    }
    if (int(L.lines.size()) < K) {
        err = "only " + std::to_string(L.lines.size()) + " disjoint-enough communities (K = " + std::to_string(K) + ")";
        return false;
    }

    // Seeds and the evaluated set.
    const uint64_t salt = csrfile::mix64(seed);
    L.seeds.assign(K, {});
    L.exclusive.assign(K, 0);
    L.truth.assign(V, -1);
    std::ostringstream rec;
    rec << "p3seeds-1 dataset=" << dataset << " K=" << K << " s=" << s << " theta=" << theta << " seed=" << seed
        << "\n";
    std::vector<long> per(K, 0);
    for (int k = 0; k < K; ++k) {
        std::vector<std::pair<uint64_t, int64_t>> ex;
        for (int64_t v : cm[L.lines[k]])
            if (cnt[v] == 1) ex.push_back({csrfile::mix64(uint64_t(orig[v]) ^ salt), v});
        L.exclusive[k] = long(ex.size());
        if (long(ex.size()) <= s) {
            err = "community " + std::to_string(L.lines[k]) + " has " + std::to_string(ex.size()) +
                  " exclusive members, not more than s = " + std::to_string(s);
            return false;
        }
        std::sort(ex.begin(), ex.end());
        rec << "c=" << k << " line=" << L.lines[k] << " size=" << L.sizes[k] << " exclusive=" << ex.size()
            << " seeds=";
        for (int i = 0; i < s; ++i) {
            L.seeds[k].push_back(ex[i].second);
            rec << (i ? "," : "") << orig[ex[i].second];
        }
        rec << "\n";
        for (size_t i = size_t(s); i < ex.size(); ++i) {
            L.truth[ex[i].second] = k;
            per[k]++;
        }
    }
    L.n_eval = std::accumulate(per.begin(), per.end(), 0L);
    L.majority = L.n_eval ? double(*std::max_element(per.begin(), per.end())) / double(L.n_eval) : 0.0;
    L.record = rec.str();
    return true;
}
