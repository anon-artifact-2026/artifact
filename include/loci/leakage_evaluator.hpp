#pragma once
#include "loci/common.hpp"
#include <cmath>
#include <tuple>

namespace loci {

struct LeakageCellTrace {
    std::uint64_t handle = 0;
    std::uint64_t search_touches = 0;
    std::uint64_t update_touches = 0;
    std::uint64_t maintenance_events = 0;
    std::uint64_t visible_log_refs = 0;
    std::uint64_t max_visible_log_refs = 0;
    std::uint64_t response_refs = 0;
    std::uint64_t response_bytes = 0;

    std::uint64_t true_load = 0;
    std::uint64_t true_log_used = 0;
    std::uint64_t true_update_touches = 0;
    std::uint64_t true_private_maintenance_events = 0;
    std::uint64_t true_log_full_events = 0;
};

struct LeakageEvalResult {
    std::uint64_t cells = 0;
    std::uint64_t top_k = 0;
    double region_precision_at_k = 0.0;
    double hotspot_precision_at_k = 0.0;
    double log_profile_precision_at_k = 0.0;
    double region_auc = 0.0;
    double hotspot_auc = 0.0;
    double log_growth_auc = 0.0;
    double maintenance_auc = 0.0;
    double log_length_correlation = 0.0;
    double maintenance_correlation = 0.0;
    double ambiguity_size = 0.0;
    double normalized_ambiguity = 0.0;
    double log_ambiguity_size = 0.0;
    double normalized_log_ambiguity = 0.0;

    static void write_csv_header(std::ostream& os) {
        os << "eval_cells,eval_top_k,eval_region_precision_at_k,eval_hotspot_precision_at_k,eval_log_profile_precision_at_k,eval_region_auc,eval_hotspot_auc,eval_log_growth_auc,eval_maintenance_auc,eval_log_length_correlation,eval_maintenance_correlation,eval_ambiguity_size,eval_normalized_ambiguity,eval_log_ambiguity_size,eval_normalized_log_ambiguity";
    }

    void write_csv_row(std::ostream& os) const {
        os << cells << ',' << top_k << ',' << region_precision_at_k << ','
           << hotspot_precision_at_k << ',' << log_profile_precision_at_k << ','
           << region_auc << ',' << hotspot_auc << ',' << log_growth_auc << ','
           << maintenance_auc << ','
           << log_length_correlation << ','
           << maintenance_correlation << ',' << ambiguity_size << ','
           << normalized_ambiguity << ',' << log_ambiguity_size << ','
           << normalized_log_ambiguity;
    }
};

inline double pearson_corr(const std::vector<double>& x, const std::vector<double>& y) {
    if (x.size() != y.size() || x.size() < 2) return 0.0;
    double sx = 0.0, sy = 0.0;
    for (std::size_t i = 0; i < x.size(); ++i) {
        sx += x[i];
        sy += y[i];
    }
    double mx = sx / static_cast<double>(x.size());
    double my = sy / static_cast<double>(y.size());
    double num = 0.0, dx = 0.0, dy = 0.0;
    for (std::size_t i = 0; i < x.size(); ++i) {
        double ax = x[i] - mx;
        double ay = y[i] - my;
        num += ax * ay;
        dx += ax * ax;
        dy += ay * ay;
    }
    if (dx == 0.0 || dy == 0.0) return 0.0;
    return num / std::sqrt(dx * dy);
}

inline std::vector<std::size_t> top_k_indices(const std::vector<double>& score, std::size_t k) {
    std::vector<std::size_t> idx(score.size());
    for (std::size_t i = 0; i < idx.size(); ++i) idx[i] = i;
    std::sort(idx.begin(), idx.end(), [&](std::size_t a, std::size_t b) {
        if (score[a] != score[b]) return score[a] > score[b];
        return a < b;
    });
    if (idx.size() > k) idx.resize(k);
    return idx;
}

inline double precision_at_k(const std::vector<double>& predicted, const std::vector<double>& truth, std::size_t k) {
    if (predicted.empty() || predicted.size() != truth.size() || k == 0) return 0.0;
    k = std::min(k, predicted.size());
    auto pred = top_k_indices(predicted, k);
    auto real = top_k_indices(truth, k);
    std::set<std::size_t> real_set(real.begin(), real.end());
    std::size_t hits = 0;
    for (auto i : pred) if (real_set.count(i)) ++hits;
    return static_cast<double>(hits) / static_cast<double>(k);
}

inline double auc_for_top_truth(const std::vector<double>& predicted, const std::vector<double>& truth, std::size_t positives) {
    if (predicted.empty() || predicted.size() != truth.size() || positives == 0 || positives >= truth.size()) return 0.0;
    auto pos_idx = top_k_indices(truth, positives);
    std::set<std::size_t> pos(pos_idx.begin(), pos_idx.end());
    double wins = 0.0;
    double pairs = 0.0;
    for (std::size_t i = 0; i < predicted.size(); ++i) {
        if (!pos.count(i)) continue;
        for (std::size_t j = 0; j < predicted.size(); ++j) {
            if (pos.count(j)) continue;
            if (predicted[i] > predicted[j]) wins += 1.0;
            else if (predicted[i] == predicted[j]) wins += 0.5;
            pairs += 1.0;
        }
    }
    return pairs == 0.0 ? 0.0 : wins / pairs;
}

inline LeakageEvalResult evaluate_leakage_trace(std::vector<LeakageCellTrace> cells, std::size_t top_k = 0) {
    LeakageEvalResult out;
    out.cells = static_cast<std::uint64_t>(cells.size());
    if (cells.empty()) return out;
    if (top_k == 0) top_k = std::max<std::size_t>(1, (cells.size() + 4) / 5);
    top_k = std::min(top_k, cells.size());
    out.top_k = static_cast<std::uint64_t>(top_k);

    std::vector<double> density_pred, density_truth, hotspot_pred, hotspot_truth, log_pred, log_truth, mnt_pred, mnt_truth;
    density_pred.reserve(cells.size());
    density_truth.reserve(cells.size());
    hotspot_pred.reserve(cells.size());
    hotspot_truth.reserve(cells.size());
    log_pred.reserve(cells.size());
    log_truth.reserve(cells.size());
    mnt_pred.reserve(cells.size());
    mnt_truth.reserve(cells.size());

    std::map<std::tuple<std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t>, std::uint64_t> buckets;
    std::map<std::uint64_t, std::uint64_t> log_buckets;
    for (const auto& c : cells) {
        double visible_pressure =
            static_cast<double>(c.search_touches) +
            2.0 * static_cast<double>(c.update_touches) +
            4.0 * static_cast<double>(c.maintenance_events) +
            0.125 * static_cast<double>(c.visible_log_refs) +
            4.0 * static_cast<double>(c.max_visible_log_refs);
        density_pred.push_back(visible_pressure);
        density_truth.push_back(static_cast<double>(c.true_load));
        hotspot_pred.push_back(static_cast<double>(c.update_touches));
        hotspot_truth.push_back(static_cast<double>(c.true_update_touches));
        log_pred.push_back(static_cast<double>(c.max_visible_log_refs));
        log_truth.push_back(static_cast<double>(c.true_log_used));
        mnt_pred.push_back(static_cast<double>(c.maintenance_events));
        mnt_truth.push_back(static_cast<double>(c.true_update_touches + c.true_log_used));

        auto key = std::make_tuple(
            c.search_touches,
            c.update_touches,
            c.maintenance_events,
            c.max_visible_log_refs,
            c.response_refs,
            c.response_bytes);
        buckets[key]++;
        log_buckets[c.max_visible_log_refs]++;
    }

    out.region_precision_at_k = precision_at_k(density_pred, density_truth, top_k);
    out.hotspot_precision_at_k = precision_at_k(hotspot_pred, hotspot_truth, top_k);
    out.log_profile_precision_at_k = precision_at_k(log_pred, log_truth, top_k);
    out.region_auc = auc_for_top_truth(density_pred, density_truth, top_k);
    out.hotspot_auc = auc_for_top_truth(hotspot_pred, hotspot_truth, top_k);
    out.log_growth_auc = auc_for_top_truth(log_pred, log_truth, top_k);
    out.maintenance_auc = auc_for_top_truth(mnt_pred, mnt_truth, top_k);
    out.log_length_correlation = pearson_corr(log_pred, log_truth);
    out.maintenance_correlation = pearson_corr(mnt_pred, mnt_truth);

    double ambiguity_sum = 0.0;
    for (const auto& c : cells) {
        auto key = std::make_tuple(
            c.search_touches,
            c.update_touches,
            c.maintenance_events,
            c.max_visible_log_refs,
            c.response_refs,
            c.response_bytes);
        ambiguity_sum += static_cast<double>(buckets[key]);
    }
    out.ambiguity_size = ambiguity_sum / static_cast<double>(cells.size());
    out.normalized_ambiguity = out.ambiguity_size / static_cast<double>(cells.size());

    double log_ambiguity_sum = 0.0;
    for (const auto& c : cells) log_ambiguity_sum += static_cast<double>(log_buckets[c.max_visible_log_refs]);
    out.log_ambiguity_size = log_ambiguity_sum / static_cast<double>(cells.size());
    out.normalized_log_ambiguity = out.log_ambiguity_size / static_cast<double>(cells.size());
    return out;
}

} // namespace loci
