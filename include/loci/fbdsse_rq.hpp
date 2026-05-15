#pragma once
#include "loci/tree_range.hpp"

namespace loci {

struct FBDSSERQParams {
    std::uint32_t universe = 1u << 20;
    CryptoMode crypto_mode = CryptoMode::Mock;
};

class FBDSSERQBackend {
    TreeRangeBaseline tree_;

public:
    explicit FBDSSERQBackend(FBDSSERQParams params, std::uint64_t key = 0xC001D00DULL)
        : tree_(TreeRangeParams{params.universe, params.crypto_mode}, key) {}

    BuildStats build(const std::vector<Record>& records) { return tree_.build(records); }
    std::vector<int> search(std::uint32_t L, std::uint32_t R) { return tree_.search(L, R); }
    void insert(int id, std::uint32_t value) { tree_.insert(id, value); }
    void erase(int id) { tree_.erase(id); }

    std::vector<int> plaintext_search(std::uint32_t L, std::uint32_t R) const { return tree_.plaintext_search(L, R); }
    void check_correctness(std::mt19937& rng, int trials) { tree_.check_correctness(rng, trials); }

    const TranscriptStats& transcript() const { return tree_.transcript(); }
    std::size_t active_size() const { return tree_.active_size(); }
    std::size_t server_bytes() const { return tree_.server_bytes(); }
    std::size_t logical_cell_count() const { return tree_.logical_cell_count(); }
    LBCStorageStats lbc_storage_stats() const { return tree_.lbc_storage_stats(); }
    LeakageEvalResult evaluate_leakage(std::size_t top_k = 0) const { return tree_.evaluate_leakage(top_k); }
    void reset_measurements() { tree_.reset_measurements(); }
    void write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const {
        tree_.write_trace(dir, scheme, dataset);
    }

    void print_summary(std::ostream& os) const {
        os << "fbdsse_rq_treecover=1 ";
        tree_.print_summary(os);
    }
};

} // namespace loci
