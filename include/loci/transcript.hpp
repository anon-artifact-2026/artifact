#pragma once
#include "loci/common.hpp"

namespace loci {

struct TranscriptStats {
    std::uint64_t searches = 0;
    std::uint64_t updates = 0;
    std::uint64_t refreshes = 0;
    std::uint64_t splits = 0;
    std::uint64_t merges = 0;
    std::uint64_t touched_cells = 0;
    std::uint64_t fetched_objects = 0;
    std::uint64_t response_bytes = 0;
    std::uint64_t patch_bytes = 0;
    std::uint64_t refresh_bytes = 0;
    std::uint64_t guide_locates = 0;
    std::uint64_t guide_corrections = 0;
    std::uint64_t token_padding_refs = 0;
    std::uint64_t max_token_refs = 0;
    std::uint64_t max_fanout_class = 0;
    std::uint64_t log_refs = 0;
    std::uint64_t raw_log_length_exposures = 0;
    std::uint64_t max_visible_log_refs_per_cell = 0;
    std::uint64_t ordered_token_exposures = 0;
    std::uint64_t cert_capacity_class = 0;
    std::uint64_t cert_fanout_class = 0;
    std::uint64_t cert_log_class = 0;
    std::uint64_t cert_maintenance_class = 0;
    std::uint64_t cert_split_load_class = 0;
    std::uint64_t cert_merge_load_class = 0;
    std::uint64_t cert_desc_object_class = 0;
    std::uint64_t cert_proto_object_class = 0;
    std::uint64_t cert_patch_object_class = 0;
    std::uint64_t cert_full_object_class = 0;
    std::uint64_t refresh_class_events = 0;
    std::uint64_t split_class_events = 0;
    std::uint64_t merge_class_events = 0;
    std::uint64_t public_refresh_ticks = 0;
    std::uint64_t scheduled_refreshes = 0;
    std::uint64_t forced_log_refreshes = 0;
    std::uint64_t forced_capacity_splits = 0;
    std::uint64_t public_split_events = 0;
    std::uint64_t public_merge_events = 0;
    std::uint64_t cert_candidate_cells = 0;
    std::uint64_t cert_certified_cells = 0;
    std::uint64_t cert_capacity_overflow_splits = 0;
    std::uint64_t guide_retrains = 0;
    std::uint64_t locator_rebuilds = 0;
    double patch_update_latency_ms_total = 0.0;
    double maintenance_latency_ms_total = 0.0;
    double refresh_latency_ms_total = 0.0;

    void write_csv_header(std::ostream& os) const {
        os << "searches,updates,refreshes,splits,merges,touched_cells,fetched_objects,response_bytes,patch_bytes,refresh_bytes,guide_locates,guide_corrections,token_padding_refs,max_token_refs,max_fanout_class,log_refs,raw_log_length_exposures,max_visible_log_refs_per_cell,ordered_token_exposures,cert_capacity_class,cert_fanout_class,cert_log_class,cert_maintenance_class,cert_split_load_class,cert_merge_load_class,cert_desc_object_class,cert_proto_object_class,cert_patch_object_class,cert_full_object_class,refresh_class_events,split_class_events,merge_class_events,public_refresh_ticks,scheduled_refreshes,forced_log_refreshes,forced_capacity_splits,public_split_events,public_merge_events,cert_candidate_cells,cert_certified_cells,cert_capacity_overflow_splits";
    }
    void write_csv_row(std::ostream& os) const {
        os << searches << ',' << updates << ',' << refreshes << ',' << splits << ',' << merges << ','
           << touched_cells << ',' << fetched_objects << ',' << response_bytes << ',' << patch_bytes << ','
           << refresh_bytes << ',' << guide_locates << ',' << guide_corrections << ','
           << token_padding_refs << ',' << max_token_refs << ',' << max_fanout_class << ','
           << log_refs << ',' << raw_log_length_exposures << ',' << max_visible_log_refs_per_cell << ','
           << ordered_token_exposures << ','
           << cert_capacity_class << ',' << cert_fanout_class << ',' << cert_log_class << ','
           << cert_maintenance_class << ',' << cert_split_load_class << ',' << cert_merge_load_class << ','
           << cert_desc_object_class << ',' << cert_proto_object_class << ',' << cert_patch_object_class << ','
           << cert_full_object_class << ',' << refresh_class_events << ',' << split_class_events << ','
           << merge_class_events << ',' << public_refresh_ticks << ',' << scheduled_refreshes << ','
           << forced_log_refreshes << ',' << forced_capacity_splits << ',' << public_split_events << ','
           << public_merge_events << ',' << cert_candidate_cells << ',' << cert_certified_cells << ','
           << cert_capacity_overflow_splits;
    }
};

} // namespace loci
