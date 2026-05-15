#include "loci/tree_range.hpp"
#include <cmath>
#include <iomanip>

namespace loci {

static Bytes serialize_ids(const std::set<int>& ids) {
    ByteWriter w;
    w.u32(static_cast<std::uint32_t>(ids.size()));
    for (int id : ids) w.i32(id);
    return w.data;
}

static std::vector<int> deserialize_ids(const Bytes& bytes) {
    ByteReader r(bytes);
    auto n = r.u32();
    std::vector<int> out;
    out.reserve(n);
    for (std::uint32_t i = 0; i < n; ++i) out.push_back(r.i32());
    return out;
}

TreeRangeBaseline::TreeRangeBaseline(TreeRangeParams params, std::uint64_t key)
    : params_(params), crypto_(key, params.crypto_mode) {
    if (params_.universe == 0) throw std::runtime_error("TreeRangeParams: universe must be positive");
    leaf_base_ = 1;
    while (leaf_base_ < params_.universe) leaf_base_ <<= 1;
}

TreeNodeMeta TreeRangeBaseline::meta(std::uint32_t node) {
    auto it = node_meta_.find(node);
    if (it != node_meta_.end()) return it->second;
    std::uint64_t handle = crypto_.handle(static_cast<std::uint64_t>(node));
    std::uint64_t tag = crypto_.tag(handle, ObjectKind::Cell, 0);
    auto m = TreeNodeMeta{handle, tag};
    node_meta_[node] = m;
    return m;
}

std::vector<std::uint32_t> TreeRangeBaseline::path_nodes(std::uint32_t value) const {
    if (value >= params_.universe) throw std::runtime_error("TreeRangeBaseline: value out of universe");
    std::vector<std::uint32_t> out;
    std::uint32_t node = leaf_base_ + value;
    while (node >= 1) {
        out.push_back(node);
        if (node == 1) break;
        node >>= 1;
    }
    return out;
}

std::vector<std::uint32_t> TreeRangeBaseline::cover_nodes(std::uint32_t L, std::uint32_t R) const {
    if (L > R) std::swap(L, R);
    R = std::min<std::uint32_t>(R, params_.universe - 1);
    L = std::min<std::uint32_t>(L, params_.universe - 1);
    std::uint32_t l = leaf_base_ + L;
    std::uint32_t r = leaf_base_ + R;
    std::vector<std::uint32_t> left, right;
    while (l <= r) {
        if ((l & 1U) == 1U) left.push_back(l++);
        if ((r & 1U) == 0U) right.push_back(r--);
        l >>= 1;
        r >>= 1;
    }
    left.insert(left.end(), right.rbegin(), right.rend());
    return left;
}

SealedObject TreeRangeBaseline::seal_node(std::uint32_t node) {
    auto m = meta(node);
    auto it = node_base_ids_.find(node);
    const std::set<int> empty;
    const auto& ids = (it == node_ids_.end()) ? empty : it->second;
    return crypto_.seal(m.tag, serialize_ids(ids), 0);
}

std::uint64_t TreeRangeBaseline::delta_tag(std::uint32_t node, std::size_t index) {
    auto m = meta(node);
    return crypto_.tag(m.handle, ObjectKind::Log, static_cast<std::uint64_t>(index));
}

SealedObject TreeRangeBaseline::seal_delta(std::uint32_t node, std::size_t index, const Patch& patch) {
    return crypto_.seal(delta_tag(node, index), serialize_patch(patch), 0);
}

void TreeRangeBaseline::upload_node(std::uint32_t node) {
    auto m = meta(node);
    auto obj = seal_node(node);
    server_.put(m.handle, obj);
}

std::vector<int> TreeRangeBaseline::open_node(std::uint32_t, const SealedObject& obj) const {
    return deserialize_ids(crypto_.open(obj));
}

LeakageCellTrace& TreeRangeBaseline::leakage_node(std::uint32_t node) {
    auto m = meta(node);
    auto& row = leakage_trace_[m.handle];
    row.handle = m.handle;
    auto it = node_ids_.find(node);
    row.true_load = (it == node_ids_.end()) ? 0 : static_cast<std::uint64_t>(it->second.size());
    return row;
}

void TreeRangeBaseline::record_search_node(std::uint32_t node, const SealedObject& obj) {
    auto& row = leakage_node(node);
    row.search_touches++;
    row.response_refs++;
    row.response_bytes += obj.padded_size;
}

void TreeRangeBaseline::record_update_node(std::uint32_t node) {
    auto& row = leakage_node(node);
    row.update_touches++;
    row.true_update_touches++;
    row.maintenance_events++;
}

BuildStats TreeRangeBaseline::build(const std::vector<Record>& records) {
    BuildStats bs;
    Timer t;
    active_.clear();
    node_base_ids_.clear();
    node_ids_.clear();
    node_updates_.clear();
    node_meta_.clear();
    leakage_trace_.clear();
    server_ = ServerEDB{};
    transcript_ = TranscriptStats{};
    trace_.clear();
    transcript_.cert_capacity_class = leaf_base_;
    transcript_.cert_log_class = static_cast<std::uint64_t>(std::log2(static_cast<double>(leaf_base_))) + 1;

    for (const auto& rec : records) {
        if (rec.value >= params_.universe) throw std::runtime_error("TreeRangeBaseline::build: record outside universe");
        active_[rec.id] = rec.value;
        for (auto node : path_nodes(rec.value)) node_ids_[node].insert(rec.id);
    }
    node_base_ids_ = node_ids_;
    bs.train_ms = 0.0;
    bs.certify_ms = 0.0;

    t.reset();
    for (const auto& [node, _] : node_ids_) upload_node(node);
    bs.encode_ms = t.ms();
    return bs;
}

std::vector<int> TreeRangeBaseline::search(std::uint32_t L, std::uint32_t R) {
    Timer timer;
    auto cover = cover_nodes(L, R);
    transcript_.searches++;
    transcript_.touched_cells += cover.size();

    std::set<int> result;
    std::uint64_t object_bytes = 0;
    std::uint64_t fetched = 0;
    std::vector<std::uint64_t> handles;
    handles.reserve(cover.size());
    for (auto node : cover) {
        auto m = meta(node);
        handles.push_back(m.handle);
        SealedObject obj;
        if (server_.has(m.tag)) obj = server_.fetch(m.tag);
        else obj = seal_node(node);
        transcript_.response_bytes += obj.padded_size;
        object_bytes += obj.padded_size;
        ++fetched;
        record_search_node(node, obj);
        std::set<int> materialized;
        for (int id : open_node(node, obj)) materialized.insert(id);
        auto upd_it = node_updates_.find(node);
        if (upd_it != node_updates_.end()) {
            for (std::size_t ui = 0; ui < upd_it->second.size(); ++ui) {
                auto tag = delta_tag(node, ui);
                if (!server_.has(tag)) continue;
                auto delta = server_.fetch(tag);
                transcript_.response_bytes += delta.padded_size;
                object_bytes += delta.padded_size;
                ++fetched;
                auto patch = deserialize_patch(crypto_.open(delta));
                if (patch.op == PatchOp::Add) materialized.insert(patch.id);
                else if (patch.op == PatchOp::Del) materialized.erase(patch.id);
            }
        }
        for (int id : materialized) {
            auto it = active_.find(id);
            if (it != active_.end() && std::min(L, R) <= it->second && it->second <= std::max(L, R)) {
                result.insert(id);
            }
        }
    }
    transcript_.fetched_objects += fetched;
    transcript_.max_token_refs = std::max<std::uint64_t>(transcript_.max_token_refs, fetched);
    transcript_.max_fanout_class = std::max<std::uint64_t>(transcript_.max_fanout_class, fetched);
    trace_.searches.push_back(SearchTraceRow{
        trace_.tick(),
        trace_.qid(),
        join_handles(handles),
        fetched,
        fetched,
        object_bytes,
        object_bytes,
        static_cast<std::uint64_t>(result.size()),
        static_cast<std::uint64_t>(cover.size()),
        0,
        1,
        timer.ms()});
    return std::vector<int>(result.begin(), result.end());
}

void TreeRangeBaseline::insert(int id, std::uint32_t value) {
    Timer timer;
    if (active_.count(id)) throw std::runtime_error("TreeRangeBaseline::insert duplicate id");
    if (value >= params_.universe) throw std::runtime_error("TreeRangeBaseline::insert outside universe");
    active_[id] = value;
    std::size_t bytes = 0;
    std::vector<std::uint64_t> handles;
    for (auto node : path_nodes(value)) {
        node_ids_[node].insert(id);
        Patch patch{PatchOp::Add, id, value, -1};
        auto& updates = node_updates_[node];
        auto obj = seal_delta(node, updates.size(), patch);
        updates.push_back(patch);
        server_.put(meta(node).handle, obj);
        bytes += obj.padded_size;
        handles.push_back(meta(node).handle);
        record_update_node(node);
    }
    transcript_.updates++;
    transcript_.patch_bytes += bytes;
    double latency_ms = timer.ms();
    transcript_.patch_update_latency_ms_total += latency_ms;
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "insert",
        join_handles(handles),
        static_cast<std::uint64_t>(transcript_.cert_log_class),
        static_cast<std::uint64_t>(bytes),
        "",
        latency_ms});
}

void TreeRangeBaseline::erase(int id) {
    Timer timer;
    auto it = active_.find(id);
    if (it == active_.end()) throw std::runtime_error("TreeRangeBaseline::erase missing id");
    std::uint32_t value = it->second;
    active_.erase(it);
    std::size_t bytes = 0;
    std::vector<std::uint64_t> handles;
    for (auto node : path_nodes(value)) {
        auto n_it = node_ids_.find(node);
        if (n_it != node_ids_.end()) {
            n_it->second.erase(id);
            if (n_it->second.empty()) node_ids_.erase(n_it);
        }
        Patch patch{PatchOp::Del, id, value, -1};
        auto& updates = node_updates_[node];
        auto obj = seal_delta(node, updates.size(), patch);
        updates.push_back(patch);
        server_.put(meta(node).handle, obj);
        bytes += obj.padded_size;
        handles.push_back(meta(node).handle);
        record_update_node(node);
    }
    transcript_.updates++;
    transcript_.patch_bytes += bytes;
    double latency_ms = timer.ms();
    transcript_.patch_update_latency_ms_total += latency_ms;
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "erase",
        join_handles(handles),
        static_cast<std::uint64_t>(transcript_.cert_log_class),
        static_cast<std::uint64_t>(bytes),
        "",
        latency_ms});
}

std::vector<int> TreeRangeBaseline::plaintext_search(std::uint32_t L, std::uint32_t R) const {
    if (L > R) std::swap(L, R);
    std::vector<int> out;
    for (const auto& [id, value] : active_) if (L <= value && value <= R) out.push_back(id);
    std::sort(out.begin(), out.end());
    return out;
}

void TreeRangeBaseline::check_correctness(std::mt19937& rng, int trials) {
    std::uniform_int_distribution<std::uint32_t> dist(0, params_.universe - 1);
    for (int i = 0; i < trials; ++i) {
        auto L = dist(rng), R = dist(rng);
        if (L > R) std::swap(L, R);
        auto got = search(L, R);
        auto exp = plaintext_search(L, R);
        if (got != exp) {
            std::cerr << "TreeRange correctness failure for [" << L << "," << R << "] got="
                      << got.size() << " exp=" << exp.size() << "\n";
            throw std::runtime_error("TreeRange correctness check failed");
        }
    }
}

LeakageEvalResult TreeRangeBaseline::evaluate_leakage(std::size_t top_k) const {
    std::vector<LeakageCellTrace> rows;
    rows.reserve(leakage_trace_.size());
    for (auto row : leakage_trace_) rows.push_back(row.second);
    return evaluate_leakage_trace(std::move(rows), top_k);
}

void TreeRangeBaseline::reset_measurements() {
    transcript_ = TranscriptStats{};
    leakage_trace_.clear();
    trace_.clear();
    transcript_.cert_capacity_class = leaf_base_;
    transcript_.cert_log_class = static_cast<std::uint64_t>(std::log2(static_cast<double>(leaf_base_))) + 1;
}

void TreeRangeBaseline::write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const {
    std::vector<LayoutUnitRow> layout;
    layout.reserve(node_ids_.size());
    for (const auto& [node, ids] : node_ids_) {
        std::set<std::uint32_t> distinct;
        for (int id : ids) {
            auto it = active_.find(id);
            if (it != active_.end()) distinct.insert(it->second);
        }
        auto meta_it = node_meta_.find(node);
        std::uint64_t handle = (meta_it == node_meta_.end()) ? 0 : meta_it->second.handle;
        std::uint64_t updates = 0;
        auto leak_it = leakage_trace_.find(handle);
        if (leak_it != leakage_trace_.end()) updates = leak_it->second.true_update_touches;
        const std::uint64_t true_load = static_cast<std::uint64_t>(ids.size());
        layout.push_back(LayoutUnitRow{
            handle_string(handle),
            transcript_.cert_capacity_class,
            load_label(true_load, std::max<std::uint64_t>(1, active_.size())),
            "tree_node_" + std::to_string(node),
            0,
            params_.universe == 0 ? 0 : static_cast<std::uint64_t>(params_.universe - 1),
            true_load,
            0,
            updates,
            0,
            0,
            static_cast<std::uint64_t>(distinct.size()),
            update_label(updates)});
    }
    write_trace_csvs(dir, scheme, dataset, trace_, layout);
}

void TreeRangeBaseline::print_summary(std::ostream& os) const {
    std::size_t max_posting = 0;
    for (const auto& [_, ids] : node_ids_) max_posting = std::max(max_posting, ids.size());
    os << "tree_nodes=" << node_ids_.size()
       << " active=" << active_.size()
       << " leaf_base=" << leaf_base_
       << " max_posting=" << max_posting
       << " server_objects=" << server_.object_count()
       << " server_bytes=" << server_.byte_size() << '\n';
}

} // namespace loci
