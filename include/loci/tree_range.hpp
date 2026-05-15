#pragma once
#include "loci/loci.hpp"
#include "loci/trace.hpp"

namespace loci {

struct TreeRangeParams {
    std::uint32_t universe = 1u << 20;
    CryptoMode crypto_mode = CryptoMode::Mock;
};

struct TreeNodeMeta {
    std::uint64_t handle = 0;
    std::uint64_t tag = 0;
};

class TreeRangeBaseline {
    TreeRangeParams params_;
    MockCrypto crypto_;
    ServerEDB server_;
    std::map<int, std::uint32_t> active_;
    std::uint32_t leaf_base_ = 1;
    std::map<std::uint32_t, std::set<int>> node_base_ids_;
    std::map<std::uint32_t, std::set<int>> node_ids_;
    std::map<std::uint32_t, std::vector<Patch>> node_updates_;
    std::map<std::uint32_t, TreeNodeMeta> node_meta_;
    std::map<std::uint64_t, LeakageCellTrace> leakage_trace_;
    TranscriptStats transcript_;
    TraceLog trace_;

public:
    explicit TreeRangeBaseline(TreeRangeParams params, std::uint64_t key = 0xC001D00DULL);

    BuildStats build(const std::vector<Record>& records);
    std::vector<int> search(std::uint32_t L, std::uint32_t R);
    void insert(int id, std::uint32_t value);
    void erase(int id);

    std::vector<int> plaintext_search(std::uint32_t L, std::uint32_t R) const;
    void check_correctness(std::mt19937& rng, int trials);

    const TranscriptStats& transcript() const { return transcript_; }
    std::size_t active_size() const { return active_.size(); }
    std::size_t server_bytes() const { return server_.byte_size(); }
    std::size_t logical_cell_count() const { return node_ids_.size(); }
    LBCStorageStats lbc_storage_stats() const { return LBCStorageStats{}; }
    LeakageEvalResult evaluate_leakage(std::size_t top_k = 0) const;
    void reset_measurements();
    void write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const;

    void print_summary(std::ostream& os) const;

private:
    TreeNodeMeta meta(std::uint32_t node);
    std::vector<std::uint32_t> path_nodes(std::uint32_t value) const;
    std::vector<std::uint32_t> cover_nodes(std::uint32_t L, std::uint32_t R) const;
    SealedObject seal_node(std::uint32_t node);
    SealedObject seal_delta(std::uint32_t node, std::size_t index, const Patch& patch);
    void upload_node(std::uint32_t node);
    std::uint64_t delta_tag(std::uint32_t node, std::size_t index);
    std::vector<int> open_node(std::uint32_t node, const SealedObject& obj) const;
    LeakageCellTrace& leakage_node(std::uint32_t node);
    void record_search_node(std::uint32_t node, const SealedObject& obj);
    void record_update_node(std::uint32_t node);
};

} // namespace loci
