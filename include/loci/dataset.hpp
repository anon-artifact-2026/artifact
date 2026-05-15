#pragma once
#include "loci/common.hpp"

namespace loci {

inline std::vector<Record> make_skewed_dataset(std::size_t n, std::uint32_t universe, std::uint32_t seed = 7) {
    if (universe == 0) throw std::runtime_error("dataset universe must be positive");
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> coin(0.0, 1.0);
    std::uniform_int_distribution<std::uint32_t> all(0, universe - 1);
    std::uint32_t center = universe / 3;
    std::uint32_t width = std::max<std::uint32_t>(4, universe / 70);
    std::uint32_t hot_lo = (center > width) ? (center - width) : 0;
    std::uint32_t hot_hi = std::min<std::uint32_t>(universe - 1, center + width);
    std::uniform_int_distribution<std::uint32_t> hot(hot_lo, hot_hi);
    std::vector<Record> records;
    records.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        std::uint32_t v = (coin(rng) < 0.55) ? hot(rng) : all(rng);
        records.push_back(Record{static_cast<int>(i), v});
    }
    return records;
}

inline std::vector<Record> make_uniform_dataset(std::size_t n, std::uint32_t universe, std::uint32_t seed = 9) {
    if (universe == 0) throw std::runtime_error("dataset universe must be positive");
    std::mt19937 rng(seed);
    std::uniform_int_distribution<std::uint32_t> all(0, universe - 1);
    std::vector<Record> records;
    records.reserve(n);
    for (std::size_t i = 0; i < n; ++i) records.push_back(Record{static_cast<int>(i), all(rng)});
    return records;
}

inline std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    bool quoted = false;
    for (std::size_t i = 0; i < line.size(); ++i) {
        char c = line[i];
        if (quoted) {
            if (c == '"' && i + 1 < line.size() && line[i + 1] == '"') {
                cur.push_back('"');
                ++i;
            } else if (c == '"') {
                quoted = false;
            } else {
                cur.push_back(c);
            }
        } else if (c == '"') {
            quoted = true;
        } else if (c == ',') {
            out.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(cur);
    return out;
}

inline std::string trim_csv_cell(const std::string& s) {
    std::size_t b = 0;
    std::size_t e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\r' || s[b] == '\n')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r' || s[e - 1] == '\n')) --e;
    return s.substr(b, e - b);
}

inline std::size_t choose_csv_column(const std::map<std::string, std::size_t>& col,
                                     const std::vector<std::string>& candidates,
                                     const std::string& role) {
    for (const auto& name : candidates) {
        auto it = col.find(name);
        if (it != col.end()) return it->second;
    }
    std::string msg = "dataset CSV missing " + role + " column; tried:";
    for (const auto& name : candidates) msg += " " + name;
    throw std::runtime_error(msg);
}

inline std::vector<Record> load_range_csv_dataset(const std::string& path,
                                                  std::uint32_t universe,
                                                  std::size_t limit = 0,
                                                  const std::string& id_column = "id",
                                                  const std::string& range_column = "range_value") {
    if (universe == 0) throw std::runtime_error("dataset universe must be positive");
    std::ifstream in(path);
    if (!in) throw std::runtime_error("could not open dataset CSV: " + path);

    std::string line;
    if (!std::getline(in, line)) throw std::runtime_error("dataset CSV is empty: " + path);
    auto header = split_csv_line(line);
    std::map<std::string, std::size_t> col;
    for (std::size_t i = 0; i < header.size(); ++i) col[trim_csv_cell(header[i])] = i;
    std::size_t id_idx = choose_csv_column(col, {id_column, "rid", "id"}, "record id");
    std::size_t value_idx = choose_csv_column(col, {range_column, "value", "range_value", "raw_value"}, "ordered value");

    std::vector<std::pair<int, std::int64_t>> raw;
    raw.reserve(limit ? limit : 1024);
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        auto fields = split_csv_line(line);
        if (fields.size() <= std::max(id_idx, value_idx)) continue;
        int id = std::stoi(trim_csv_cell(fields[id_idx]));
        std::int64_t value = std::stoll(trim_csv_cell(fields[value_idx]));
        raw.push_back({id, value});
        if (limit != 0 && raw.size() >= limit) break;
    }
    if (raw.empty()) throw std::runtime_error("dataset CSV produced no records: " + path);

    std::vector<std::int64_t> unique_values;
    unique_values.reserve(raw.size());
    for (const auto& rec : raw) unique_values.push_back(rec.second);
    std::sort(unique_values.begin(), unique_values.end());
    unique_values.erase(std::unique(unique_values.begin(), unique_values.end()), unique_values.end());

    std::map<std::int64_t, std::uint32_t> compressed;
    if (unique_values.size() == 1) {
        compressed[unique_values.front()] = 0;
    } else {
        const std::uint64_t denom = static_cast<std::uint64_t>(unique_values.size() - 1);
        const std::uint64_t scale = static_cast<std::uint64_t>(universe - 1);
        for (std::size_t i = 0; i < unique_values.size(); ++i) {
            std::uint32_t mapped = static_cast<std::uint32_t>((static_cast<std::uint64_t>(i) * scale) / denom);
            compressed[unique_values[i]] = mapped;
        }
    }

    std::vector<Record> records;
    records.reserve(raw.size());
    for (const auto& rec : raw) {
        records.push_back(Record{rec.first, compressed[rec.second]});
    }
    return records;
}

} // namespace loci
