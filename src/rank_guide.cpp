#include "loci/rank_guide.hpp"

namespace loci {

void RankGuide::train(std::vector<Record> records, int max_segments) {
    segments_.clear();
    if (records.empty()) return;
    std::sort(records.begin(), records.end(), record_less);
    int s_count = std::max(1, std::min(max_segments, static_cast<int>(records.size())));
    segments_.reserve(static_cast<std::size_t>(s_count));
    for (int s = 0; s < s_count; ++s) {
        std::size_t left = static_cast<std::size_t>(s) * records.size() / s_count;
        std::size_t right = static_cast<std::size_t>(s + 1) * records.size() / s_count;
        if (right <= left) right = left + 1;
        auto x0 = records[left].value;
        auto x1 = records[right - 1].value;
        double y0 = static_cast<double>(left);
        double y1 = static_cast<double>(right - 1);
        double slope = (x1 > x0) ? (y1 - y0) / static_cast<double>(x1 - x0) : 0.0;
        segments_.push_back(Segment{x0, x1, y0, slope});
    }
}

double RankGuide::predict_rank(std::uint32_t value) const {
    if (segments_.empty()) return 0.0;
    int lo = 0, hi = static_cast<int>(segments_.size()) - 1, ans = 0;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (segments_[mid].x0 <= value) { ans = mid; lo = mid + 1; }
        else hi = mid - 1;
    }
    const auto& s = segments_[ans];
    if (value <= s.x0) return s.y0;
    if (value >= s.x1) return s.y0 + s.slope * static_cast<double>(s.x1 - s.x0);
    return s.y0 + s.slope * static_cast<double>(value - s.x0);
}

} // namespace loci
