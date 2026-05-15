#include "loci/cell_baseline.hpp"
#include <iomanip>

namespace loci {

CellBaseline::CellBaseline(CellBaselineParams params, std::uint64_t key)
    : params_(params), crypto_(key, params.crypto_mode),
      padding_(params.global_padding ? PaddingPolicy{} : PaddingPolicy{0, 0, 0, 0}) {
    if (params_.universe == 0) throw std::runtime_error("CellBaselineParams: universe must be positive");
    if (params_.target_cell_size <= 0) throw std::runtime_error("CellBaselineParams: target_cell_size must be positive");
    if (params_.theta <= 0) throw std::runtime_error("CellBaselineParams: theta must be positive");
    if (params_.pad_pool_size < 0) throw std::runtime_error("CellBaselineParams: pad_pool_size must be non-negative");
    if (params_.public_refresh_period < 0) throw std::runtime_error("CellBaselineParams: public_refresh_period must be non-negative");
}

std::uint64_t CellBaseline::fresh_handle() { return crypto_.handle(nonce_++); }

Bytes CellBaseline::serialize_records(const std::vector<Record>& records) const {
    ByteWriter w;
    w.u32(static_cast<std::uint32_t>(records.size()));
    for (const auto& rec : records) {
        w.i32(rec.id);
        w.u32(rec.value);
    }
    return w.data;
}

std::vector<Record> CellBaseline::deserialize_records(const Bytes& bytes) const {
    ByteReader r(bytes);
    auto n = r.u32();
    std::vector<Record> out;
    out.reserve(n);
    for (std::uint32_t i = 0; i < n; ++i) out.push_back(Record{r.i32(), r.u32()});
    return out;
}

std::size_t CellBaseline::cell_object_pad() const {
    if (!params_.global_padding) return 0;
    std::size_t plain = 4 + 8 * std::max<std::size_t>(1, global_record_capacity_);
    return next_power_of_two(8 + plain, 64);
}

std::size_t CellBaseline::patch_object_pad() const {
    return params_.global_padding ? padding_.patch_pad() : 0;
}

std::size_t CellBaseline::token_fanout_class(std::size_t refs) const {
    if (!params_.global_padding) return refs;
    return std::max<std::size_t>(refs, cells_.size() * static_cast<std::size_t>(1 + params_.theta));
}

std::uint64_t CellBaseline::cell_log_tag(const Cell& cell, int slot) const {
    return crypto_.tag(cell.handle, ObjectKind::Log,
                       cell.version * static_cast<std::uint64_t>(params_.theta) + static_cast<std::uint64_t>(slot));
}

void CellBaseline::train_pgm_guide(const std::vector<Record>& sorted) {
    guide_keys_.clear();
    guide_keys_.reserve(sorted.size());
    for (const auto& rec : sorted) guide_keys_.push_back(rec.value);
    if (guide_keys_.empty()) {
        pgm_.reset();
    } else {
        pgm_ = std::make_unique<pgm::PGMIndex<std::uint32_t, 64>>(guide_keys_.begin(), guide_keys_.end());
    }
}

void CellBaseline::build_pgm_cells(const std::vector<Record>& sorted) {
    train_pgm_guide(sorted);
    cells_.clear();
    if (sorted.empty()) {
        Cell cell;
        cell.handle = fresh_handle();
        cell.lo = 0;
        cell.hi = params_.universe - 1;
        cells_.push_back(std::move(cell));
        return;
    }

    std::size_t target = static_cast<std::size_t>(params_.target_cell_size);
    for (std::size_t off = 0; off < sorted.size(); off += target) {
        std::size_t end = std::min(sorted.size(), off + target);
        Cell cell;
        cell.handle = fresh_handle();
        cell.live_records.assign(sorted.begin() + static_cast<long>(off), sorted.begin() + static_cast<long>(end));
        cell.base_records = cell.live_records;
        cells_.push_back(std::move(cell));
    }

    for (std::size_t i = 0; i < cells_.size(); ++i) {
        if (i == 0) cells_[i].lo = 0;
        else cells_[i].lo = cells_[i].live_records.empty() ? cells_[i - 1].hi : cells_[i].live_records.front().value;

        if (i + 1 == cells_.size()) {
            cells_[i].hi = params_.universe - 1;
        } else {
            auto next_lo = cells_[i + 1].live_records.empty() ? params_.universe - 1 : cells_[i + 1].live_records.front().value;
            auto this_hi = cells_[i].live_records.empty() ? next_lo : cells_[i].live_records.back().value;
            cells_[i].hi = (next_lo > this_hi) ? (next_lo - 1) : this_hi;
        }
    }
}

void CellBaseline::build_fixed_cells(const std::vector<Record>& sorted) {
    cells_.clear();
    std::size_t target = static_cast<std::size_t>(params_.target_cell_size);
    std::size_t cell_count = std::max<std::size_t>(1, (sorted.size() + target - 1) / target);
    std::uint64_t width64 = (static_cast<std::uint64_t>(params_.universe) + cell_count - 1) / cell_count;
    fixed_cell_width_ = static_cast<std::uint32_t>(std::max<std::uint64_t>(1, width64));

    cells_.resize(cell_count);
    for (std::size_t i = 0; i < cell_count; ++i) {
        auto& cell = cells_[i];
        cell.handle = fresh_handle();
        std::uint64_t lo = static_cast<std::uint64_t>(i) * fixed_cell_width_;
        std::uint64_t hi = std::min<std::uint64_t>(params_.universe - 1, (static_cast<std::uint64_t>(i) + 1) * fixed_cell_width_ - 1);
        cell.lo = static_cast<std::uint32_t>(std::min<std::uint64_t>(lo, params_.universe - 1));
        cell.hi = static_cast<std::uint32_t>(hi);
    }

    for (const auto& rec : sorted) {
        std::size_t idx = std::min<std::size_t>(cells_.size() - 1, rec.value / fixed_cell_width_);
        cells_[idx].live_records.push_back(rec);
    }
    for (auto& cell : cells_) {
        std::sort(cell.live_records.begin(), cell.live_records.end(), record_less);
        cell.base_records = cell.live_records;
    }
}

std::size_t CellBaseline::upload_cell(Cell& cell, bool erase_existing) {
    if (erase_existing) server_.erase_cell(cell.handle);
    cell.full_tag = crypto_.tag(cell.handle, ObjectKind::Full, cell.version);
    cell.log_tags.resize(static_cast<std::size_t>(params_.theta));

    auto full = crypto_.seal(cell.full_tag, serialize_records(cell.base_records), cell_object_pad());
    std::size_t bytes = full.padded_size;
    server_.put(cell.handle, full);

    for (int i = 0; i < params_.theta; ++i) {
        cell.log_tags[static_cast<std::size_t>(i)] = cell_log_tag(cell, i);
        if (params_.global_padding) {
            auto dummy = crypto_.seal(cell.log_tags[static_cast<std::size_t>(i)], serialize_patch(Patch{}), patch_object_pad());
            bytes += dummy.padded_size;
            server_.put(cell.handle, dummy);
        }
    }
    return bytes;
}

BuildStats CellBaseline::build(const std::vector<Record>& records) {
    BuildStats stats;
    Timer timer;
    active_.clear();
    cells_.clear();
    leakage_trace_.clear();
    guide_keys_.clear();
    pgm_.reset();
    server_ = ServerEDB{};
    transcript_ = TranscriptStats{};
    trace_.clear();
    nonce_ = 1;
    pad_cursor_ = 0;
    pad_tags_.clear();
    public_update_clock_ = 0;
    public_refresh_cursor_ = 0;

    std::vector<Record> sorted = records;
    std::sort(sorted.begin(), sorted.end(), record_less);
    for (const auto& rec : sorted) {
        if (rec.value >= params_.universe) throw std::runtime_error("CellBaseline::build: record outside universe");
        active_[rec.id] = rec.value;
    }

    timer.reset();
    if (params_.layout == CellLayoutKind::PGMLearned) build_pgm_cells(sorted);
    else build_fixed_cells(sorted);
    stats.train_ms = timer.ms();

    global_record_capacity_ = 1;
    for (const auto& cell : cells_) global_record_capacity_ = std::max(global_record_capacity_, cell.live_records.size() + static_cast<std::size_t>(params_.theta));
    transcript_.cert_capacity_class = params_.global_padding ? static_cast<std::uint64_t>(global_record_capacity_) : 0;
    transcript_.cert_fanout_class = params_.global_padding ? static_cast<std::uint64_t>(token_fanout_class(0)) : 0;
    transcript_.cert_log_class = static_cast<std::uint64_t>(params_.theta);
    transcript_.cert_maintenance_class = params_.global_padding ? static_cast<std::uint64_t>(params_.public_refresh_period) : 0;
    transcript_.cert_patch_object_class = static_cast<std::uint64_t>(
        crypto_.sealed_size(serialize_patch(Patch{}).size(), patch_object_pad()));
    transcript_.cert_full_object_class = params_.global_padding
        ? static_cast<std::uint64_t>(crypto_.sealed_size(4 + 8 * global_record_capacity_, cell_object_pad()))
        : 0;
    transcript_.cert_candidate_cells = cells_.size();
    transcript_.cert_certified_cells = cells_.size();

    timer.reset();
    for (auto& cell : cells_) upload_cell(cell, false);
    if (params_.global_padding) ensure_pad_pool(static_cast<std::size_t>(params_.pad_pool_size));
    stats.encode_ms = timer.ms();
    return stats;
}

int CellBaseline::locate_cell(std::uint32_t value) {
    if (cells_.empty()) return -1;
    int idx = 0;
    if (params_.layout == CellLayoutKind::FixedWidth) {
        idx = static_cast<int>(std::min<std::size_t>(cells_.size() - 1, value / fixed_cell_width_));
    } else {
        transcript_.guide_locates++;
        if (pgm_ && !guide_keys_.empty()) {
            auto pos = pgm_->search(value).pos;
            idx = static_cast<int>(std::min<std::size_t>(cells_.size() - 1, pos / static_cast<std::size_t>(params_.target_cell_size)));
        }
    }
    while (idx > 0 && value < cells_[static_cast<std::size_t>(idx)].lo) {
        --idx;
        transcript_.guide_corrections++;
    }
    while (idx + 1 < static_cast<int>(cells_.size()) && value > cells_[static_cast<std::size_t>(idx)].hi) {
        ++idx;
        transcript_.guide_corrections++;
    }
    return idx;
}

int CellBaseline::first_intersecting_cell(std::uint32_t L) {
    int i = locate_cell(L);
    if (i < 0) return -1;
    while (i > 0 && cells_[static_cast<std::size_t>(i - 1)].hi >= L) --i;
    while (i < static_cast<int>(cells_.size()) && cells_[static_cast<std::size_t>(i)].hi < L) ++i;
    return i < static_cast<int>(cells_.size()) ? i : -1;
}

int CellBaseline::last_intersecting_cell(std::uint32_t R) {
    int i = locate_cell(R);
    if (i < 0) return -1;
    while (i + 1 < static_cast<int>(cells_.size()) && cells_[static_cast<std::size_t>(i + 1)].lo <= R) ++i;
    while (i >= 0 && cells_[static_cast<std::size_t>(i)].lo > R) --i;
    return i;
}

LeakageCellTrace& CellBaseline::leakage_cell(std::uint64_t handle) {
    auto& row = leakage_trace_[handle];
    row.handle = handle;
    return row;
}

void CellBaseline::record_search_leakage(const Cell& cell, int visible_log_count, std::size_t refs, std::uint64_t bytes) {
    auto& row = leakage_cell(cell.handle);
    row.search_touches++;
    row.visible_log_refs += static_cast<std::uint64_t>(std::max(0, visible_log_count));
    row.max_visible_log_refs = std::max<std::uint64_t>(row.max_visible_log_refs, static_cast<std::uint64_t>(std::max(0, visible_log_count)));
    row.response_refs += static_cast<std::uint64_t>(refs);
    row.response_bytes += bytes;
}

void CellBaseline::record_update_leakage(const Cell& cell) {
    auto& row = leakage_cell(cell.handle);
    row.update_touches++;
    row.true_update_touches++;
}

void CellBaseline::record_maintenance_leakage(const Cell& cell, MaintenanceCause cause) {
    auto& row = leakage_cell(cell.handle);
    row.maintenance_events++;
    if (cause != MaintenanceCause::Scheduled) row.true_private_maintenance_events++;
    if (cause == MaintenanceCause::LogFull) row.true_log_full_events++;
}

void CellBaseline::ensure_pad_pool(std::size_t min_tags) {
    if (!params_.global_padding || min_tags == 0) return;
    std::size_t target = pad_tags_.empty()
        ? std::max<std::size_t>(min_tags, static_cast<std::size_t>(params_.pad_pool_size))
        : std::max<std::size_t>(min_tags, pad_tags_.size());
    target = next_power_of_two(target, 1);
    const std::uint64_t pad_handle = crypto_.prf(static_cast<std::uint64_t>(ObjectKind::Pad), 0x504144504f4f4cULL);
    while (pad_tags_.size() < target) {
        std::uint64_t tag = crypto_.tag(pad_handle, ObjectKind::Pad, static_cast<std::uint64_t>(pad_tags_.size()));
        auto obj = crypto_.seal(tag, Bytes{}, patch_object_pad());
        server_.put(pad_handle, obj);
        pad_tags_.push_back(tag);
    }
}

std::uint64_t CellBaseline::next_pad_tag() {
    ensure_pad_pool(1);
    if (pad_tags_.empty()) throw std::runtime_error("CellBaseline: padding requested without pad objects");
    std::uint64_t tag = pad_tags_[pad_cursor_ % pad_tags_.size()];
    pad_cursor_ = (pad_cursor_ + 1) % pad_tags_.size();
    return tag;
}

std::vector<int> CellBaseline::search(std::uint32_t L, std::uint32_t R) {
    Timer timer;
    if (L > R) std::swap(L, R);
    QueryToken token;
    std::vector<CellQueryContext> context;
    std::vector<std::uint64_t> handles;
    int left = first_intersecting_cell(L);
    int right = last_intersecting_cell(R);
    if (left >= 0 && right >= left) {
        for (int ci = left; ci <= right; ++ci) {
            const auto& cell = cells_[static_cast<std::size_t>(ci)];
            if (!cell.intersects(L, R)) continue;
            std::size_t before = token.refs.size();
            token.refs.push_back(FetchRef{cell.full_tag});
            int visible_logs = params_.global_padding ? params_.theta : static_cast<int>(cell.log.size());
            for (int li = 0; li < visible_logs; ++li) token.refs.push_back(FetchRef{cell.log_tags[static_cast<std::size_t>(li)]});
            transcript_.log_refs += static_cast<std::uint64_t>(visible_logs);
            transcript_.max_visible_log_refs_per_cell = std::max<std::uint64_t>(
                transcript_.max_visible_log_refs_per_cell,
                static_cast<std::uint64_t>(visible_logs));

            std::uint64_t bytes = 0;
            for (std::size_t ri = before; ri < token.refs.size(); ++ri) bytes += server_.fetch(token.refs[ri].tag).padded_size;
            record_search_leakage(cell, visible_logs, token.refs.size() - before, bytes);
            if (!params_.global_padding) transcript_.raw_log_length_exposures++;
            context.push_back(CellQueryContext{ci, std::max(L, cell.lo), std::min(R, cell.hi), visible_logs});
            handles.push_back(cell.handle);
        }
    }

    if (params_.global_padding) {
        std::size_t before = token.refs.size();
        std::size_t target = token_fanout_class(before);
        ensure_pad_pool(target - before);
        while (token.refs.size() < target) token.refs.push_back(FetchRef{next_pad_tag()});
        transcript_.token_padding_refs += target - before;
        transcript_.max_fanout_class = std::max<std::uint64_t>(transcript_.max_fanout_class, target);
        if (token.refs.size() > 1) {
            std::uint64_t seed = crypto_.prf(0x43454c4c53485546ULL, nonce_++);
            std::mt19937_64 rng(seed);
            std::shuffle(token.refs.begin(), token.refs.end(), rng);
        }
    } else {
        transcript_.ordered_token_exposures++;
        transcript_.max_fanout_class = std::max<std::uint64_t>(transcript_.max_fanout_class, token.refs.size());
    }

    transcript_.searches++;
    transcript_.touched_cells += context.size();
    transcript_.fetched_objects += token.refs.size();
    transcript_.max_token_refs = std::max<std::uint64_t>(transcript_.max_token_refs, token.refs.size());
    std::uint64_t object_bytes = 0;
    for (const auto& ref : token.refs) {
        auto bytes = server_.fetch(ref.tag).padded_size;
        transcript_.response_bytes += bytes;
        object_bytes += bytes;
    }
    auto response = server_.fetch(token);

    std::set<int> answer;
    for (const auto& entry : context) {
        const auto& cell = cells_[static_cast<std::size_t>(entry.cell_index)];
        std::map<int, std::uint32_t> materialized;
        for (const auto& rec : deserialize_records(crypto_.open(response.objects.at(cell.full_tag)))) {
            materialized[rec.id] = rec.value;
        }
        for (int li = 0; li < entry.visible_log_count; ++li) {
            auto patch = deserialize_patch(crypto_.open(response.objects.at(cell.log_tags[static_cast<std::size_t>(li)])));
            if (patch.op == PatchOp::Add) materialized[patch.id] = patch.value;
            else if (patch.op == PatchOp::Del) materialized.erase(patch.id);
        }
        for (const auto& [id, value] : materialized) {
            auto active_it = active_.find(id);
            if (active_it != active_.end() && active_it->second == value && entry.L <= value && value <= entry.R) {
                answer.insert(id);
            }
        }
    }
    trace_.searches.push_back(SearchTraceRow{
        trace_.tick(),
        trace_.qid(),
        join_handles(handles),
        static_cast<std::uint64_t>(token.refs.size()),
        params_.global_padding ? static_cast<std::uint64_t>(token_fanout_class(token.refs.size())) : static_cast<std::uint64_t>(token.refs.size()),
        params_.global_padding ? static_cast<std::uint64_t>(next_power_of_two(static_cast<std::size_t>(object_bytes), 1)) : object_bytes,
        object_bytes,
        params_.global_padding ? static_cast<std::uint64_t>(next_power_of_two(answer.size(), 1)) : static_cast<std::uint64_t>(answer.size()),
        static_cast<std::uint64_t>(context.size()),
        0,
        params_.global_padding ? 0 : 1,
        timer.ms()});
    return std::vector<int>(answer.begin(), answer.end());
}

void CellBaseline::refresh_cell(int cell_index, MaintenanceCause cause) {
    Timer timer;
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) return;
    auto& cell = cells_[static_cast<std::size_t>(cell_index)];
    record_maintenance_leakage(cell, cause);
    cell.base_records = cell.live_records;
    std::sort(cell.base_records.begin(), cell.base_records.end(), record_less);
    cell.log.clear();
    cell.version++;

    std::size_t bytes = upload_cell(cell, true);
    transcript_.refreshes++;
    transcript_.refresh_class_events++;
    if (cause == MaintenanceCause::Scheduled) transcript_.scheduled_refreshes++;
    if (cause == MaintenanceCause::LogFull) transcript_.forced_log_refreshes++;
    transcript_.refresh_bytes += bytes;
    std::string raw_trigger;
    if (!params_.global_padding) {
        raw_trigger = (cause == MaintenanceCause::LogFull) ? "log_full" :
            (cause == MaintenanceCause::Scheduled ? "scheduled" : "manual");
    }
    std::string event_type = "refresh";
    if (!params_.global_padding) {
        event_type = cause == MaintenanceCause::Scheduled ? "refresh_scheduled" :
            (cause == MaintenanceCause::LogFull ? "refresh_log_full" : "refresh_manual");
    }
    double latency_ms = timer.ms();
    transcript_.refresh_latency_ms_total += latency_ms;
    transcript_.maintenance_latency_ms_total += latency_ms;
    trace_.maintenance.push_back(MaintenanceTraceRow{
        trace_.tick(),
        event_type,
        handle_string(cell.handle),
        transcript_.cert_maintenance_class,
        raw_trigger,
        transcript_.cert_full_object_class,
        latency_ms});
}

void CellBaseline::append_patch(int cell_index, const Patch& patch) {
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) throw std::runtime_error("CellBaseline::append_patch: cell index out of range");
    if (static_cast<int>(cells_[static_cast<std::size_t>(cell_index)].log.size()) >= params_.theta) {
        refresh_cell(cell_index, MaintenanceCause::LogFull);
    }
    auto& cell = cells_[static_cast<std::size_t>(cell_index)];
    auto slot = static_cast<int>(cell.log.size());
    auto tag = cell.log_tags[static_cast<std::size_t>(slot)];
    auto obj = crypto_.seal(tag, serialize_patch(patch), patch_object_pad());
    server_.put(cell.handle, obj);
    cell.log.push_back(patch);
    transcript_.patch_bytes += obj.padded_size;
}

void CellBaseline::insert(int id, std::uint32_t value) {
    Timer timer;
    std::uint64_t patch_before = transcript_.patch_bytes;
    if (active_.count(id)) throw std::runtime_error("CellBaseline::insert duplicate id");
    if (value >= params_.universe) throw std::runtime_error("CellBaseline::insert outside universe");
    int ci = locate_cell(value);
    if (ci < 0) throw std::runtime_error("CellBaseline::insert could not locate cell");
    if (static_cast<int>(cells_[static_cast<std::size_t>(ci)].log.size()) >= params_.theta) refresh_cell(ci, MaintenanceCause::LogFull);
    Timer patch_timer;
    auto& cell = cells_[static_cast<std::size_t>(ci)];
    cell.live_records.push_back(Record{id, value});
    std::sort(cell.live_records.begin(), cell.live_records.end(), record_less);
    active_[id] = value;
    append_patch(ci, Patch{PatchOp::Add, id, value, -1});
    record_update_leakage(cells_[static_cast<std::size_t>(ci)]);
    transcript_.updates++;
    const auto& updated = cells_[static_cast<std::size_t>(ci)];
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "insert",
        handle_string(updated.handle),
        transcript_.cert_patch_object_class,
        transcript_.patch_bytes - patch_before,
        params_.global_padding ? "" : std::to_string(updated.log.size()),
        timer.ms()});
    transcript_.patch_update_latency_ms_total += patch_timer.ms();
    advance_public_refresh();
}

void CellBaseline::erase(int id) {
    Timer timer;
    std::uint64_t patch_before = transcript_.patch_bytes;
    auto active_it = active_.find(id);
    if (active_it == active_.end()) throw std::runtime_error("CellBaseline::erase missing id");
    std::uint32_t value = active_it->second;
    int ci = locate_cell(value);
    if (ci < 0) throw std::runtime_error("CellBaseline::erase could not locate cell");
    if (static_cast<int>(cells_[static_cast<std::size_t>(ci)].log.size()) >= params_.theta) refresh_cell(ci, MaintenanceCause::LogFull);
    Timer patch_timer;
    auto& cell = cells_[static_cast<std::size_t>(ci)];
    cell.live_records.erase(
        std::remove_if(cell.live_records.begin(), cell.live_records.end(), [&](const Record& rec) { return rec.id == id; }),
        cell.live_records.end());
    active_.erase(active_it);
    append_patch(ci, Patch{PatchOp::Del, id, value, -1});
    record_update_leakage(cells_[static_cast<std::size_t>(ci)]);
    transcript_.updates++;
    const auto& updated = cells_[static_cast<std::size_t>(ci)];
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "erase",
        handle_string(updated.handle),
        transcript_.cert_patch_object_class,
        transcript_.patch_bytes - patch_before,
        params_.global_padding ? "" : std::to_string(updated.log.size()),
        timer.ms()});
    transcript_.patch_update_latency_ms_total += patch_timer.ms();
    advance_public_refresh();
}

void CellBaseline::advance_public_refresh() {
    if (!params_.global_padding || params_.public_refresh_period <= 0 || cells_.empty()) return;
    ++public_update_clock_;
    if (public_update_clock_ < params_.public_refresh_period) return;
    public_update_clock_ = 0;
    transcript_.public_refresh_ticks++;
    int ci = public_refresh_cursor_ % static_cast<int>(cells_.size());
    public_refresh_cursor_ = (public_refresh_cursor_ + 1) % std::max(1, static_cast<int>(cells_.size()));
    refresh_cell(ci, MaintenanceCause::Scheduled);
}

std::vector<int> CellBaseline::plaintext_search(std::uint32_t L, std::uint32_t R) const {
    if (L > R) std::swap(L, R);
    std::vector<int> out;
    for (const auto& [id, value] : active_) if (L <= value && value <= R) out.push_back(id);
    std::sort(out.begin(), out.end());
    return out;
}

void CellBaseline::check_correctness(std::mt19937& rng, int trials) {
    std::uniform_int_distribution<std::uint32_t> dist(0, params_.universe - 1);
    for (int i = 0; i < trials; ++i) {
        auto L = dist(rng), R = dist(rng);
        if (L > R) std::swap(L, R);
        auto got = search(L, R);
        auto exp = plaintext_search(L, R);
        if (got != exp) {
            std::cerr << "CellBaseline correctness failure for [" << L << "," << R << "] got="
                      << got.size() << " exp=" << exp.size() << "\n";
            throw std::runtime_error("CellBaseline correctness check failed");
        }
    }
}

LeakageEvalResult CellBaseline::evaluate_leakage(std::size_t top_k) const {
    std::vector<LeakageCellTrace> rows;
    rows.reserve(cells_.size());
    for (const auto& cell : cells_) {
        LeakageCellTrace row;
        auto it = leakage_trace_.find(cell.handle);
        if (it != leakage_trace_.end()) row = it->second;
        row.handle = cell.handle;
        row.true_load = static_cast<std::uint64_t>(cell.live_records.size());
        row.true_log_used = static_cast<std::uint64_t>(cell.log.size());
        rows.push_back(row);
    }
    return evaluate_leakage_trace(std::move(rows), top_k);
}

void CellBaseline::reset_measurements() {
    transcript_ = TranscriptStats{};
    leakage_trace_.clear();
    trace_.clear();
    transcript_.cert_capacity_class = params_.global_padding ? static_cast<std::uint64_t>(global_record_capacity_) : 0;
    transcript_.cert_fanout_class = params_.global_padding ? static_cast<std::uint64_t>(token_fanout_class(0)) : 0;
    transcript_.cert_log_class = static_cast<std::uint64_t>(params_.theta);
    transcript_.cert_maintenance_class = params_.global_padding ? static_cast<std::uint64_t>(params_.public_refresh_period) : 0;
    transcript_.cert_patch_object_class = static_cast<std::uint64_t>(
        crypto_.sealed_size(serialize_patch(Patch{}).size(), patch_object_pad()));
    transcript_.cert_full_object_class = params_.global_padding
        ? static_cast<std::uint64_t>(crypto_.sealed_size(4 + 8 * global_record_capacity_, cell_object_pad()))
        : 0;
    transcript_.cert_candidate_cells = cells_.size();
    transcript_.cert_certified_cells = cells_.size();
}

void CellBaseline::write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const {
    std::vector<LayoutUnitRow> layout;
    layout.reserve(cells_.size());
    for (const auto& cell : cells_) {
        std::set<std::uint32_t> distinct;
        for (const auto& rec : cell.live_records) distinct.insert(rec.value);
        std::uint64_t updates = 0;
        std::uint64_t private_maintenance = 0;
        std::uint64_t private_log_full = 0;
        auto it = leakage_trace_.find(cell.handle);
        if (it != leakage_trace_.end()) {
            updates = it->second.true_update_touches;
            private_maintenance = it->second.true_private_maintenance_events;
            private_log_full = it->second.true_log_full_events;
        }
        const std::uint64_t true_load = static_cast<std::uint64_t>(cell.live_records.size());
        const std::uint64_t true_log_used = static_cast<std::uint64_t>(cell.log.size());
        const std::uint64_t unit_class = params_.global_padding
            ? static_cast<std::uint64_t>(global_record_capacity_)
            : true_load;
        layout.push_back(LayoutUnitRow{
            handle_string(cell.handle),
            unit_class,
            load_label(true_load, std::max<std::uint64_t>(1, global_record_capacity_)),
            std::to_string(cell.lo) + "-" + std::to_string(cell.hi),
            cell.lo,
            cell.hi,
            true_load,
            true_log_used,
            updates,
            private_maintenance,
            private_log_full,
            static_cast<std::uint64_t>(distinct.size()),
            update_label(updates)});
    }
    write_trace_csvs(dir, scheme, dataset, trace_, layout);
}

void CellBaseline::print_summary(std::ostream& os) const {
    std::size_t max_load = 0;
    std::size_t log_used = 0;
    for (const auto& cell : cells_) {
        max_load = std::max(max_load, cell.live_records.size());
        log_used += cell.log.size();
    }
    os << "cell_layout=" << (params_.layout == CellLayoutKind::PGMLearned ? "pgm_learned" : "fixed_width")
       << " global_padding=" << (params_.global_padding ? 1 : 0)
       << " cells=" << cells_.size()
       << " active=" << active_.size()
       << " max_load=" << max_load
       << " log_used=" << log_used
       << " server_objects=" << server_.object_count()
       << " server_bytes=" << server_.byte_size()
       << " guide_segments=" << (pgm_ ? pgm_->segments_count() : 0)
       << " fixed_cell_width=" << fixed_cell_width_ << '\n';
}

} // namespace loci
