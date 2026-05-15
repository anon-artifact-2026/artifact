#pragma once
#include "loci/common.hpp"

namespace loci {

class RankGuide {
    struct Segment {
        std::uint32_t x0 = 0;
        std::uint32_t x1 = 0;
        double y0 = 0.0;
        double slope = 0.0;
    };
    std::vector<Segment> segments_;

public:
    void train(std::vector<Record> records, int max_segments = 64);
    double predict_rank(std::uint32_t value) const;
    std::size_t segment_count() const { return segments_.size(); }
};

} // namespace loci
