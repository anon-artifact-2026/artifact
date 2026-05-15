#pragma once
#include "loci/common.hpp"

namespace loci {

class BitVec {
    std::size_t n_ = 0;
    std::vector<std::uint64_t> words_;
public:
    BitVec() = default;
    explicit BitVec(std::size_t n) : n_(n), words_((n + 63) / 64, 0) {}
    BitVec(std::size_t n, std::vector<std::uint64_t> words) : n_(n), words_(std::move(words)) { trim(); }

    std::size_t size() const { return n_; }
    std::size_t word_count() const { return words_.size(); }
    std::size_t bytes() const { return words_.size() * sizeof(std::uint64_t); }
    const std::vector<std::uint64_t>& words() const { return words_; }

    void trim() {
        if (words_.empty()) return;
        std::size_t r = n_ & 63;
        if (r != 0) words_.back() &= ((1ULL << r) - 1ULL);
    }

    void set(std::size_t i, bool value = true) {
        if (i >= n_) throw std::out_of_range("BitVec::set");
        auto mask = 1ULL << (i & 63);
        if (value) words_[i >> 6] |= mask;
        else words_[i >> 6] &= ~mask;
    }

    bool get(std::size_t i) const {
        if (i >= n_) throw std::out_of_range("BitVec::get");
        return ((words_[i >> 6] >> (i & 63)) & 1ULL) != 0;
    }

    std::size_t weight() const {
        std::size_t s = 0;
        for (auto w : words_) s += static_cast<std::size_t>(__builtin_popcountll(w));
        return s;
    }

    BitVec bxor(const BitVec& other) const {
        check_same(other);
        BitVec out(n_);
        for (std::size_t i = 0; i < words_.size(); ++i) out.words_[i] = words_[i] ^ other.words_[i];
        out.trim();
        return out;
    }

    BitVec bor(const BitVec& other) const {
        check_same(other);
        BitVec out(n_);
        for (std::size_t i = 0; i < words_.size(); ++i) out.words_[i] = words_[i] | other.words_[i];
        out.trim();
        return out;
    }

    BitVec band(const BitVec& other) const {
        check_same(other);
        BitVec out(n_);
        for (std::size_t i = 0; i < words_.size(); ++i) out.words_[i] = words_[i] & other.words_[i];
        out.trim();
        return out;
    }

    BitVec andnot(const BitVec& other) const {
        check_same(other);
        BitVec out(n_);
        for (std::size_t i = 0; i < words_.size(); ++i) out.words_[i] = words_[i] & ~other.words_[i];
        out.trim();
        return out;
    }

    std::vector<std::uint32_t> ones() const {
        std::vector<std::uint32_t> out;
        for (std::size_t i = 0; i < n_; ++i) if (get(i)) out.push_back(static_cast<std::uint32_t>(i));
        return out;
    }

    static BitVec prefix(std::size_t n, std::size_t count) {
        BitVec out(n);
        count = std::min(count, n);
        for (std::size_t i = 0; i < count; ++i) out.set(i);
        return out;
    }

    static BitVec sparse(std::size_t n, const std::vector<std::uint32_t>& positions) {
        BitVec out(n);
        for (auto p : positions) if (p < n) out.set(p);
        return out;
    }

    Bytes serialize() const {
        ByteWriter w;
        w.u32(static_cast<std::uint32_t>(n_));
        w.u32(static_cast<std::uint32_t>(words_.size()));
        for (auto x : words_) w.u64(x);
        return w.data;
    }

    static BitVec deserialize(const Bytes& bytes) {
        ByteReader r(bytes);
        auto n = r.u32();
        auto m = r.u32();
        std::vector<std::uint64_t> words;
        words.reserve(m);
        for (std::uint32_t i = 0; i < m; ++i) words.push_back(r.u64());
        return BitVec(n, std::move(words));
    }

private:
    void check_same(const BitVec& other) const {
        if (n_ != other.n_ || words_.size() != other.words_.size()) throw std::runtime_error("BitVec size mismatch");
    }
};

} // namespace loci
