#pragma once
#include "loci/lbc.hpp"
#include "loci/leakage_evaluator.hpp"
#include "loci/rank_guide.hpp"
#include "loci/transcript.hpp"
#include "loci/trace.hpp"

namespace loci {

struct LOCIParams {
    std::uint32_t universe = 1u << 20;
    LBCParams lbc;
    int guide_segments = 64;
    int pad_pool_size = 1024;
    int public_fanout_base = 16;
    int public_refresh_period = 64;
    int split_load_percent = 90;
    int merge_load_percent = 25;
    CryptoMode crypto_mode = CryptoMode::Mock;
    bool enable_prototypes = true;
    bool enable_padding = true;
    bool enable_public_refresh = true;
    bool enable_certification = true;
    bool public_refresh_always = true;
    bool expose_log_length = false;
    bool expose_token_order = false;
};

struct CellLocation {
    int cell = -1;
    int slot = -1;
    std::uint32_t value = 0;
};

struct ContextEntry {
    int cell_index = -1;
    std::uint64_t handle = 0;
    std::uint32_t L = 0;
    std::uint32_t R = 0;
    bool full = false;
    int j_left = 0;
    int j_right = 0;
    int log_count = 0;
};

struct QueryContext {
    std::vector<ContextEntry> entries;
};

struct Plan {
    QueryToken token;
    QueryContext context;
};

struct BuildStats {
    double train_ms = 0;
    double certify_ms = 0;
    double encode_ms = 0;
};

enum class MaintenanceCause {
    Manual,
    Scheduled,
    LogFull
};

class LOCIIndex {
    LOCIParams params_;
    MockCrypto crypto_;
    PaddingPolicy padding_;
    LBCEncoder lbc_;
    RankGuide guide_;
    ServerEDB server_;
    std::vector<ClientCell> cells_;
    std::map<int, std::uint32_t> active_;
    std::map<int, CellLocation> locator_;
    std::map<std::uint64_t, LeakageCellTrace> leakage_trace_;
    std::vector<std::uint64_t> pad_tags_;
    std::uint64_t nonce_ = 1;
    std::size_t pad_cursor_ = 0;
    int updates_since_guide_ = 0;
    int public_update_clock_ = 0;
    int public_refresh_cursor_ = 0;
    TranscriptStats transcript_;
    TraceLog trace_;

public:
    explicit LOCIIndex(LOCIParams params, std::uint64_t key = 0xC001D00DULL);

    BuildStats build(const std::vector<Record>& records);
    Plan token_gen(std::uint32_t L, std::uint32_t R);
    QueryResponse server_fetch(const QueryToken& token);
    std::vector<int> decode(const QueryContext& context, const QueryResponse& response);
    std::vector<int> search(std::uint32_t L, std::uint32_t R);

    void insert(int id, std::uint32_t value);
    void erase(int id);
    void refresh(int cell_index);

    std::vector<int> plaintext_search(std::uint32_t L, std::uint32_t R) const;
    void check_correctness(std::mt19937& rng, int trials);

    const TranscriptStats& transcript() const { return transcript_; }
    const std::vector<ClientCell>& cells() const { return cells_; }
    const ServerEDB& server() const { return server_; }
    std::size_t active_size() const { return active_.size(); }
    std::size_t server_bytes() const { return server_.byte_size(); }
    std::size_t guide_segments() const { return guide_.segment_count(); }
    std::size_t logical_cell_count() const { return cells_.size(); }
    LBCStorageStats lbc_storage_stats() const;
    LeakageEvalResult evaluate_leakage(std::size_t top_k = 0) const;
    void reset_measurements();
    void write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const;

    void print_summary(std::ostream& os) const;

private:
    std::uint64_t fresh_handle();
    std::vector<std::vector<Record>> certify_cells(std::vector<Record> records);
    void install_cell(std::size_t position, EncodedCell encoded);
    void attach_certificate(ClientCell& cell) const;
    void rebuild_locator();
    void retrain_guide();
    void maybe_retrain_guide();
    void rebuild_all_from_active();

    int hint_cell(std::uint32_t value);
    int locate_cell(std::uint32_t value);
    int choose_cell_for_insert(std::uint32_t value);
    int first_intersecting_cell(std::uint32_t L);
    int last_intersecting_cell(std::uint32_t R);

    std::pair<int,int> boundary_indices(const ClientCell& cell, std::uint32_t L, std::uint32_t R) const;
    void add_ref(QueryToken& token, std::uint64_t tag) const;
    void fetch_boundary(QueryToken& token, const ClientCell& cell, int boundary_index) const;
    void shuffle_token(QueryToken& token);
    void record_public_classes();
    std::size_t certified_fanout_class(std::size_t refs) const;
    void ensure_pad_pool(std::size_t min_tags);
    std::uint64_t next_pad_tag();
    LeakageCellTrace& leakage_cell(std::uint64_t handle);
    void record_search_leakage(const ClientCell& cell, int log_count, std::size_t response_refs, std::uint64_t response_bytes);
    void record_update_leakage(const ClientCell& cell);
    void record_maintenance_leakage(std::uint64_t handle, MaintenanceCause cause);

    LBCParams cell_lbc_params(std::size_t record_count) const;
    LBCEncoder encoder_for(const ClientCell& cell) const;
    EncodedCell encode_cell(std::uint64_t handle, std::uint32_t lo, std::uint32_t hi, std::vector<Record> records) const;
    void write_patch(int cell_index, const Patch& patch);
    void ensure_log_capacity(int cell_index);
    void refresh_cell(int cell_index, MaintenanceCause cause);
    void advance_public_refresh_automaton();
    void try_public_split(int cell_index);
    void ensure_insert_capacity(int cell_index, std::uint32_t incoming_value);
    void split_cell(int cell_index, std::uint32_t incoming_value);
    void try_merge_around(int cell_index, bool public_tick);
    std::size_t upload_encoded_cell(EncodedCell& encoded);
};

} // namespace loci
