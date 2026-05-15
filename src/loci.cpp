#include "loci/loci.hpp"
#include <iomanip>

namespace loci {

static LOCIParams normalize_params(LOCIParams p) {
    if (p.universe == 0) throw std::runtime_error("LOCIParams: universe must be positive");
    if (p.lbc.B <= 0) throw std::runtime_error("LOCIParams: B must be positive");
    if (p.lbc.theta <= 0) throw std::runtime_error("LOCIParams: theta must be positive");
    if (p.lbc.rho <= 0 || p.lbc.kappa <= 0 || p.lbc.rho * p.lbc.kappa != p.lbc.B) throw std::runtime_error("LOCIParams: rho*kappa must equal B");
    if (p.pad_pool_size < 0) throw std::runtime_error("LOCIParams: pad_pool_size must be non-negative");
    if (p.public_fanout_base < 0) throw std::runtime_error("LOCIParams: public_fanout_base must be non-negative");
    if (p.public_refresh_period < 0) throw std::runtime_error("LOCIParams: public_refresh_period must be non-negative");
    if (p.split_load_percent <= 0 || p.split_load_percent > 100) throw std::runtime_error("LOCIParams: split_load_percent must be in 1..100");
    if (p.merge_load_percent < 0 || p.merge_load_percent >= p.split_load_percent) throw std::runtime_error("LOCIParams: merge_load_percent must be below split_load_percent");
    if (!p.enable_prototypes) p.lbc.max_prototypes = 1;
    if (!p.enable_padding) p.public_fanout_base = 0;
    return p;
}

static int load_threshold(int capacity, int percent) {
    return std::max(1, (capacity * percent + 99) / 100);
}

LOCIIndex::LOCIIndex(LOCIParams params, std::uint64_t key)
    : params_(normalize_params(params)), crypto_(key, params_.crypto_mode),
      padding_(params_.enable_padding ? PaddingPolicy{} : PaddingPolicy{0,0,0,0}),
      lbc_(params_.lbc, crypto_, padding_) {}

std::uint64_t LOCIIndex::fresh_handle() { return crypto_.handle(nonce_++); }

std::vector<std::vector<Record>> LOCIIndex::certify_cells(std::vector<Record> records) {
    std::sort(records.begin(), records.end(), record_less);
    std::vector<std::vector<Record>> candidates;
    if (records.empty()) {
        candidates.emplace_back();
        transcript_.cert_candidate_cells = 1;
        transcript_.cert_certified_cells = 1;
        return candidates;
    }

    std::vector<Record> cur;
    int last_bucket = -1;
    for (const auto& rec : records) {
        int bucket = static_cast<int>(guide_.predict_rank(rec.value) / std::max(1, params_.lbc.B));
        bool cut_by_learned_bucket = !cur.empty() && bucket != last_bucket;
        if (cut_by_learned_bucket) {
            candidates.push_back(cur);
            cur.clear();
        }
        cur.push_back(rec);
        last_bucket = bucket;
    }
    if (!cur.empty()) candidates.push_back(cur);

    if (!params_.enable_certification) {
        transcript_.cert_candidate_cells = candidates.size();
        transcript_.cert_certified_cells = candidates.size();
        return candidates;
    }

    std::vector<std::vector<Record>> certified;
    for (auto& c : candidates) {
        std::sort(c.begin(), c.end(), record_less);
        std::size_t pieces = 0;
        for (std::size_t off = 0; off < c.size(); off += static_cast<std::size_t>(params_.lbc.B)) {
            std::size_t end = std::min(c.size(), off + static_cast<std::size_t>(params_.lbc.B));
            certified.emplace_back(c.begin() + static_cast<long>(off), c.begin() + static_cast<long>(end));
            ++pieces;
        }
        if (pieces > 1) transcript_.cert_capacity_overflow_splits += pieces - 1;
    }
    if (certified.empty()) certified.emplace_back();
    transcript_.cert_candidate_cells = candidates.size();
    transcript_.cert_certified_cells = certified.size();
    return certified;
}

BuildStats LOCIIndex::build(const std::vector<Record>& records) {
    BuildStats bs;
    active_.clear(); locator_.clear(); cells_.clear(); server_ = ServerEDB{}; transcript_ = TranscriptStats{}; trace_.clear(); nonce_ = 1;
    leakage_trace_.clear();
    pad_tags_.clear();
    pad_cursor_ = 0;
    updates_since_guide_ = 0;
    public_update_clock_ = 0;
    public_refresh_cursor_ = 0;
    record_public_classes();
    for (const auto& r : records) active_[r.id] = r.value;

    Timer t;
    std::vector<Record> sorted_records = records;
    guide_.train(sorted_records, params_.guide_segments);
    bs.train_ms = t.ms();

    t.reset();
    auto chunks = certify_cells(sorted_records);
    bs.certify_ms = t.ms();

    t.reset();
    std::vector<std::uint32_t> lows(chunks.size(), 0), highs(chunks.size(), params_.universe - 1);
    for (std::size_t i = 0; i < chunks.size(); ++i) {
        if (!chunks[i].empty()) lows[i] = chunks[i].front().value;
    }
    for (std::size_t i = 0; i < chunks.size(); ++i) {
        if (i == 0) lows[i] = 0;
        if (i + 1 < chunks.size()) {
            std::uint32_t next_lo = chunks[i + 1].empty() ? params_.universe - 1 : chunks[i + 1].front().value;
            std::uint32_t this_hi = chunks[i].empty() ? next_lo : chunks[i].back().value;
            highs[i] = (next_lo > this_hi) ? (next_lo - 1) : this_hi;
        } else highs[i] = params_.universe - 1;
    }

    for (std::size_t i = 0; i < chunks.size(); ++i) {
        auto encoded = encode_cell(fresh_handle(), lows[i], highs[i], chunks[i]);
        install_cell(cells_.size(), std::move(encoded));
    }
    if (params_.enable_padding) ensure_pad_pool(static_cast<std::size_t>(params_.pad_pool_size));
    rebuild_locator();
    bs.encode_ms = t.ms();
    return bs;
}

LeakageCellTrace& LOCIIndex::leakage_cell(std::uint64_t handle) {
    auto& row = leakage_trace_[handle];
    row.handle = handle;
    return row;
}

void LOCIIndex::record_search_leakage(const ClientCell& cell, int log_count, std::size_t response_refs, std::uint64_t response_bytes) {
    auto& row = leakage_cell(cell.handle);
    row.search_touches++;
    row.visible_log_refs += static_cast<std::uint64_t>(std::max(0, log_count));
    row.max_visible_log_refs = std::max<std::uint64_t>(
        row.max_visible_log_refs,
        static_cast<std::uint64_t>(std::max(0, log_count)));
    row.response_refs += static_cast<std::uint64_t>(response_refs);
    row.response_bytes += response_bytes;
}

void LOCIIndex::record_update_leakage(const ClientCell& cell) {
    auto& row = leakage_cell(cell.handle);
    row.update_touches++;
    row.true_update_touches++;
}

void LOCIIndex::record_maintenance_leakage(std::uint64_t handle, MaintenanceCause cause) {
    auto& row = leakage_cell(handle);
    row.maintenance_events++;
    if (cause != MaintenanceCause::Scheduled) row.true_private_maintenance_events++;
    if (cause == MaintenanceCause::LogFull) row.true_log_full_events++;
}

void LOCIIndex::record_public_classes() {
    transcript_.cert_capacity_class = static_cast<std::uint64_t>(
        params_.enable_certification ? params_.lbc.B : 0);
    transcript_.cert_fanout_class = static_cast<std::uint64_t>(
        params_.enable_padding ? std::max(1, params_.public_fanout_base) : 0);
    transcript_.cert_log_class = static_cast<std::uint64_t>(params_.lbc.theta);
    transcript_.cert_maintenance_class = static_cast<std::uint64_t>(
        params_.enable_public_refresh ? params_.public_refresh_period : 0);
    transcript_.cert_split_load_class = static_cast<std::uint64_t>(
        params_.enable_certification ? load_threshold(params_.lbc.B, params_.split_load_percent) : 0);
    transcript_.cert_merge_load_class = static_cast<std::uint64_t>(
        params_.enable_certification ? load_threshold(params_.lbc.B, params_.merge_load_percent) : 0);
    transcript_.cert_desc_object_class = static_cast<std::uint64_t>(
        params_.enable_certification
            ? crypto_.sealed_size(serialize_descriptor(BoundaryDescriptor{}).size(), padding_.desc_pad())
            : 0);
    transcript_.cert_proto_object_class = static_cast<std::uint64_t>(
        params_.enable_certification
            ? crypto_.sealed_size(BitVec(static_cast<std::size_t>(params_.lbc.B)).serialize().size(), padding_.proto_pad())
            : 0);
    transcript_.cert_patch_object_class = static_cast<std::uint64_t>(
        crypto_.sealed_size(serialize_patch(Patch{}).size(), padding_.patch_pad()));
    transcript_.cert_full_object_class = static_cast<std::uint64_t>(
        params_.enable_certification
            ? crypto_.sealed_size(BitVec(static_cast<std::size_t>(params_.lbc.B)).serialize().size(), padding_.bitvec_pad(static_cast<std::size_t>(params_.lbc.B)))
            : 0);
}

std::size_t LOCIIndex::certified_fanout_class(std::size_t refs) const {
    if (!params_.enable_padding) return refs;
    return next_power_of_two(refs, std::max<std::size_t>(1, static_cast<std::size_t>(params_.public_fanout_base)));
}

void LOCIIndex::attach_certificate(ClientCell& cell) const {
    cell.cert.capacity_class = static_cast<std::uint64_t>(
        params_.enable_certification ? params_.lbc.B : cell.params.B);
    cell.cert.fanout_class = static_cast<std::uint64_t>(
        params_.enable_padding ? std::max(1, params_.public_fanout_base) : 0);
    cell.cert.log_class = static_cast<std::uint64_t>(params_.lbc.theta);
    cell.cert.maintenance_class = static_cast<std::uint64_t>(
        params_.enable_public_refresh ? params_.public_refresh_period : 0);
    cell.cert.split_load_class = static_cast<std::uint64_t>(
        params_.enable_certification ? load_threshold(params_.lbc.B, params_.split_load_percent) : 0);
    cell.cert.merge_load_class = static_cast<std::uint64_t>(
        params_.enable_certification ? load_threshold(params_.lbc.B, params_.merge_load_percent) : 0);
    cell.cert.desc_object_class = params_.enable_certification ? transcript_.cert_desc_object_class : 0;
    cell.cert.proto_object_class = params_.enable_certification ? transcript_.cert_proto_object_class : 0;
    cell.cert.patch_object_class = transcript_.cert_patch_object_class;
    cell.cert.full_object_class = params_.enable_certification ? transcript_.cert_full_object_class : 0;
}

LBCParams LOCIIndex::cell_lbc_params(std::size_t record_count) const {
    LBCParams p = params_.lbc;
    if (params_.enable_certification) return p;
    int capacity = 1;
    int needed = std::max(1, static_cast<int>(record_count) + 1);
    while (capacity < needed) capacity <<= 1;
    p.B = capacity;
    p.rho = std::min(std::max(1, p.rho), p.B);
    while (p.rho > 1 && (p.B % p.rho) != 0) --p.rho;
    p.kappa = p.B / p.rho;
    return p;
}

LBCEncoder LOCIIndex::encoder_for(const ClientCell& cell) const {
    return LBCEncoder(cell.params, crypto_, padding_);
}

EncodedCell LOCIIndex::encode_cell(std::uint64_t handle, std::uint32_t lo, std::uint32_t hi, std::vector<Record> records) const {
    auto local = cell_lbc_params(records.size());
    return LBCEncoder(local, crypto_, padding_).encode(handle, lo, hi, std::move(records));
}

void LOCIIndex::ensure_pad_pool(std::size_t min_tags) {
    if (!params_.enable_padding || min_tags == 0) return;
    std::size_t target = pad_tags_.empty()
        ? std::max<std::size_t>(min_tags, static_cast<std::size_t>(params_.pad_pool_size))
        : std::max<std::size_t>(min_tags, pad_tags_.size());
    target = next_power_of_two(target, 1);
    const std::uint64_t pad_handle = crypto_.prf(static_cast<std::uint64_t>(ObjectKind::Pad), 0x504144504f4f4cULL);
    while (pad_tags_.size() < target) {
        std::uint64_t tag = crypto_.tag(pad_handle, ObjectKind::Pad, static_cast<std::uint64_t>(pad_tags_.size()));
        auto obj = crypto_.seal(tag, Bytes{}, padding_.patch_pad());
        server_.put(pad_handle, obj);
        pad_tags_.push_back(tag);
    }
}

std::uint64_t LOCIIndex::next_pad_tag() {
    ensure_pad_pool(1);
    if (pad_tags_.empty()) throw std::runtime_error("padding requested without a pad pool");
    std::uint64_t tag = pad_tags_[pad_cursor_ % pad_tags_.size()];
    pad_cursor_ = (pad_cursor_ + 1) % pad_tags_.size();
    return tag;
}

void LOCIIndex::install_cell(std::size_t position, EncodedCell encoded) {
    attach_certificate(encoded.client);
    for (const auto& [handle, obj] : encoded.sealed_objects) server_.put(handle, obj);
    if (position >= cells_.size()) cells_.push_back(std::move(encoded.client));
    else cells_[position] = std::move(encoded.client);
}

void LOCIIndex::rebuild_locator() {
    transcript_.locator_rebuilds++;
    locator_.clear();
    for (int ci = 0; ci < static_cast<int>(cells_.size()); ++ci) {
        const auto& cell = cells_[ci];
        for (int s = 0; s < static_cast<int>(cell.slots.size()); ++s) {
            const auto& slot = cell.slots[static_cast<std::size_t>(s)];
            if (slot.state == SlotState::Active) locator_[slot.id] = CellLocation{ci, s, slot.value};
        }
    }
}

void LOCIIndex::retrain_guide() {
    transcript_.guide_retrains++;
    std::vector<Record> rec;
    rec.reserve(active_.size());
    for (const auto& [id, value] : active_) rec.push_back(Record{id, value});
    guide_.train(rec, params_.guide_segments);
}

void LOCIIndex::maybe_retrain_guide() {
    if (++updates_since_guide_ >= 256) {
        retrain_guide();
        updates_since_guide_ = 0;
    }
}

int LOCIIndex::hint_cell(std::uint32_t value) {
    transcript_.guide_locates++;
    if (cells_.empty()) return -1;
    int h = static_cast<int>(guide_.predict_rank(value) / std::max(1, params_.lbc.B));
    if (h < 0) h = 0;
    if (h >= static_cast<int>(cells_.size())) h = static_cast<int>(cells_.size()) - 1;
    return h;
}

int LOCIIndex::locate_cell(std::uint32_t value) {
    int i = hint_cell(value);
    if (i < 0) return -1;
    while (i > 0 && value < cells_[i].lo) { --i; transcript_.guide_corrections++; }
    while (i + 1 < static_cast<int>(cells_.size()) && value > cells_[i].hi) { ++i; transcript_.guide_corrections++; }
    return i;
}

int LOCIIndex::first_intersecting_cell(std::uint32_t L) {
    int i = locate_cell(L);
    if (i < 0) return -1;
    while (i > 0 && cells_[i - 1].hi >= L) { --i; transcript_.guide_corrections++; }
    while (i < static_cast<int>(cells_.size()) && cells_[i].hi < L) { ++i; transcript_.guide_corrections++; }
    return (i < static_cast<int>(cells_.size())) ? i : -1;
}

int LOCIIndex::last_intersecting_cell(std::uint32_t R) {
    int i = locate_cell(R);
    if (i < 0) return -1;
    while (i + 1 < static_cast<int>(cells_.size()) && cells_[i + 1].lo <= R) { ++i; transcript_.guide_corrections++; }
    while (i >= 0 && cells_[i].lo > R) { --i; transcript_.guide_corrections++; }
    return i;
}

int LOCIIndex::choose_cell_for_insert(std::uint32_t value) {
    int h = locate_cell(value);
    if (h < 0) return -1;
    int left = h, right = h;
    while (left > 0 && cells_[left - 1].contains(value)) --left;
    while (right + 1 < static_cast<int>(cells_.size()) && cells_[right + 1].contains(value)) ++right;
    int best = -1, best_load = 1 << 30;
    for (int i = left; i <= right; ++i) {
        if (cells_[i].contains(value) && cells_[i].free_slot() >= 0 && cells_[i].load() < best_load) {
            best = i; best_load = cells_[i].load();
        }
    }
    return best >= 0 ? best : h;
}

std::pair<int,int> LOCIIndex::boundary_indices(const ClientCell& cell, std::uint32_t L, std::uint32_t R) const {
    int j_left = static_cast<int>(std::lower_bound(cell.boundaries.begin(), cell.boundaries.end(), L) - cell.boundaries.begin());
    int j_right = static_cast<int>(std::upper_bound(cell.boundaries.begin(), cell.boundaries.end(), R) - cell.boundaries.begin());
    return {j_left, j_right}; // j_left is count <= predecessor, j_right is count <= R
}

void LOCIIndex::add_ref(QueryToken& token, std::uint64_t tag) const {
    token.refs.push_back(FetchRef{tag});
}

void LOCIIndex::fetch_boundary(QueryToken& token, const ClientCell& cell, int boundary_index) const {
    if (boundary_index <= 0) return;
    int j = boundary_index - 1;
    add_ref(token, cell.desc_tags[static_cast<std::size_t>(j)]);
    int pi = 0;
    if (j >= 0 && j < static_cast<int>(cell.boundary_prototype.size())) pi = cell.boundary_prototype[static_cast<std::size_t>(j)];
    add_ref(token, cell.proto_tags[static_cast<std::size_t>(pi)]);
}

void LOCIIndex::shuffle_token(QueryToken& token) {
    if (token.refs.size() < 2) return;
    std::uint64_t seed = crypto_.prf(0x544f4b5348554646ULL, nonce_++);
    std::mt19937_64 rng(seed);
    std::shuffle(token.refs.begin(), token.refs.end(), rng);
}

Plan LOCIIndex::token_gen(std::uint32_t L, std::uint32_t R) {
    if (L > R) std::swap(L, R);
    Plan plan;
    int left = first_intersecting_cell(L);
    int right = last_intersecting_cell(R);
    if (left < 0 || right < left) return plan;
    for (int ci = left; ci <= right; ++ci) {
        const auto& cell = cells_[ci];
        if (!cell.intersects(L, R)) continue;
        std::uint32_t local_L = std::max(L, cell.lo);
        std::uint32_t local_R = std::min(R, cell.hi);
        bool full = (local_L <= cell.lo && cell.hi <= local_R);
        ContextEntry ctx;
        ctx.cell_index = ci;
        ctx.handle = cell.handle;
        ctx.L = local_L;
        ctx.R = local_R;
        ctx.full = full;
        ctx.log_count = params_.expose_log_length ? cell.log_used : params_.lbc.theta;

        std::size_t before_cell_refs = plan.token.refs.size();
        for (int li = 0; li < ctx.log_count; ++li) {
            add_ref(plan.token, cell.log_tags[static_cast<std::size_t>(li)]);
        }
        transcript_.log_refs += static_cast<std::uint64_t>(ctx.log_count);
        transcript_.max_visible_log_refs_per_cell = std::max<std::uint64_t>(
            transcript_.max_visible_log_refs_per_cell,
            static_cast<std::uint64_t>(ctx.log_count));
        if (params_.expose_log_length) {
            transcript_.raw_log_length_exposures++;
        }
        if (full) {
            add_ref(plan.token, cell.full_tag);
        } else {
            auto [jl, jr] = boundary_indices(cell, local_L, local_R);
            ctx.j_left = jl; ctx.j_right = jr;
            fetch_boundary(plan.token, cell, jl);
            fetch_boundary(plan.token, cell, jr);
        }
        std::uint64_t cell_response_bytes = 0;
        for (std::size_t ri = before_cell_refs; ri < plan.token.refs.size(); ++ri) {
            cell_response_bytes += server_.fetch(plan.token.refs[ri].tag).padded_size;
        }
        record_search_leakage(cell, ctx.log_count, plan.token.refs.size() - before_cell_refs, cell_response_bytes);
        plan.context.entries.push_back(ctx);
    }
    if (params_.enable_padding) {
        std::size_t before = plan.token.refs.size();
        std::size_t target = certified_fanout_class(before);
        std::size_t pad_count = target - before;
        ensure_pad_pool(pad_count);
        for (std::size_t k = before; k < target; ++k) {
            add_ref(plan.token, next_pad_tag());
        }
        transcript_.token_padding_refs += pad_count;
        transcript_.max_fanout_class = std::max<std::uint64_t>(transcript_.max_fanout_class, target);
    } else {
        transcript_.max_fanout_class = std::max<std::uint64_t>(transcript_.max_fanout_class, plan.token.refs.size());
    }
    if (params_.expose_token_order) {
        transcript_.ordered_token_exposures++;
    } else {
        shuffle_token(plan.token);
    }
    transcript_.max_token_refs = std::max<std::uint64_t>(transcript_.max_token_refs, plan.token.refs.size());
    return plan;
}

QueryResponse LOCIIndex::server_fetch(const QueryToken& token) {
    transcript_.fetched_objects += token.refs.size();
    for (const auto& ref : token.refs) {
        transcript_.response_bytes += server_.fetch(ref.tag).padded_size;
    }
    auto ans = server_.fetch(token);
    return ans;
}

std::vector<int> LOCIIndex::decode(const QueryContext& context, const QueryResponse& response) {
    std::set<int> result;
    for (const auto& entry : context.entries) {
        const auto& cell = cells_[static_cast<std::size_t>(entry.cell_index)];
        auto local_lbc = encoder_for(cell);
        BitVec base(cell.params.B);
        if (entry.full) {
            base = BitVec::deserialize(crypto_.open(response.objects.at(cell.full_tag)));
        } else {
            auto right = local_lbc.recover_boundary(cell, entry.j_right, response);
            auto left = local_lbc.recover_boundary(cell, entry.j_left, response);
            base = right.andnot(left);
        }

        BitVec add(cell.params.B), del(cell.params.B);
        for (int li = 0; li < entry.log_count; ++li) {
            auto tag = cell.log_tags[static_cast<std::size_t>(li)];
            Patch p = local_lbc.open_patch(tag, response);
            if (p.op == PatchOp::Dummy) continue;
            if (p.value < entry.L || p.value > entry.R) continue;
            if (p.slot < 0 || p.slot >= cell.params.B) continue;
            if (p.op == PatchOp::Add) add.set(static_cast<std::size_t>(p.slot));
            if (p.op == PatchOp::Del) del.set(static_cast<std::size_t>(p.slot));
        }
        BitVec local = base.bor(add).andnot(del);
        for (auto slot_index : local.ones()) {
            const auto& slot = cell.slots[slot_index];
            if (slot.state == SlotState::Active && entry.L <= slot.value && slot.value <= entry.R) result.insert(slot.id);
        }
    }
    return std::vector<int>(result.begin(), result.end());
}

std::vector<int> LOCIIndex::search(std::uint32_t L, std::uint32_t R) {
    Timer timer;
    auto plan = token_gen(L, R);
    transcript_.searches++;
    transcript_.touched_cells += plan.context.entries.size();
    std::uint64_t object_bytes = 0;
    for (const auto& ref : plan.token.refs) object_bytes += server_.fetch(ref.tag).padded_size;
    auto response = server_fetch(plan.token);
    auto result = decode(plan.context, response);
    std::vector<std::uint64_t> handles;
    handles.reserve(plan.context.entries.size());
    std::uint64_t full_cells = 0;
    std::uint64_t boundary_cells = 0;
    for (const auto& entry : plan.context.entries) {
        handles.push_back(entry.handle);
        if (entry.full) ++full_cells;
        else ++boundary_cells;
    }
    trace_.searches.push_back(SearchTraceRow{
        trace_.tick(),
        trace_.qid(),
        join_handles(handles),
        static_cast<std::uint64_t>(plan.token.refs.size()),
        params_.enable_padding ? static_cast<std::uint64_t>(certified_fanout_class(plan.token.refs.size())) : static_cast<std::uint64_t>(plan.token.refs.size()),
        params_.enable_padding ? static_cast<std::uint64_t>(next_power_of_two(static_cast<std::size_t>(object_bytes), 1)) : object_bytes,
        object_bytes,
        params_.enable_padding ? static_cast<std::uint64_t>(next_power_of_two(result.size(), 1)) : static_cast<std::uint64_t>(result.size()),
        full_cells,
        boundary_cells,
        params_.expose_token_order ? 1 : 0,
        timer.ms()});
    return result;
}

std::size_t LOCIIndex::upload_encoded_cell(EncodedCell& encoded) {
    attach_certificate(encoded.client);
    std::size_t bytes = 0;
    for (const auto& [handle, obj] : encoded.sealed_objects) {
        server_.put(handle, obj);
        bytes += obj.padded_size;
    }
    return bytes;
}

void LOCIIndex::write_patch(int cell_index, const Patch& patch) {
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) throw std::runtime_error("write_patch: cell index out of range");
    if (cells_[static_cast<std::size_t>(cell_index)].log_used >= params_.lbc.theta) {
        refresh_cell(cell_index, MaintenanceCause::LogFull);
    }
    auto& cell = cells_[static_cast<std::size_t>(cell_index)];
    auto tag = cell.log_tags[static_cast<std::size_t>(cell.log_used)];
    auto obj = encoder_for(cell).seal_patch(tag, patch);
    server_.put(cell.handle, obj);
    cell.log_used++;
    transcript_.patch_bytes += obj.padded_size;
}

void LOCIIndex::ensure_log_capacity(int cell_index) {
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) return;
    if (cells_[static_cast<std::size_t>(cell_index)].log_used >= params_.lbc.theta) {
        refresh_cell(cell_index, MaintenanceCause::LogFull);
    }
}

void LOCIIndex::ensure_insert_capacity(int cell_index, std::uint32_t incoming_value) {
    if (cells_[static_cast<std::size_t>(cell_index)].free_slot() >= 0) return;
    refresh_cell(cell_index, MaintenanceCause::Manual);
    if (cells_[static_cast<std::size_t>(cell_index)].free_slot() >= 0) return;
    transcript_.forced_capacity_splits++;
    split_cell(cell_index, incoming_value);
}

void LOCIIndex::insert(int id, std::uint32_t value) {
    Timer timer;
    std::uint64_t patch_before = transcript_.patch_bytes;
    if (cells_.empty()) build({});
    if (active_.count(id)) throw std::runtime_error("insert duplicate id");
    int ci = choose_cell_for_insert(value);
    if (ci < 0) throw std::runtime_error("insert could not locate a target cell");
    ensure_insert_capacity(ci, value);
    ci = choose_cell_for_insert(value);
    if (ci < 0) throw std::runtime_error("insert could not locate a target cell after capacity check");
    ensure_log_capacity(ci);
    int slot = cells_[static_cast<std::size_t>(ci)].free_slot();
    if (slot < 0) throw std::runtime_error("no free slot after capacity check");
    Timer patch_timer;
    auto& cell = cells_[static_cast<std::size_t>(ci)];
    cell.slots[static_cast<std::size_t>(slot)] = Slot{SlotState::Active, id, value};
    active_[id] = value;
    locator_[id] = CellLocation{ci, slot, value};
    write_patch(ci, Patch{PatchOp::Add, id, value, slot});
    record_update_leakage(cells_[static_cast<std::size_t>(ci)]);
    transcript_.updates++;
    const auto& updated = cells_[static_cast<std::size_t>(ci)];
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "insert",
        handle_string(updated.handle),
        transcript_.cert_patch_object_class,
        transcript_.patch_bytes - patch_before,
        params_.expose_log_length ? std::to_string(updated.log_used) : "",
        timer.ms()});
    transcript_.patch_update_latency_ms_total += patch_timer.ms();
    advance_public_refresh_automaton();
    maybe_retrain_guide();
}

void LOCIIndex::erase(int id) {
    Timer timer;
    std::uint64_t patch_before = transcript_.patch_bytes;
    auto it = locator_.find(id);
    if (it == locator_.end()) throw std::runtime_error("erase missing id");
    auto loc = it->second;
    ensure_log_capacity(loc.cell);
    it = locator_.find(id);
    if (it == locator_.end()) throw std::runtime_error("erase missing id after refresh");
    loc = it->second;
    Timer patch_timer;
    auto& cell = cells_[static_cast<std::size_t>(loc.cell)];
    cell.slots[static_cast<std::size_t>(loc.slot)].state = SlotState::Retired;
    active_.erase(id);
    locator_.erase(it);
    write_patch(loc.cell, Patch{PatchOp::Del, id, loc.value, loc.slot});
    record_update_leakage(cells_[static_cast<std::size_t>(loc.cell)]);
    transcript_.updates++;
    const auto& updated = cells_[static_cast<std::size_t>(loc.cell)];
    trace_.updates.push_back(UpdateTraceRow{
        trace_.tick(),
        "erase",
        handle_string(updated.handle),
        transcript_.cert_patch_object_class,
        transcript_.patch_bytes - patch_before,
        params_.expose_log_length ? std::to_string(updated.log_used) : "",
        timer.ms()});
    transcript_.patch_update_latency_ms_total += patch_timer.ms();
    advance_public_refresh_automaton();
    maybe_retrain_guide();
}

void LOCIIndex::refresh(int cell_index) {
    refresh_cell(cell_index, MaintenanceCause::Manual);
}

void LOCIIndex::refresh_cell(int cell_index, MaintenanceCause cause) {
    Timer timer;
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) return;
    auto old = cells_[static_cast<std::size_t>(cell_index)];
    auto records = old.active_records();
    record_maintenance_leakage(old.handle, cause);
    server_.erase_cell(old.handle);
    auto encoded = encode_cell(old.handle, old.lo, old.hi, records);
    std::size_t bytes = upload_encoded_cell(encoded);
    cells_[static_cast<std::size_t>(cell_index)] = std::move(encoded.client);
    transcript_.refreshes++;
    transcript_.refresh_class_events++;
    if (cause == MaintenanceCause::Scheduled) transcript_.scheduled_refreshes++;
    if (cause == MaintenanceCause::LogFull) transcript_.forced_log_refreshes++;
    transcript_.refresh_bytes += bytes;
    std::string raw_trigger;
    if (!params_.enable_public_refresh) {
        raw_trigger = (cause == MaintenanceCause::LogFull) ? "log_full" :
                      (cause == MaintenanceCause::Scheduled ? "scheduled" : "manual");
    }
    std::string event_type = "refresh";
    if (!params_.enable_public_refresh) {
        event_type = cause == MaintenanceCause::Scheduled ? "refresh_scheduled" :
            (cause == MaintenanceCause::LogFull ? "refresh_log_full" : "refresh_manual");
    }
    rebuild_locator();
    double latency_ms = timer.ms();
    transcript_.refresh_latency_ms_total += latency_ms;
    transcript_.maintenance_latency_ms_total += latency_ms;
    trace_.maintenance.push_back(MaintenanceTraceRow{
        trace_.tick(),
        event_type,
        handle_string(old.handle),
        transcript_.cert_maintenance_class,
        raw_trigger,
        transcript_.cert_full_object_class,
        latency_ms});
}

static bool same_value(const std::vector<Record>& records) {
    if (records.empty()) return true;
    for (const auto& r : records) if (r.value != records.front().value) return false;
    return true;
}

void LOCIIndex::try_public_split(int cell_index) {
    if (!params_.enable_certification) return;
    if (cell_index < 0 || cell_index >= static_cast<int>(cells_.size())) return;
    const auto records = cells_[static_cast<std::size_t>(cell_index)].active_records();
    if (static_cast<int>(records.size()) < load_threshold(params_.lbc.B, params_.split_load_percent)) return;
    if (records.size() < 2 || same_value(records)) return;
    std::uint32_t pivot = records[records.size() / 2].value;
    auto before = transcript_.splits;
    split_cell(cell_index, pivot);
    if (transcript_.splits > before) transcript_.public_split_events++;
}

void LOCIIndex::advance_public_refresh_automaton() {
    if (!params_.enable_public_refresh || params_.public_refresh_period <= 0 || cells_.empty()) return;
    ++public_update_clock_;
    if (public_update_clock_ < params_.public_refresh_period) return;
    public_update_clock_ = 0;
    transcript_.public_refresh_ticks++;

    int ci = public_refresh_cursor_ % static_cast<int>(cells_.size());
    public_refresh_cursor_ = (public_refresh_cursor_ + 1) % std::max(1, static_cast<int>(cells_.size()));
    if (params_.public_refresh_always || cells_[static_cast<std::size_t>(ci)].log_used > 0) {
        refresh_cell(ci, MaintenanceCause::Scheduled);
    }
    if (ci < static_cast<int>(cells_.size())) try_public_split(ci);
    if (ci < static_cast<int>(cells_.size())) try_merge_around(ci, true);
}

void LOCIIndex::split_cell(int cell_index, std::uint32_t incoming_value) {
    Timer timer;
    auto old = cells_[static_cast<std::size_t>(cell_index)];
    auto records = old.active_records();
    std::sort(records.begin(), records.end(), record_less);
    if (records.empty()) return;

    if (same_value(records)) {
        std::uint32_t old_value = records.front().value;
        record_maintenance_leakage(old.handle, MaintenanceCause::Manual);
        server_.erase_cell(old.handle);
        if (incoming_value < old_value) {
            std::uint32_t new_hi = (old_value == 0) ? 0 : old_value - 1;
            auto new_cell = encode_cell(fresh_handle(), old.lo, new_hi, {});
            auto old_cell = encode_cell(old.handle, old_value, old.hi, records);
            std::size_t bytes = upload_encoded_cell(new_cell) + upload_encoded_cell(old_cell);
            cells_[static_cast<std::size_t>(cell_index)] = std::move(new_cell.client);
            cells_.insert(cells_.begin() + cell_index + 1, std::move(old_cell.client));
            transcript_.refresh_bytes += bytes;
        } else if (incoming_value > old_value) {
            std::uint32_t old_hi = old_value;
            std::uint32_t new_lo = (old_value == std::numeric_limits<std::uint32_t>::max()) ? old_value : old_value + 1;
            auto old_cell = encode_cell(old.handle, old.lo, old_hi, records);
            auto new_cell = encode_cell(fresh_handle(), new_lo, old.hi, {});
            std::size_t bytes = upload_encoded_cell(old_cell) + upload_encoded_cell(new_cell);
            cells_[static_cast<std::size_t>(cell_index)] = std::move(old_cell.client);
            cells_.insert(cells_.begin() + cell_index + 1, std::move(new_cell.client));
            transcript_.refresh_bytes += bytes;
        } else {
            auto old_cell = encode_cell(old.handle, old.lo, old.hi, records);
            auto overflow = encode_cell(fresh_handle(), incoming_value, incoming_value, {});
            std::size_t bytes = upload_encoded_cell(old_cell) + upload_encoded_cell(overflow);
            cells_[static_cast<std::size_t>(cell_index)] = std::move(old_cell.client);
            cells_.insert(cells_.begin() + cell_index + 1, std::move(overflow.client));
            transcript_.refresh_bytes += bytes;
        }
        transcript_.splits++;
        transcript_.split_class_events++;
        rebuild_locator();
        retrain_guide();
        double latency_ms = timer.ms();
        transcript_.maintenance_latency_ms_total += latency_ms;
        trace_.maintenance.push_back(MaintenanceTraceRow{
            trace_.tick(),
            "split",
            handle_string(old.handle),
            transcript_.cert_split_load_class,
            params_.enable_public_refresh ? "" : "capacity",
            transcript_.cert_full_object_class,
            latency_ms});
        return;
    }

    std::size_t mid = records.size() / 2;
    while (mid < records.size() && records[mid - 1].value == records[mid].value) ++mid;
    if (mid >= records.size()) {
        mid = records.size() / 2;
        while (mid > 0 && records[mid - 1].value == records[mid].value) --mid;
    }
    if (mid == 0 || mid >= records.size()) mid = records.size() / 2;

    std::vector<Record> left(records.begin(), records.begin() + static_cast<long>(mid));
    std::vector<Record> right(records.begin() + static_cast<long>(mid), records.end());
    std::uint32_t left_hi = (right.front().value > left.back().value) ? (right.front().value - 1) : left.back().value;
    std::uint32_t right_lo = right.front().value;

    server_.erase_cell(old.handle);
    record_maintenance_leakage(old.handle, MaintenanceCause::Manual);
    auto L = encode_cell(old.handle, old.lo, left_hi, left);
    auto R = encode_cell(fresh_handle(), right_lo, old.hi, right);
    std::size_t bytes = upload_encoded_cell(L) + upload_encoded_cell(R);
    cells_[static_cast<std::size_t>(cell_index)] = std::move(L.client);
    cells_.insert(cells_.begin() + cell_index + 1, std::move(R.client));
    transcript_.splits++;
    transcript_.split_class_events++;
    transcript_.refresh_bytes += bytes;
    rebuild_locator();
    retrain_guide();
    double latency_ms = timer.ms();
    transcript_.maintenance_latency_ms_total += latency_ms;
    trace_.maintenance.push_back(MaintenanceTraceRow{
        trace_.tick(),
        "split",
        handle_string(old.handle),
        transcript_.cert_split_load_class,
        params_.enable_public_refresh ? "" : "capacity",
        transcript_.cert_full_object_class,
        latency_ms});
}

void LOCIIndex::try_merge_around(int cell_index, bool public_tick) {
    if (!params_.enable_certification) return;
    if (cells_.size() < 2) return;
    int start = std::max(0, cell_index - 1);
    int end = std::min(static_cast<int>(cells_.size()) - 2, cell_index + 1);
    for (int i = start; i <= end; ++i) {
        int load = cells_[static_cast<std::size_t>(i)].load() + cells_[static_cast<std::size_t>(i + 1)].load();
        if (load > load_threshold(params_.lbc.B, params_.merge_load_percent)) continue;
        auto rec = cells_[static_cast<std::size_t>(i)].active_records();
        auto rec2 = cells_[static_cast<std::size_t>(i + 1)].active_records();
        rec.insert(rec.end(), rec2.begin(), rec2.end());
        auto h = cells_[static_cast<std::size_t>(i)].handle;
        auto drop = cells_[static_cast<std::size_t>(i + 1)].handle;
        Timer timer;
        auto lo = std::min(cells_[static_cast<std::size_t>(i)].lo, cells_[static_cast<std::size_t>(i + 1)].lo);
        auto hi = std::max(cells_[static_cast<std::size_t>(i)].hi, cells_[static_cast<std::size_t>(i + 1)].hi);
        server_.erase_cell(h);
        server_.erase_cell(drop);
        record_maintenance_leakage(h, MaintenanceCause::Manual);
        record_maintenance_leakage(drop, MaintenanceCause::Manual);
        auto encoded = encode_cell(h, lo, hi, rec);
        std::size_t bytes = upload_encoded_cell(encoded);
        cells_[static_cast<std::size_t>(i)] = std::move(encoded.client);
        cells_.erase(cells_.begin() + i + 1);
        transcript_.merges++;
        transcript_.merge_class_events++;
        if (public_tick) transcript_.public_merge_events++;
        transcript_.refresh_bytes += bytes;
        rebuild_locator();
        retrain_guide();
        double latency_ms = timer.ms();
        transcript_.maintenance_latency_ms_total += latency_ms;
        trace_.maintenance.push_back(MaintenanceTraceRow{
            trace_.tick(),
            "merge",
            join_handles(std::vector<std::uint64_t>{h, drop}),
            transcript_.cert_merge_load_class,
            public_tick ? "" : "load",
            transcript_.cert_full_object_class,
            latency_ms});
        return;
    }
}

void LOCIIndex::rebuild_all_from_active() {
    std::vector<Record> records;
    for (const auto& [id, value] : active_) records.push_back(Record{id, value});
    build(records);
}

std::vector<int> LOCIIndex::plaintext_search(std::uint32_t L, std::uint32_t R) const {
    if (L > R) std::swap(L, R);
    std::vector<int> out;
    for (const auto& [id, value] : active_) if (L <= value && value <= R) out.push_back(id);
    std::sort(out.begin(), out.end());
    return out;
}

void LOCIIndex::check_correctness(std::mt19937& rng, int trials) {
    std::uniform_int_distribution<std::uint32_t> dist(0, params_.universe - 1);
    for (int i = 0; i < trials; ++i) {
        auto L = dist(rng), R = dist(rng);
        if (L > R) std::swap(L, R);
        auto got = search(L, R);
        auto exp = plaintext_search(L, R);
        if (got != exp) {
            std::cerr << "Correctness failure for [" << L << "," << R << "] got=" << got.size() << " exp=" << exp.size() << "\n";
            throw std::runtime_error("LOCI correctness check failed");
        }
    }
}

void LOCIIndex::print_summary(std::ostream& os) const {
    std::size_t desc = 0, proto = 0, logs = 0, max_load = 0;
    for (const auto& c : cells_) {
        desc += c.desc_tags.size();
        proto += c.proto_tags.size();
        logs += static_cast<std::size_t>(c.log_used);
        max_load = std::max(max_load, static_cast<std::size_t>(c.load()));
    }
    auto stats = lbc_storage_stats();
    double avg_repair = stats.boundary_count
        ? static_cast<double>(stats.repair_entries) / static_cast<double>(stats.boundary_count)
        : 0.0;
    double compression = stats.sealed_bytes()
        ? static_cast<double>(stats.raw_bitmap_bytes) / static_cast<double>(stats.sealed_bytes())
        : 0.0;
    os << "cells=" << cells_.size()
       << " active=" << active_.size()
       << " desc_slots=" << desc
       << " proto_slots=" << proto
       << " log_used=" << logs
       << " max_load=" << max_load
       << " server_objects=" << server_.object_count()
       << " server_bytes=" << server_.byte_size()
       << " guide_segments=" << guide_.segment_count()
       << " lbc_repair_entries=" << stats.repair_entries
       << " lbc_avg_repair=" << std::fixed << std::setprecision(3) << avg_repair
       << " lbc_desc_bytes=" << stats.desc_sealed_bytes
       << " lbc_proto_bytes=" << stats.proto_sealed_bytes
       << " lbc_full_bytes=" << stats.full_sealed_bytes
       << " lbc_log_bytes=" << stats.log_sealed_bytes
       << " lbc_raw_bitmap_bytes=" << stats.raw_bitmap_bytes
       << " lbc_compression_ratio=" << compression << '\n';
}

LBCStorageStats LOCIIndex::lbc_storage_stats() const {
    LBCStorageStats stats;
    for (const auto& cell : cells_) stats.add(cell.stats);
    return stats;
}

LeakageEvalResult LOCIIndex::evaluate_leakage(std::size_t top_k) const {
    std::vector<LeakageCellTrace> rows;
    rows.reserve(cells_.size());
    for (const auto& cell : cells_) {
        LeakageCellTrace row;
        auto it = leakage_trace_.find(cell.handle);
        if (it != leakage_trace_.end()) row = it->second;
        row.handle = cell.handle;
        row.true_load = static_cast<std::uint64_t>(cell.load());
        row.true_log_used = static_cast<std::uint64_t>(std::max(0, cell.log_used));
        rows.push_back(row);
    }
    return evaluate_leakage_trace(std::move(rows), top_k);
}

void LOCIIndex::reset_measurements() {
    transcript_ = TranscriptStats{};
    trace_.clear();
    leakage_trace_.clear();
    record_public_classes();
}

void LOCIIndex::write_trace(const std::string& dir, const std::string& scheme, const std::string& dataset) const {
    std::vector<LayoutUnitRow> layout;
    layout.reserve(cells_.size());
    for (const auto& cell : cells_) {
        std::set<std::uint32_t> distinct;
        for (const auto& rec : cell.active_records()) distinct.insert(rec.value);
        std::uint64_t updates = 0;
        std::uint64_t private_maintenance = 0;
        std::uint64_t private_log_full = 0;
        auto it = leakage_trace_.find(cell.handle);
        if (it != leakage_trace_.end()) {
            updates = it->second.true_update_touches;
            private_maintenance = it->second.true_private_maintenance_events;
            private_log_full = it->second.true_log_full_events;
        }
        const std::uint64_t true_load = static_cast<std::uint64_t>(cell.load());
        const std::uint64_t true_log_used = static_cast<std::uint64_t>(std::max(0, cell.log_used));
        layout.push_back(LayoutUnitRow{
            handle_string(cell.handle),
            cell.cert.capacity_class,
            load_label(true_load, std::max<std::uint64_t>(1, cell.cert.capacity_class)),
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

} // namespace loci
