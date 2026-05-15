#pragma once
#include "loci/matrix_bitmap.hpp"
#include "loci/crypto.hpp"
#include "loci/server_edb.hpp"

namespace loci {

enum class SlotState : std::uint8_t { Free = 0, Active = 1, Retired = 2 };

struct Slot {
    SlotState state = SlotState::Free;
    int id = -1;
    std::uint32_t value = 0;
};

enum class PatchOp : std::uint8_t { Dummy = 0, Add = 1, Del = 2 };

struct Patch {
    PatchOp op = PatchOp::Dummy;
    int id = -1;
    std::uint32_t value = 0;
    int slot = -1;
};

struct BoundaryDescriptor {
    int eta = 0;
    int xi = 0;
    int prototype = 0;
    std::vector<std::uint32_t> repair_positions;
};

struct LBCParams {
    int B = 512;
    int rho = 32;
    int kappa = 16;
    int theta = 32;
    int max_prototypes = 8;
};

struct LBCStorageStats {
    std::uint64_t boundary_count = 0;
    std::uint64_t prototype_count = 0;
    std::uint64_t repair_entries = 0;
    std::uint64_t desc_plain_bytes = 0;
    std::uint64_t proto_plain_bytes = 0;
    std::uint64_t full_plain_bytes = 0;
    std::uint64_t desc_sealed_bytes = 0;
    std::uint64_t proto_sealed_bytes = 0;
    std::uint64_t full_sealed_bytes = 0;
    std::uint64_t log_sealed_bytes = 0;
    std::uint64_t raw_bitmap_bytes = 0;

    void add(const LBCStorageStats& other) {
        boundary_count += other.boundary_count;
        prototype_count += other.prototype_count;
        repair_entries += other.repair_entries;
        desc_plain_bytes += other.desc_plain_bytes;
        proto_plain_bytes += other.proto_plain_bytes;
        full_plain_bytes += other.full_plain_bytes;
        desc_sealed_bytes += other.desc_sealed_bytes;
        proto_sealed_bytes += other.proto_sealed_bytes;
        full_sealed_bytes += other.full_sealed_bytes;
        log_sealed_bytes += other.log_sealed_bytes;
        raw_bitmap_bytes += other.raw_bitmap_bytes;
    }

    std::uint64_t sealed_bytes() const {
        return desc_sealed_bytes + proto_sealed_bytes + full_sealed_bytes + log_sealed_bytes;
    }
};

struct CertifiedCellClass {
    std::uint64_t capacity_class = 0;
    std::uint64_t fanout_class = 0;
    std::uint64_t log_class = 0;
    std::uint64_t maintenance_class = 0;
    std::uint64_t split_load_class = 0;
    std::uint64_t merge_load_class = 0;
    std::uint64_t desc_object_class = 0;
    std::uint64_t proto_object_class = 0;
    std::uint64_t patch_object_class = 0;
    std::uint64_t full_object_class = 0;
};

struct ClientCell {
    std::uint64_t handle = 0;
    std::uint32_t lo = 0;
    std::uint32_t hi = 0;
    LBCParams params;
    CertifiedCellClass cert;
    std::vector<Slot> slots;
    std::vector<std::uint32_t> boundaries;
    std::vector<int> boundary_prototype;
    std::vector<std::uint64_t> desc_tags;
    std::vector<std::uint64_t> proto_tags;
    std::uint64_t full_tag = 0;
    std::vector<std::uint64_t> log_tags;
    int log_used = 0;
    LBCStorageStats stats;

    bool intersects(std::uint32_t L, std::uint32_t R) const { return !(R < lo || hi < L); }
    bool contains(std::uint32_t v) const { return lo <= v && v <= hi; }
    int load() const;
    int free_slot() const;
    std::vector<Record> active_records() const;
};

struct EncodedCell {
    ClientCell client;
    std::vector<std::pair<std::uint64_t, SealedObject>> sealed_objects;
};

Bytes serialize_descriptor(const BoundaryDescriptor& d);
BoundaryDescriptor deserialize_descriptor(const Bytes& bytes);
Bytes serialize_patch(const Patch& p);
Patch deserialize_patch(const Bytes& bytes);

class LBCEncoder {
    LBCParams params_;
    MatrixShape shape_;
    const MockCrypto& crypto_;
    PaddingPolicy padding_;
public:
    LBCEncoder(LBCParams params, const MockCrypto& crypto, PaddingPolicy padding = {})
        : params_(params), shape_(params.rho, params.kappa), crypto_(crypto), padding_(padding) {
        if (params_.rho * params_.kappa != params_.B) throw std::runtime_error("LBC params: rho*kappa must equal B");
    }

    const LBCParams& params() const { return params_; }
    const PaddingPolicy& padding() const { return padding_; }

    EncodedCell encode(std::uint64_t handle, std::uint32_t lo, std::uint32_t hi, std::vector<Record> records) const;
    BitVec recover_boundary(const ClientCell& cell, int boundary_index, const QueryResponse& response) const;
    Patch open_patch(std::uint64_t tag, const QueryResponse& response) const;
    SealedObject seal_patch(std::uint64_t tag, const Patch& patch) const;

private:
    int slot_for_rank(int rank) const;
    std::vector<BitVec> accumulated_bitmaps(const ClientCell& cell) const;
    BoundaryDescriptor make_descriptor(const MatrixBitmap& residual, const std::vector<BitVec>& prototypes) const;
    std::vector<BitVec> choose_prototypes(const std::vector<BitVec>& residuals) const;
};

} // namespace loci
