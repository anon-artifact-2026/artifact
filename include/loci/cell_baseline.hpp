#pragma once
#include "loci/loci.hpp"
#include "pgm/pgm_index.hpp"
#include <memory>

namespace loci {

enum class CellLayoutKind {
    PGMLearned,
    FixedWidth
};

struct CellBaselineParams {
    std::uint32_t universe = 1u << 20;
    int target_cell_size = 512;
    int theta = 32;
    int pad_pool_size = 1024;
    int public_refresh_period = 64;
    CryptoMode crypto_mode = CryptoMode::Mock;
    CellLayoutKind layout = CellLayoutKind::PGMLearned;
    bool global_padding = false;
};

class CellBaseline {
    struct Cell {
        std::uint64_t handle = 0;
        std::uint64_t full_tag = 0;
        std::uint32_t lo = 0;
        std::uint32_t hi = 0;
        std::vector<Record> base_records;
        std::vector<Record> live_records;
        std::vector<Patch> log;
        std::vector<std::uint64_t> log_tags;
        std::uint64_t version = 0;

        bool intersects(std::uint32_t L, std::uint32_t R) const { return !(R < lo || hi < L); }
        bool contains(std::uint32_t value) const { return lo <= value && value <= hi; }
    };

    struct CellQueryContext {
        int cell_index = -1;
        std::uint32_t L = 0;
        std::uint32_t R = 0;
        int visible_log_count = 0;
    };

    CellBaselineParams params_;
    MockCrypto crypto_;
    PaddingPolicy padding_;
    ServerEDB server_;
    std::vector<Cell> cells_;
    std::map<int, std::uint32_t> active_;
    std::map<std::uint64_t, LeakageCellTrace> leakage_trace_;
    std::vector<std::uint32_t> guide_keys_;
    std::unique_ptr<pgm::PGMIndex<std::uint32_t, 64>> pgm_;
    std::uint64_t nonce_ = 1;
    std::uint32_t fixed_cell_width_ = 1;
    std::size_t global_record_capacity_ = 0;
    std::size_t pad_cursor_ = 0;
    std::vector<std::uint64_t> pad_tags_;
    int public_update_clock_ = 0;
    int public_refresh_cursor_ = 0;
    TranscriptStats transcript_;
    TraceLog trace_;

public:
    explicit CellBaseline(CellBaselineParams params, std::uint64_t key = 0xC001D00DULL);

    BuildStats build(const std::vector<Record>& records);
    std::vector<int> search(std::uint32_t L, std::uint32_t R);
    void insert(int id, std::uint32_t value);
    void erase(int id);

    std::vector<int> plaintext_search(std::uint32_t L, std::uint32_t R) const;
    void check_correctness(std::mt19937& rng, int trials);

    const TranscriptStats& transcript() const { return transcript_; }
    std::size_t active_size() const { return active_.size(); }
    std::size_t server_bytes() const { return server_.byte_size(); }
    std::size_t logical_cell_count() const { return cells_.size(); }
    LBCStorageStats lbc_storage_stats() const { return LBCStorageStats{}; }
    LeakageEvalResult evaluate_leakage(std::size_t top_k = 0) const;
    void reset_measurements();
    void write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const;

    void print_summary(std::ostream& os) const;

private:
    std::uint64_t fresh_handle();
    void rebuild_cells_from_active();
    void build_pgm_cells(const std::vector<Record>& sorted);
    void build_fixed_cells(const std::vector<Record>& sorted);
    void train_pgm_guide(const std::vector<Record>& sorted);
    int locate_cell(std::uint32_t value);
    int first_intersecting_cell(std::uint32_t L);
    int last_intersecting_cell(std::uint32_t R);

    Bytes serialize_records(const std::vector<Record>& records) const;
    std::vector<Record> deserialize_records(const Bytes& bytes) const;
    std::size_t cell_object_pad() const;
    std::size_t patch_object_pad() const;
    std::size_t token_fanout_class(std::size_t refs) const;
    std::uint64_t cell_log_tag(const Cell& cell, int slot) const;
    std::size_t upload_cell(Cell& cell, bool erase_existing);
    void refresh_cell(int cell_index, MaintenanceCause cause);
    void append_patch(int cell_index, const Patch& patch);
    void advance_public_refresh();

    void ensure_pad_pool(std::size_t min_tags);
    std::uint64_t next_pad_tag();
    LeakageCellTrace& leakage_cell(std::uint64_t handle);
    void record_search_leakage(const Cell& cell, int visible_log_count, std::size_t refs, std::uint64_t bytes);
    void record_update_leakage(const Cell& cell);
    void record_maintenance_leakage(const Cell& cell, MaintenanceCause cause);
};

} // namespace loci
