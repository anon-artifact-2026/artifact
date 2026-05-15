#pragma once
#include "loci/bitvec.hpp"

namespace loci {

struct MatrixShape {
    int rho = 0;
    int kappa = 0;
    int slots = 0;
    MatrixShape() = default;
    MatrixShape(int r, int k) : rho(r), kappa(k), slots(r * k) {
        if (r <= 0 || k <= 0) throw std::runtime_error("invalid matrix shape");
    }
};

struct PrefixCoordinates {
    int eta = 0;
    int xi = 0;
};

class MatrixBitmap {
    MatrixShape shape_;
    BitVec bits_;
public:
    MatrixBitmap() = default;
    explicit MatrixBitmap(MatrixShape s) : shape_(s), bits_(s.slots) {}
    MatrixBitmap(MatrixShape s, BitVec bits) : shape_(s), bits_(std::move(bits)) {
        if (static_cast<int>(bits_.size()) != s.slots) throw std::runtime_error("matrix/bitvec size mismatch");
    }

    const BitVec& bits() const { return bits_; }
    BitVec flatten() const { return bits_; }
    MatrixShape shape() const { return shape_; }

    MatrixBitmap bxor(const MatrixBitmap& other) const {
        return MatrixBitmap(shape_, bits_.bxor(other.bits_));
    }

    static PrefixCoordinates coordinates(int prefix_count, const MatrixShape& shape) {
        if (prefix_count < 0) prefix_count = 0;
        if (prefix_count > shape.slots) prefix_count = shape.slots;
        return PrefixCoordinates{prefix_count / shape.kappa, prefix_count % shape.kappa};
    }

    static MatrixBitmap from_bitmap(const BitVec& bv, const MatrixShape& shape) {
        return MatrixBitmap(shape, bv);
    }

    static MatrixBitmap prefix_template(const MatrixShape& shape, PrefixCoordinates c) {
        return MatrixBitmap(shape, BitVec::prefix(shape.slots, c.eta * shape.kappa + c.xi));
    }
};

} // namespace loci
