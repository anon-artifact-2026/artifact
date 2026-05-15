#pragma once

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <map>
#include <set>
#include <chrono>
#include <random>
#include <iostream>
#include <fstream>
#include <cstdlib>
#include <limits>

namespace loci {

using Byte = std::uint8_t;
using Bytes = std::vector<Byte>;

inline std::uint64_t splitmix64(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

inline std::size_t next_power_of_two(std::size_t x, std::size_t base = 16) {
    std::size_t y = std::max<std::size_t>(1, base);
    while (y < x) y <<= 1;
    return y;
}

struct Timer {
    std::chrono::high_resolution_clock::time_point t;
    Timer() : t(std::chrono::high_resolution_clock::now()) {}
    void reset() { t = std::chrono::high_resolution_clock::now(); }
    double ms() const {
        return std::chrono::duration<double, std::milli>(
            std::chrono::high_resolution_clock::now() - t).count();
    }
};

struct Record {
    int id = -1;
    std::uint32_t value = 0;
};

inline bool record_less(const Record& a, const Record& b) {
    if (a.value != b.value) return a.value < b.value;
    return a.id < b.id;
}

class ByteWriter {
public:
    Bytes data;
    void u8(std::uint8_t x) { data.push_back(x); }
    void u32(std::uint32_t x) {
        for (int i = 0; i < 4; ++i) data.push_back(static_cast<Byte>((x >> (8 * i)) & 0xff));
    }
    void u64(std::uint64_t x) {
        for (int i = 0; i < 8; ++i) data.push_back(static_cast<Byte>((x >> (8 * i)) & 0xff));
    }
    void i32(int x) { u32(static_cast<std::uint32_t>(x)); }
    void bytes(const Bytes& x) {
        u32(static_cast<std::uint32_t>(x.size()));
        data.insert(data.end(), x.begin(), x.end());
    }
    void vec_u32(const std::vector<std::uint32_t>& v) {
        u32(static_cast<std::uint32_t>(v.size()));
        for (auto x : v) u32(x);
    }
};

class ByteReader {
    const Bytes& data_;
    std::size_t pos_ = 0;
public:
    explicit ByteReader(const Bytes& d) : data_(d) {}
    void require(std::size_t n) const {
        if (pos_ + n > data_.size()) throw std::runtime_error("ByteReader: truncated input");
    }
    std::uint8_t u8() { require(1); return data_[pos_++]; }
    std::uint32_t u32() {
        require(4);
        std::uint32_t x = 0;
        for (int i = 0; i < 4; ++i) x |= static_cast<std::uint32_t>(data_[pos_++]) << (8 * i);
        return x;
    }
    std::uint64_t u64() {
        require(8);
        std::uint64_t x = 0;
        for (int i = 0; i < 8; ++i) x |= static_cast<std::uint64_t>(data_[pos_++]) << (8 * i);
        return x;
    }
    int i32() { return static_cast<int>(u32()); }
    Bytes bytes() {
        auto n = u32(); require(n);
        Bytes out(data_.begin() + static_cast<long>(pos_), data_.begin() + static_cast<long>(pos_ + n));
        pos_ += n;
        return out;
    }
    std::vector<std::uint32_t> vec_u32() {
        auto n = u32();
        std::vector<std::uint32_t> v;
        v.reserve(n);
        for (std::uint32_t i = 0; i < n; ++i) v.push_back(u32());
        return v;
    }
};

} // namespace loci
