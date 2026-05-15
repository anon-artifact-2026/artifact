#pragma once
#include "loci/common.hpp"
#include <filesystem>
#include <sstream>

namespace loci {

struct SearchTraceRow {
    std::uint64_t t = 0;
    std::uint64_t qid = 0;
    std::string touched_units;
    std::uint64_t token_count = 0;
    std::uint64_t token_class = 0;
    std::uint64_t response_class = 0;
    std::uint64_t object_bytes = 0;
    std::uint64_t result_size_class = 0;
    std::uint64_t full_cells = 0;
    std::uint64_t boundary_cells = 0;
    int visible_order = 0;
    double latency_ms = 0.0;
};

struct UpdateTraceRow {
    std::uint64_t t = 0;
    std::string op;
    std::string touched_unit;
    std::uint64_t patch_class = 0;
    std::uint64_t update_bytes = 0;
    std::string raw_log_len_visible;
    double latency_ms = 0.0;
};

struct MaintenanceTraceRow {
    std::uint64_t t = 0;
    std::string event_type;
    std::string touched_units;
    std::uint64_t maint_class = 0;
    std::string raw_trigger_visible;
    std::uint64_t new_object_class = 0;
    double latency_ms = 0.0;
};

struct LayoutUnitRow {
    std::string unit_id;
    std::uint64_t unit_class = 0;
    std::string hidden_load_label;
    std::string hidden_region_label;
    std::uint64_t region_lo = 0;
    std::uint64_t region_hi = 0;
    std::uint64_t true_load = 0;
    std::uint64_t true_log_used = 0;
    std::uint64_t true_update_touches = 0;
    std::uint64_t private_maintenance_events = 0;
    std::uint64_t private_log_full_events = 0;
    std::uint64_t distinct_values = 0;
    std::string update_intensity_label;
};

struct TraceLog {
    std::vector<SearchTraceRow> searches;
    std::vector<UpdateTraceRow> updates;
    std::vector<MaintenanceTraceRow> maintenance;
    std::uint64_t clock = 0;
    std::uint64_t next_qid = 0;

    void clear() {
        searches.clear();
        updates.clear();
        maintenance.clear();
        clock = 0;
        next_qid = 0;
    }

    std::uint64_t tick() { return ++clock; }
    std::uint64_t qid() { return ++next_qid; }
};

inline std::string csv_escape(const std::string& s) {
    bool quote = false;
    for (char c : s) {
        if (c == ',' || c == '"' || c == '\n' || c == '\r') {
            quote = true;
            break;
        }
    }
    if (!quote) return s;
    std::string out = "\"";
    for (char c : s) {
        if (c == '"') out += "\"\"";
        else out.push_back(c);
    }
    out.push_back('"');
    return out;
}

inline std::string handle_string(std::uint64_t handle) {
    std::ostringstream os;
    os << std::hex << handle;
    return os.str();
}

inline std::string join_handles(const std::vector<std::uint64_t>& handles) {
    std::ostringstream os;
    for (std::size_t i = 0; i < handles.size(); ++i) {
        if (i) os << ';';
        os << std::hex << handles[i] << std::dec;
    }
    return os.str();
}

inline std::string load_label(std::uint64_t load, std::uint64_t unit_class) {
    if (unit_class == 0) return std::to_string(load);
    if (load * 4 <= unit_class) return "low";
    if (load * 4 <= unit_class * 3) return "mid";
    return "high";
}

inline std::string update_label(std::uint64_t updates) {
    if (updates == 0) return "none";
    if (updates <= 2) return "low";
    if (updates <= 8) return "mid";
    return "high";
}

inline void write_trace_csvs(const std::string& dir,
                             const std::string& scheme,
                             const std::string& dataset,
                             const TraceLog& trace,
                             const std::vector<LayoutUnitRow>& layout) {
    if (dir.empty()) return;
    std::filesystem::create_directories(dir);

    auto append = [&](const std::string& name, const std::string& header, auto writer) {
        std::filesystem::path path = std::filesystem::path(dir) / name;
        bool exists = std::filesystem::exists(path);
        std::ofstream os(path, std::ios::app);
        if (!exists) os << header << '\n';
        writer(os);
    };

    append("search_trace.csv",
           "scheme,dataset,t,qid,touched_units,token_count,token_class,response_class,object_bytes,result_size_class,full_cells,boundary_cells,visible_order,latency",
           [&](std::ostream& os) {
               for (const auto& r : trace.searches) {
                   os << scheme << ',' << dataset << ',' << r.t << ',' << r.qid << ','
                      << csv_escape(r.touched_units) << ',' << r.token_count << ',' << r.token_class << ','
                      << r.response_class << ',' << r.object_bytes << ',' << r.result_size_class << ','
                      << r.full_cells << ',' << r.boundary_cells << ','
                      << r.visible_order << ',' << r.latency_ms << '\n';
               }
           });

    append("update_trace.csv",
           "scheme,dataset,t,op,touched_unit,patch_class,update_bytes,raw_log_len_visible,latency",
           [&](std::ostream& os) {
               for (const auto& r : trace.updates) {
                   os << scheme << ',' << dataset << ',' << r.t << ',' << r.op << ','
                      << csv_escape(r.touched_unit) << ',' << r.patch_class << ',' << r.update_bytes << ','
                      << csv_escape(r.raw_log_len_visible) << ',' << r.latency_ms << '\n';
               }
           });

    append("maintenance_trace.csv",
           "scheme,dataset,t,event_type,touched_units,maint_class,raw_trigger_visible,new_object_class,latency",
           [&](std::ostream& os) {
               for (const auto& r : trace.maintenance) {
                   os << scheme << ',' << dataset << ',' << r.t << ',' << r.event_type << ','
                      << csv_escape(r.touched_units) << ',' << r.maint_class << ','
                      << csv_escape(r.raw_trigger_visible) << ',' << r.new_object_class << ','
                      << r.latency_ms << '\n';
               }
           });

    append("layout_units.csv",
           "scheme,dataset,unit_id,unit_class,hidden_load_label,hidden_region_label,region_lo,region_hi,true_load,true_log_used,true_update_touches,private_maintenance_events,private_log_full_events,distinct_values,update_intensity_label",
           [&](std::ostream& os) {
               for (const auto& r : layout) {
                   os << scheme << ',' << dataset << ',' << csv_escape(r.unit_id) << ','
                      << r.unit_class << ',' << r.hidden_load_label << ',' << r.hidden_region_label << ','
                      << r.region_lo << ',' << r.region_hi << ','
                      << r.true_load << ',' << r.true_log_used << ',' << r.true_update_touches << ','
                      << r.private_maintenance_events << ',' << r.private_log_full_events << ','
                      << r.distinct_values << ',' << r.update_intensity_label << '\n';
               }
           });
}

} // namespace loci
