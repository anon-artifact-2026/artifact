#include "loci/lbc.hpp"

namespace loci {

int ClientCell::load() const {
    int n = 0;
    for (const auto& s : slots) if (s.state == SlotState::Active) ++n;
    return n;
}

int ClientCell::free_slot() const {
    for (int i = 0; i < static_cast<int>(slots.size()); ++i) {
        if (slots[static_cast<std::size_t>(i)].state == SlotState::Free) return i;
    }
    return -1;
}

std::vector<Record> ClientCell::active_records() const {
    std::vector<Record> out;
    for (const auto& s : slots) if (s.state == SlotState::Active) out.push_back(Record{s.id, s.value});
    std::sort(out.begin(), out.end(), record_less);
    return out;
}

int LBCEncoder::slot_for_rank(int rank) const {
    if (rank < 0 || rank >= params_.B) throw std::runtime_error("slot rank out of range");
    int row = rank / params_.kappa;
    int col = rank % params_.kappa;
    if (params_.kappa <= 1) return rank;

    // Keep rows in value order but permute the frontier inside each row.
    // This makes LBC residuals non-trivial while preserving locality.
    int stride = params_.kappa - 1;
    int shift = row % params_.kappa;
    int permuted_col = (col * stride + shift) % params_.kappa;
    return row * params_.kappa + permuted_col;
}

Bytes serialize_descriptor(const BoundaryDescriptor& d) {
    ByteWriter w;
    w.i32(d.eta);
    w.i32(d.xi);
    w.i32(d.prototype);
    w.vec_u32(d.repair_positions);
    return w.data;
}

BoundaryDescriptor deserialize_descriptor(const Bytes& bytes) {
    ByteReader r(bytes);
    BoundaryDescriptor d;
    d.eta = r.i32();
    d.xi = r.i32();
    d.prototype = r.i32();
    d.repair_positions = r.vec_u32();
    return d;
}

Bytes serialize_patch(const Patch& p) {
    ByteWriter w;
    w.u8(static_cast<std::uint8_t>(p.op));
    w.i32(p.id);
    w.u32(p.value);
    w.i32(p.slot);
    return w.data;
}

Patch deserialize_patch(const Bytes& bytes) {
    ByteReader r(bytes);
    Patch p;
    p.op = static_cast<PatchOp>(r.u8());
    p.id = r.i32();
    p.value = r.u32();
    p.slot = r.i32();
    return p;
}

std::vector<BitVec> LBCEncoder::accumulated_bitmaps(const ClientCell& cell) const {
    std::vector<BitVec> bitmaps;
    bitmaps.reserve(cell.boundaries.size());
    for (auto boundary : cell.boundaries) {
        BitVec bv(params_.B);
        for (int s = 0; s < static_cast<int>(cell.slots.size()); ++s) {
            const auto& slot = cell.slots[static_cast<std::size_t>(s)];
            if (slot.state == SlotState::Active && slot.value <= boundary) bv.set(static_cast<std::size_t>(s));
        }
        bitmaps.push_back(std::move(bv));
    }
    return bitmaps;
}

std::vector<BitVec> LBCEncoder::choose_prototypes(const std::vector<BitVec>& residuals) const {
    std::vector<BitVec> prototypes;
    prototypes.emplace_back(params_.B); // zero prototype
    if (residuals.empty()) {
        while (static_cast<int>(prototypes.size()) < params_.max_prototypes) prototypes.emplace_back(params_.B);
        return prototypes;
    }
    std::vector<int> chosen(residuals.size(), 0);
    while (static_cast<int>(prototypes.size()) < params_.max_prototypes) {
        std::size_t best_i = residuals.size();
        std::size_t best_gain = 0;
        for (std::size_t i = 0; i < residuals.size(); ++i) {
            std::size_t d0 = residuals[i].weight();
            std::size_t closest = d0;
            for (const auto& z : prototypes) closest = std::min(closest, residuals[i].bxor(z).weight());
            if (closest > best_gain) { best_gain = closest; best_i = i; }
        }
        if (best_i == residuals.size() || best_gain <= 2) break;
        prototypes.push_back(residuals[best_i]);
    }
    while (static_cast<int>(prototypes.size()) < params_.max_prototypes) prototypes.emplace_back(params_.B);
    return prototypes;
}

BoundaryDescriptor LBCEncoder::make_descriptor(const MatrixBitmap& residual, const std::vector<BitVec>& prototypes) const {
    BoundaryDescriptor best;
    std::size_t best_w = static_cast<std::size_t>(-1);
    for (int pi = 0; pi < static_cast<int>(prototypes.size()); ++pi) {
        BitVec repair = residual.flatten().bxor(prototypes[static_cast<std::size_t>(pi)]);
        std::size_t w = repair.weight();
        if (w < best_w) {
            best_w = w;
            best.prototype = pi;
            best.repair_positions = repair.ones();
        }
    }
    return best;
}

EncodedCell LBCEncoder::encode(std::uint64_t handle, std::uint32_t lo, std::uint32_t hi, std::vector<Record> records) const {
    if (static_cast<int>(records.size()) > params_.B) throw std::runtime_error("LBCEncoder::encode: cell overflow");
    std::sort(records.begin(), records.end(), record_less);

    ClientCell cell;
    cell.handle = handle;
    cell.lo = lo;
    cell.hi = hi;
    cell.params = params_;
    cell.slots.assign(static_cast<std::size_t>(params_.B), Slot{});
    cell.desc_tags.resize(static_cast<std::size_t>(params_.B));
    cell.log_tags.resize(static_cast<std::size_t>(params_.theta));
    cell.full_tag = crypto_.tag(handle, ObjectKind::Full, 0);

    for (int i = 0; i < static_cast<int>(records.size()); ++i) {
        int slot = slot_for_rank(i);
        cell.slots[static_cast<std::size_t>(slot)] = Slot{SlotState::Active, records[static_cast<std::size_t>(i)].id, records[static_cast<std::size_t>(i)].value};
        if (cell.boundaries.empty() || cell.boundaries.back() != records[static_cast<std::size_t>(i)].value) {
            cell.boundaries.push_back(records[static_cast<std::size_t>(i)].value);
        }
    }

    auto acc = accumulated_bitmaps(cell);
    std::vector<BitVec> residuals;
    residuals.reserve(acc.size());
    std::vector<PrefixCoordinates> coords;
    coords.reserve(acc.size());

    for (const auto& bv : acc) {
        int prefix_count = static_cast<int>(bv.weight());
        auto coord = MatrixBitmap::coordinates(prefix_count, shape_);
        coords.push_back(coord);
        auto M = MatrixBitmap::from_bitmap(bv, shape_);
        auto P = MatrixBitmap::prefix_template(shape_, coord);
        residuals.push_back(M.bxor(P).flatten());
    }

    bool direct_accumulated = params_.max_prototypes <= 1;
    auto prototypes = direct_accumulated ? acc : choose_prototypes(residuals);
    if (prototypes.empty()) prototypes.emplace_back(params_.B);
    cell.proto_tags.resize(prototypes.size());
    for (int pi = 0; pi < static_cast<int>(prototypes.size()); ++pi) {
        cell.proto_tags[static_cast<std::size_t>(pi)] = crypto_.tag(handle, ObjectKind::Proto, static_cast<std::uint64_t>(pi));
    }

    EncodedCell out;
    out.client = cell;
    out.client.stats.boundary_count = static_cast<std::uint64_t>(out.client.boundaries.size());
    out.client.stats.prototype_count = static_cast<std::uint64_t>(prototypes.size());
    out.client.stats.raw_bitmap_bytes = static_cast<std::uint64_t>(acc.size() * BitVec(static_cast<std::size_t>(params_.B)).serialize().size());

    for (int pi = 0; pi < static_cast<int>(prototypes.size()); ++pi) {
        auto tag = out.client.proto_tags[static_cast<std::size_t>(pi)];
        auto plain = prototypes[static_cast<std::size_t>(pi)].serialize();
        auto sealed = crypto_.seal(tag, plain, padding_.proto_pad());
        out.client.stats.proto_plain_bytes += plain.size();
        out.client.stats.proto_sealed_bytes += sealed.padded_size;
        out.sealed_objects.push_back({handle, std::move(sealed)});
    }

    auto full_plain = (acc.empty() ? BitVec(params_.B) : acc.back()).serialize();
    auto full_sealed = crypto_.seal(out.client.full_tag, full_plain, padding_.bitvec_pad(params_.B));
    out.client.stats.full_plain_bytes += full_plain.size();
    out.client.stats.full_sealed_bytes += full_sealed.padded_size;
    out.sealed_objects.push_back({handle, std::move(full_sealed)});

    out.client.boundary_prototype.assign(out.client.boundaries.size(), 0);
    for (int j = 0; j < params_.B; ++j) {
        auto tag = crypto_.tag(handle, ObjectKind::Desc, static_cast<std::uint64_t>(j + 1));
        out.client.desc_tags[static_cast<std::size_t>(j)] = tag;
        BoundaryDescriptor desc;
        if (j < static_cast<int>(residuals.size())) {
            if (direct_accumulated) {
                desc.eta = -1;
                desc.xi = 0;
                desc.prototype = j;
            } else {
                auto residual_matrix = MatrixBitmap::from_bitmap(residuals[static_cast<std::size_t>(j)], shape_);
                desc = make_descriptor(residual_matrix, prototypes);
                desc.eta = coords[static_cast<std::size_t>(j)].eta;
                desc.xi = coords[static_cast<std::size_t>(j)].xi;
            }
            out.client.boundary_prototype[static_cast<std::size_t>(j)] = desc.prototype;
        }
        auto plain = serialize_descriptor(desc);
        auto sealed = crypto_.seal(tag, plain, padding_.desc_pad());
        out.client.stats.repair_entries += desc.repair_positions.size();
        out.client.stats.desc_plain_bytes += plain.size();
        out.client.stats.desc_sealed_bytes += sealed.padded_size;
        out.sealed_objects.push_back({handle, std::move(sealed)});
    }

    for (int i = 0; i < params_.theta; ++i) {
        auto tag = crypto_.tag(handle, ObjectKind::Log, static_cast<std::uint64_t>(i));
        out.client.log_tags[static_cast<std::size_t>(i)] = tag;
        auto sealed = seal_patch(tag, Patch{});
        out.client.stats.log_sealed_bytes += sealed.padded_size;
        out.sealed_objects.push_back({handle, std::move(sealed)});
    }

    return out;
}

BitVec LBCEncoder::recover_boundary(const ClientCell& cell, int boundary_index, const QueryResponse& response) const {
    if (boundary_index <= 0) return BitVec(params_.B);
    if (boundary_index > static_cast<int>(cell.boundaries.size())) throw std::runtime_error("boundary out of range");
    int j = boundary_index - 1;
    auto desc_tag = cell.desc_tags[static_cast<std::size_t>(j)];
    auto desc = deserialize_descriptor(crypto_.open(response.objects.at(desc_tag)));
    if (desc.prototype < 0 || desc.prototype >= static_cast<int>(cell.proto_tags.size())) throw std::runtime_error("bad prototype index");
    auto proto_tag = cell.proto_tags[static_cast<std::size_t>(desc.prototype)];
    auto proto = BitVec::deserialize(crypto_.open(response.objects.at(proto_tag)));
    if (desc.eta < 0) return proto;
    auto P = MatrixBitmap::prefix_template(shape_, PrefixCoordinates{desc.eta, desc.xi}).flatten();
    auto E = BitVec::sparse(params_.B, desc.repair_positions);
    return P.bxor(proto).bxor(E);
}

Patch LBCEncoder::open_patch(std::uint64_t tag, const QueryResponse& response) const {
    return deserialize_patch(crypto_.open(response.objects.at(tag)));
}

SealedObject LBCEncoder::seal_patch(std::uint64_t tag, const Patch& patch) const {
    return crypto_.seal(tag, serialize_patch(patch), padding_.patch_pad());
}

} // namespace loci
