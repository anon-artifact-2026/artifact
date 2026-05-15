#include "loci/loci.hpp"
#include "loci/tree_range.hpp"
#include "loci/fbdsse_rq.hpp"
#include "loci/cell_baseline.hpp"
#include "loci/dataset.hpp"
#include <iomanip>
#include <sstream>
#include <filesystem>
#include <cmath>

using namespace loci;

struct Args {
    std::size_t N = 3000;
    int ops = 500;
    std::uint32_t U = 1u << 20;
    int B = 512;
    int theta = 32;
    int pad_pool = 1024;
    int fanout_class = 16;
    int refresh_period = 64;
    int split_load_percent = 90;
    int merge_load_percent = 25;
    std::size_t eval_topk = 0;
    std::string scheme = "loci";
    std::string crypto = "mock";
    std::string dist = "skew";
    std::string workload = "mixed";
    std::string variant = "full";
    std::string csv;
    std::string trace_dir;
    std::string data_csv;
    std::string dataset_name;
    std::size_t data_limit = 0;
    std::uint32_t seed = 123;
    double query_ratio = -1.0;
    double selectivity = -1.0;
    bool attack_suite = false;
    bool workload_explicit = false;
};

static Args parse(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) throw std::runtime_error("missing argument for " + k);
            return argv[++i];
        };
        if (k == "--N") a.N = std::stoull(next());
        else if (k == "--ops") a.ops = std::stoi(next());
        else if (k == "--U") a.U = static_cast<std::uint32_t>(std::stoul(next()));
        else if (k == "--B") a.B = std::stoi(next());
        else if (k == "--theta") a.theta = std::stoi(next());
        else if (k == "--pad-pool") a.pad_pool = std::stoi(next());
        else if (k == "--fanout-class") a.fanout_class = std::stoi(next());
        else if (k == "--refresh-period") a.refresh_period = std::stoi(next());
        else if (k == "--split-load-percent") a.split_load_percent = std::stoi(next());
        else if (k == "--merge-load-percent") a.merge_load_percent = std::stoi(next());
        else if (k == "--eval-topk") a.eval_topk = std::stoull(next());
        else if (k == "--scheme") a.scheme = next();
        else if (k == "--crypto") a.crypto = next();
        else if (k == "--dist") a.dist = next();
        else if (k == "--workload") { a.workload = next(); a.workload_explicit = true; }
        else if (k == "--variant") a.variant = next();
        else if (k == "--csv") a.csv = next();
        else if (k == "--trace-dir") a.trace_dir = next();
        else if (k == "--data-csv") a.data_csv = next();
        else if (k == "--dataset") a.dataset_name = next();
        else if (k == "--data-limit") a.data_limit = std::stoull(next());
        else if (k == "--seed") a.seed = static_cast<std::uint32_t>(std::stoul(next()));
        else if (k == "--query-ratio") a.query_ratio = std::stod(next());
        else if (k == "--selectivity") a.selectivity = std::stod(next());
        else if (k == "--attack-suite") a.attack_suite = true;
        else if (k == "--help") {
            std::cout << "Usage: ./bench_loci --scheme loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant full --csv out.csv\n";
            std::cout << "Schemes: loci, pgm, fixedcell, fbdsse, tree\n";
            std::cout << "Crypto: mock, real\n";
            std::cout << "Workloads: mixed, uniform, hotspot, drift, burst, structured, skew_hotspot_drift_mix\n";
            std::cout << "LOCI variants: full, nocert, nopad, noproto, nopublicrefresh, naive\n";
            std::cout << "PGM variants: naive, globalpad\n";
            std::cout << "FixedCell variants: bitmap, padded\n";
            std::cout << "Leakage attack suite: --attack-suite --crypto real --csv attack_suite.csv\n";
            std::cout << "Trace export: --trace-dir traces\n";
            std::cout << "CSV dataset: --data-csv data/processed/nyc/nyc_time.csv --data-limit 100000\n";
            std::cout << "Other processed examples: data/processed/gowalla/gowalla_location.csv, data/processed/geolife/geolife_lat.csv\n";
            std::cout << "Registry dataset: --dataset nyc_time --data-limit 100000\n";
            std::cout << "Experiment driver: --seed 0 --query-ratio 0.8 --selectivity 0.01\n";
            std::cout << "LOCI public classes: --fanout-class 16 --refresh-period 64 --split-load-percent 90 --merge-load-percent 25\n";
            std::exit(0);
        }
    }
    return a;
}

static CryptoMode parse_crypto_mode(const std::string& crypto) {
    if (crypto == "mock") return CryptoMode::Mock;
    if (crypto == "real" || crypto == "openssl") return CryptoMode::OpenSSL;
    throw std::runtime_error("unknown --crypto: " + crypto);
}

static std::string trim_text(const std::string& s) {
    std::size_t b = 0;
    std::size_t e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\r' || s[b] == '\n')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r' || s[e - 1] == '\n')) --e;
    return s.substr(b, e - b);
}

static std::string strip_quotes(const std::string& s) {
    if (s.size() >= 2 && ((s.front() == '"' && s.back() == '"') || (s.front() == '\'' && s.back() == '\''))) {
        return s.substr(1, s.size() - 2);
    }
    return s;
}

static std::string resolve_dataset_path(const std::string& dataset_name) {
    std::ifstream in("configs/datasets.yaml");
    if (!in) throw std::runtime_error("could not open configs/datasets.yaml for --dataset " + dataset_name);
    std::string line;
    bool in_datasets = false;
    bool in_target = false;
    while (std::getline(in, line)) {
        std::string trimmed = trim_text(line);
        if (trimmed.empty() || trimmed[0] == '#') continue;
        if (trimmed == "datasets:") {
            in_datasets = true;
            continue;
        }
        if (!in_datasets) continue;
        if (line.rfind("  ", 0) == 0 && line.rfind("    ", 0) != 0 && trimmed.back() == ':') {
            std::string key = trimmed.substr(0, trimmed.size() - 1);
            in_target = (key == dataset_name);
            continue;
        }
        if (in_target && line.rfind("    ", 0) == 0 && trimmed.rfind("path:", 0) == 0) {
            return strip_quotes(trim_text(trimmed.substr(5)));
        }
    }
    throw std::runtime_error("unknown --dataset in configs/datasets.yaml: " + dataset_name);
}

static std::vector<Record> make_dataset(const Args& args) {
    if (!args.data_csv.empty()) return load_range_csv_dataset(args.data_csv, args.U, args.data_limit);
    if (!args.dataset_name.empty()) return load_range_csv_dataset(resolve_dataset_path(args.dataset_name), args.U, args.data_limit);
    if (args.dist == "uniform") return make_uniform_dataset(args.N, args.U, args.seed + 9);
    if (args.dist == "skew") return make_skewed_dataset(args.N, args.U, args.seed + 7);
    throw std::runtime_error("unknown --dist: " + args.dist);
}

struct BenchResult {
    BuildStats build_stats;
    double build_ms = 0.0;
    double avg_query_ms = 0.0;
    double avg_update_ms = 0.0;
    std::size_t logical_cells = 0;
    std::size_t active = 0;
    std::size_t server_bytes = 0;
    TranscriptStats transcript;
    LBCStorageStats lbc_stats;
    LeakageEvalResult eval;
    std::string summary;
};

static std::string dataset_label(const Args& args) {
    std::string suffix = "-B" + std::to_string(args.B) + "-T" + std::to_string(args.theta);
    if (!args.dataset_name.empty()) {
        std::string limit = args.data_limit ? "-L" + std::to_string(args.data_limit) : "";
        return args.dataset_name + "-" + args.workload + limit + "-U" + std::to_string(args.U) + suffix;
    }
    if (!args.data_csv.empty()) {
        std::filesystem::path p(args.data_csv);
        std::string limit = args.data_limit ? "-L" + std::to_string(args.data_limit) : "";
        return p.stem().string() + "-" + args.workload + limit + "-U" + std::to_string(args.U) + suffix;
    }
    return args.dist + "-" + args.workload + "-N" + std::to_string(args.N) + "-U" + std::to_string(args.U) + suffix;
}

static std::string scheme_label(const Args& args) {
    if (args.scheme == "loci") {
        if (args.variant == "full") return "LOCI-Full";
        if (args.variant == "nocert") return "LOCI-NoCert";
        if (args.variant == "nopad") return "LOCI-NoPad";
        if (args.variant == "noproto") return "LOCI-NoProto";
        if (args.variant == "nopublicrefresh") return "LOCI-NoPublicRefresh";
        return "LOCI-" + args.variant;
    }
    if (args.scheme == "pgm" || args.scheme == "pgm-learned") {
        return args.variant == "globalpad" ? "PGM-Learned-GlobalPad" : "PGM-Learned-Naive";
    }
    if (args.scheme == "fixedcell" || args.scheme == "fixed-cell") return "FixedCell-Bitmap";
    if (args.scheme == "fbdsse" || args.scheme == "fbdsse-rq" || args.scheme == "treecover") return "FBDSSE-RQ-TreeCover";
    if (args.scheme == "tree" || args.scheme == "treerange") return "TreeRange";
    return args.scheme + "-" + args.variant;
}

static double avg_repair(const LBCStorageStats& stats) {
    return stats.boundary_count
        ? static_cast<double>(stats.repair_entries) / static_cast<double>(stats.boundary_count)
        : 0.0;
}

static double compression_ratio(const LBCStorageStats& stats) {
    return stats.sealed_bytes()
        ? static_cast<double>(stats.raw_bitmap_bytes) / static_cast<double>(stats.sealed_bytes())
        : 0.0;
}

static double per_count_ms(double total_ms, std::uint64_t count) {
    return count ? total_ms / static_cast<double>(count) : 0.0;
}

template <typename Index>
static BenchResult execute_index(Index& idx, const Args& args, const std::vector<Record>& records) {
    Timer timer;
    auto bs = idx.build(records);
    double build_ms = timer.ms();
    std::mt19937 rng(args.seed);
    idx.check_correctness(rng, 50);
    idx.reset_measurements();

    std::uniform_int_distribution<std::uint32_t> val(0, args.U - 1);
    std::uniform_int_distribution<std::size_t> empirical_pick(0, records.empty() ? 0 : records.size() - 1);
    int next_id = 0;
    for (const auto& rec : records) next_id = std::max(next_id, rec.id + 1);
    double q_ms = 0.0, u_ms = 0.0;
    int q_count = 0, u_count = 0;

    std::uint32_t hot_width = std::max<std::uint32_t>(1, args.U / 100);
    std::uniform_real_distribution<double> coin(0.0, 1.0);

    auto sample_band = [&](std::uint32_t center, std::uint32_t width) {
        std::uint32_t lo = (center > width) ? (center - width) : 0;
        std::uint32_t hi = std::min<std::uint32_t>(args.U - 1, center + width);
        std::uniform_int_distribution<std::uint32_t> band(lo, hi);
        return band(rng);
    };

    auto hot_value = [&](int step) {
        if (args.workload == "drift") {
            std::uint64_t start = args.U / 5;
            std::uint64_t end = (args.U * 4ULL) / 5ULL;
            std::uint64_t span = end > start ? end - start : 0;
            std::uint64_t center = start + (span * static_cast<std::uint64_t>(std::max(0, step)))
                / static_cast<std::uint64_t>(std::max(1, args.ops - 1));
            return sample_band(static_cast<std::uint32_t>(std::min<std::uint64_t>(center, args.U - 1)), hot_width);
        }
        return sample_band(args.U / 3, hot_width);
    };

    auto empirical_value = [&]() {
        if (records.empty()) return val(rng);
        return records[empirical_pick(rng)].value;
    };

    auto workload_value = [&](int step) {
        if (args.workload == "uniform" || args.workload == "mixed") return val(rng);
        if (args.workload == "real_temporal") return empirical_value();
        if (args.workload == "skew") {
            return (coin(rng) < 0.55) ? sample_band(args.U / 3, std::max<std::uint32_t>(hot_width, args.U / 70)) : val(rng);
        }
        if (args.workload == "hotspot") {
            return (coin(rng) < 0.85) ? sample_band(args.U / 3, hot_width) : val(rng);
        }
        if (args.workload == "drift") return hot_value(step);
        if (args.workload == "burst") {
            int phase = (step / std::max(1, args.ops / 10)) % 2;
            return (phase == 0 && coin(rng) < 0.95) ? sample_band(args.U / 3, hot_width) : val(rng);
        }
        if (args.workload == "structured") {
            std::uint32_t centers[4] = {args.U / 8, args.U / 3, args.U / 2, (args.U * 7u) / 8u};
            return sample_band(centers[static_cast<std::size_t>(step) % 4], std::max<std::uint32_t>(hot_width, args.U / 200));
        }
        if (args.workload == "skew_hotspot_drift_mix") {
            if (step % 3 == 0) return sample_band(args.U / 3, hot_width);
            if (step % 3 == 1) return hot_value(step);
            return (coin(rng) < 0.70) ? sample_band(args.U / 2, hot_width) : val(rng);
        }
        throw std::runtime_error("unknown --workload: " + args.workload);
    };

    auto sample_query = [&](int step) {
        std::uint32_t width = 1;
        if (args.selectivity > 0.0) {
            double raw_width = std::max(1.0, std::floor(static_cast<double>(args.U) * args.selectivity));
            width = static_cast<std::uint32_t>(std::min<double>(raw_width, args.U));
        } else {
            width = (args.workload == "hotspot" || args.workload == "drift" || args.workload == "burst"
                || args.workload == "structured" || args.workload == "skew_hotspot_drift_mix")
                ? std::max<std::uint32_t>(1, args.U / 200)
                : std::max<std::uint32_t>(1, args.U / 50);
        }
        std::uint32_t center = workload_value(step);
        std::uint32_t half = width / 2;
        std::uint32_t L = center > half ? center - half : 0;
        std::uint32_t R = std::min<std::uint32_t>(args.U - 1, L + width - 1);
        if (R - L + 1 < width && R == args.U - 1) {
            L = (width >= args.U) ? 0 : args.U - width;
        }
        return std::pair<std::uint32_t, std::uint32_t>{L, R};
    };

    for (int i = 0; i < args.ops; ++i) {
        if (args.query_ratio >= 0.0) {
            bool do_query = coin(rng) < args.query_ratio;
            if (do_query) {
                auto [L, R] = sample_query(i);
                timer.reset();
                auto res = idx.search(L, R);
                (void)res;
                q_ms += timer.ms();
                ++q_count;
            } else if (coin(rng) < 0.5 || next_id <= 0) {
                auto v = workload_value(i);
                timer.reset();
                idx.insert(next_id++, v);
                u_ms += timer.ms();
                ++u_count;
            } else {
                int id = static_cast<int>(rng() % std::max(1, next_id));
                timer.reset();
                try {
                    idx.erase(id);
                    u_ms += timer.ms();
                    ++u_count;
                } catch (...) {
                    // deleting an already-deleted id is skipped in the benchmark workload
                }
            }
            continue;
        }

        int mode = i % 3;
        if (args.workload == "hotspot" || args.workload == "drift") {
            mode = (i % 4 == 0) ? 0 : 1;
        } else if (args.workload == "uniform") {
            mode = i % 3;
        } else if (args.workload != "mixed") {
            throw std::runtime_error("unknown --workload: " + args.workload);
        }

        if (mode == 0) {
            std::uint32_t L = 0, R = 0;
            if ((args.workload == "hotspot" || args.workload == "drift") && coin(rng) < 0.80) {
                L = hot_value(i);
                R = hot_value(i);
            } else {
                L = val(rng);
                R = val(rng);
            }
            if (L > R) std::swap(L, R);
            timer.reset();
            auto res = idx.search(L, R);
            (void)res;
            q_ms += timer.ms();
            ++q_count;
        } else if (mode == 1) {
            auto v = ((args.workload == "hotspot" || args.workload == "drift") && coin(rng) < 0.85)
                ? hot_value(i)
                : val(rng);
            timer.reset();
            idx.insert(next_id++, v);
            u_ms += timer.ms();
            ++u_count;
        } else {
            int id = static_cast<int>(rng() % std::max(1, next_id));
            timer.reset();
            try {
                idx.erase(id);
                u_ms += timer.ms();
                ++u_count;
            } catch (...) {
                // deleting an already-deleted id is skipped in the benchmark workload
            }
        }
    }

    BenchResult out;
    out.build_stats = bs;
    out.build_ms = build_ms;
    out.avg_query_ms = q_count ? q_ms / q_count : 0.0;
    out.avg_update_ms = u_count ? u_ms / u_count : 0.0;
    out.logical_cells = idx.logical_cell_count();
    out.active = idx.active_size();
    out.server_bytes = idx.server_bytes();
    out.transcript = idx.transcript();
    out.lbc_stats = idx.lbc_storage_stats();
    out.eval = idx.evaluate_leakage(args.eval_topk);
    std::ostringstream summary;
    idx.print_summary(summary);
    out.summary = summary.str();
    if (!args.trace_dir.empty()) idx.write_trace(args.trace_dir, scheme_label(args), dataset_label(args));
    idx.check_correctness(rng, 50);
    return out;
}

static void print_result(const Args& args, const BenchResult& result) {
    std::cout << "LOCI/LBC refactored semantic SE prototype\n";
    std::cout << std::fixed << std::setprecision(3);
    std::cout << "scheme=" << args.scheme
              << " variant=" << args.variant
              << " crypto=" << args.crypto
              << " workload=" << args.workload
              << " build_ms=" << result.build_ms
              << " train_ms=" << result.build_stats.train_ms
              << " certify_ms=" << result.build_stats.certify_ms
              << " encode_ms=" << result.build_stats.encode_ms << '\n';
    std::cout << result.summary;
    std::cout << "avg_query_ms=" << result.avg_query_ms
              << " avg_update_ms=" << result.avg_update_ms << '\n';

    const auto& tr = result.transcript;
    const auto& lbc_stats = result.lbc_stats;
    const auto& eval = result.eval;

    std::cout << "transcript searches=" << tr.searches
              << " updates=" << tr.updates
              << " refreshes=" << tr.refreshes
              << " splits=" << tr.splits
              << " merges=" << tr.merges
              << " touched=" << tr.touched_cells
              << " fetched=" << tr.fetched_objects
              << " response_bytes=" << tr.response_bytes
              << " patch_bytes=" << tr.patch_bytes
              << " refresh_bytes=" << tr.refresh_bytes
              << " guide_locates=" << tr.guide_locates
              << " guide_corrections=" << tr.guide_corrections
              << " token_padding_refs=" << tr.token_padding_refs
              << " max_token_refs=" << tr.max_token_refs
              << " max_fanout_class=" << tr.max_fanout_class
              << " log_refs=" << tr.log_refs
              << " raw_log_length_exposures=" << tr.raw_log_length_exposures
              << " max_visible_log_refs_per_cell=" << tr.max_visible_log_refs_per_cell
              << " ordered_token_exposures=" << tr.ordered_token_exposures
              << " capacity_class=" << tr.cert_capacity_class
              << " fanout_class=" << tr.cert_fanout_class
              << " log_class=" << tr.cert_log_class
              << " maintenance_class=" << tr.cert_maintenance_class
              << " split_load_class=" << tr.cert_split_load_class
              << " merge_load_class=" << tr.cert_merge_load_class
              << " desc_object_class=" << tr.cert_desc_object_class
              << " proto_object_class=" << tr.cert_proto_object_class
              << " patch_object_class=" << tr.cert_patch_object_class
              << " full_object_class=" << tr.cert_full_object_class
              << " public_refresh_ticks=" << tr.public_refresh_ticks
              << " scheduled_refreshes=" << tr.scheduled_refreshes
              << " forced_log_refreshes=" << tr.forced_log_refreshes
              << " forced_capacity_splits=" << tr.forced_capacity_splits
              << " public_split_events=" << tr.public_split_events
              << " public_merge_events=" << tr.public_merge_events
              << " cert_candidate_cells=" << tr.cert_candidate_cells
              << " cert_certified_cells=" << tr.cert_certified_cells
              << " cert_capacity_overflow_splits=" << tr.cert_capacity_overflow_splits
              << " patch_update_latency_ms=" << per_count_ms(tr.patch_update_latency_ms_total, tr.updates)
              << " maintenance_latency_ms=" << per_count_ms(tr.maintenance_latency_ms_total, tr.updates)
              << " refresh_latency_ms=" << per_count_ms(tr.refresh_latency_ms_total, tr.refreshes)
              << " guide_retrain_count=" << tr.guide_retrains
              << " locator_rebuild_count=" << tr.locator_rebuilds << '\n';
    std::cout << "lbc_stats boundary_count=" << lbc_stats.boundary_count
              << " prototype_count=" << lbc_stats.prototype_count
              << " repair_entries=" << lbc_stats.repair_entries
              << " avg_repair=" << avg_repair(lbc_stats)
              << " desc_bytes=" << lbc_stats.desc_sealed_bytes
              << " proto_bytes=" << lbc_stats.proto_sealed_bytes
              << " full_bytes=" << lbc_stats.full_sealed_bytes
              << " log_bytes=" << lbc_stats.log_sealed_bytes
              << " raw_bitmap_bytes=" << lbc_stats.raw_bitmap_bytes
              << " compression_ratio=" << compression_ratio(lbc_stats) << '\n';
    std::cout << "leakage_eval cells=" << eval.cells
              << " top_k=" << eval.top_k
              << " region_precision_at_k=" << eval.region_precision_at_k
              << " hotspot_precision_at_k=" << eval.hotspot_precision_at_k
              << " log_profile_precision_at_k=" << eval.log_profile_precision_at_k
              << " region_auc=" << eval.region_auc
              << " hotspot_auc=" << eval.hotspot_auc
              << " log_growth_auc=" << eval.log_growth_auc
              << " maintenance_auc=" << eval.maintenance_auc
              << " log_length_correlation=" << eval.log_length_correlation
              << " maintenance_correlation=" << eval.maintenance_correlation
              << " ambiguity_size=" << eval.ambiguity_size
              << " normalized_ambiguity=" << eval.normalized_ambiguity
              << " log_ambiguity_size=" << eval.log_ambiguity_size
              << " normalized_log_ambiguity=" << eval.normalized_log_ambiguity << '\n';
    std::cout << "All correctness checks passed.\n";
}

static void write_result_csv(const Args& args, const BenchResult& result) {
    if (args.csv.empty()) return;
    bool exists = static_cast<bool>(std::ifstream(args.csv));
    std::ofstream os(args.csv, std::ios::app);
    if (!exists) {
        os << "case,scheme,N,ops,U,B,theta,pad_pool,fanout_class,refresh_period,split_load_percent,merge_load_percent,dist,workload,variant,crypto,seed,query_ratio,selectivity,build_ms,avg_query_ms,avg_update_ms,update_total_latency_ms,patch_update_latency_ms,maintenance_latency_ms,refresh_latency_ms,refresh_count,scheduled_refresh_count,forced_log_refresh_count,public_rollover_count,split_count,merge_count,guide_retrain_count,locator_rebuild_count,logical_cells,active,server_bytes,lbc_boundary_count,lbc_prototype_count,lbc_repair_entries,lbc_avg_repair,lbc_desc_bytes,lbc_proto_bytes,lbc_full_bytes,lbc_log_bytes,lbc_raw_bitmap_bytes,lbc_compression_ratio,";
        result.transcript.write_csv_header(os);
        os << ',';
        LeakageEvalResult::write_csv_header(os);
        os << '\n';
    }
    os << scheme_label(args) << ',' << args.scheme << ',' << args.N << ',' << args.ops << ',' << args.U << ',' << args.B << ','
       << args.theta << ',' << args.pad_pool << ',' << args.fanout_class << ',' << args.refresh_period << ','
       << args.split_load_percent << ',' << args.merge_load_percent << ',' << args.dist << ',' << args.workload << ','
       << args.variant << ',' << args.crypto << ',' << args.seed << ',' << args.query_ratio << ',' << args.selectivity << ','
       << result.build_ms << ',' << result.avg_query_ms << ',' << result.avg_update_ms << ','
       << result.avg_update_ms << ','
       << per_count_ms(result.transcript.patch_update_latency_ms_total, result.transcript.updates) << ','
       << per_count_ms(result.transcript.maintenance_latency_ms_total, result.transcript.updates) << ','
       << per_count_ms(result.transcript.refresh_latency_ms_total, result.transcript.refreshes) << ','
       << result.transcript.refreshes << ','
       << result.transcript.scheduled_refreshes << ','
       << result.transcript.forced_log_refreshes << ','
       << result.transcript.public_refresh_ticks << ','
       << result.transcript.splits << ','
       << result.transcript.merges << ','
       << result.transcript.guide_retrains << ','
       << result.transcript.locator_rebuilds << ','
       << result.logical_cells << ',' << result.active << ',' << result.server_bytes << ','
       << result.lbc_stats.boundary_count << ',' << result.lbc_stats.prototype_count << ',' << result.lbc_stats.repair_entries << ','
       << avg_repair(result.lbc_stats) << ',' << result.lbc_stats.desc_sealed_bytes << ','
       << result.lbc_stats.proto_sealed_bytes << ',' << result.lbc_stats.full_sealed_bytes << ','
       << result.lbc_stats.log_sealed_bytes << ',' << result.lbc_stats.raw_bitmap_bytes << ','
       << compression_ratio(result.lbc_stats) << ',';
    result.transcript.write_csv_row(os);
    os << ',';
    result.eval.write_csv_row(os);
    os << '\n';
}

static LOCIParams make_loci_params(const Args& args, CryptoMode mode) {
    LOCIParams p;
    p.universe = args.U;
    p.lbc.B = args.B;
    p.lbc.theta = args.theta;
    p.lbc.rho = 32;
    p.lbc.kappa = std::max(1, args.B / p.lbc.rho);
    if (p.lbc.rho * p.lbc.kappa != p.lbc.B) {
        p.lbc.rho = 1;
        p.lbc.kappa = p.lbc.B;
    }
    p.lbc.max_prototypes = 8;
    p.pad_pool_size = args.pad_pool;
    p.public_fanout_base = args.fanout_class;
    p.public_refresh_period = args.refresh_period;
    p.split_load_percent = args.split_load_percent;
    p.merge_load_percent = args.merge_load_percent;
    p.crypto_mode = mode;
    if (args.variant == "nopad") {
        p.enable_padding = false;
        p.expose_log_length = true;
    }
    else if (args.variant == "noproto") p.enable_prototypes = false;
    else if (args.variant == "nocert") p.enable_certification = false;
    else if (args.variant == "nopublicrefresh") p.enable_public_refresh = false;
    else if (args.variant == "naive") {
        p.enable_padding = false;
        p.enable_prototypes = false;
        p.enable_public_refresh = false;
        p.enable_certification = false;
        p.expose_log_length = true;
        p.expose_token_order = true;
    } else if (args.variant != "full") throw std::runtime_error("unknown LOCI --variant: " + args.variant);
    return p;
}

static CellBaselineParams make_cell_params(const Args& args, CryptoMode mode, CellLayoutKind layout) {
    CellBaselineParams p;
    p.universe = args.U;
    p.target_cell_size = args.B;
    p.theta = args.theta;
    p.pad_pool_size = args.pad_pool;
    p.public_refresh_period = args.refresh_period;
    p.crypto_mode = mode;
    p.layout = layout;
    if (layout == CellLayoutKind::PGMLearned) {
        if (args.variant == "globalpad") p.global_padding = true;
        else if (args.variant == "naive" || args.variant == "full") p.global_padding = false;
        else throw std::runtime_error("unknown PGM --variant: " + args.variant);
    } else {
        if (args.variant == "padded" || args.variant == "globalpad") p.global_padding = true;
        else if (args.variant == "bitmap" || args.variant == "full") p.global_padding = false;
        else throw std::runtime_error("unknown FixedCell --variant: " + args.variant);
    }
    return p;
}

static BenchResult run_config(const Args& args, const std::vector<Record>& records) {
    auto mode = parse_crypto_mode(args.crypto);
    if (args.scheme == "loci") {
        LOCIIndex idx(make_loci_params(args, mode), 0xBEEFULL);
        return execute_index(idx, args, records);
    }
    if (args.scheme == "pgm" || args.scheme == "pgm-learned") {
        CellBaseline idx(make_cell_params(args, mode, CellLayoutKind::PGMLearned), 0xBEEFULL);
        return execute_index(idx, args, records);
    }
    if (args.scheme == "fixedcell" || args.scheme == "fixed-cell") {
        CellBaseline idx(make_cell_params(args, mode, CellLayoutKind::FixedWidth), 0xBEEFULL);
        return execute_index(idx, args, records);
    }
    if (args.scheme == "fbdsse" || args.scheme == "fbdsse-rq" || args.scheme == "treecover") {
        FBDSSERQParams p;
        p.universe = args.U;
        p.crypto_mode = mode;
        FBDSSERQBackend idx(p, 0xBEEFULL);
        return execute_index(idx, args, records);
    }
    if (args.scheme == "tree" || args.scheme == "treerange") {
        TreeRangeParams p;
        p.universe = args.U;
        p.crypto_mode = mode;
        TreeRangeBaseline idx(p, 0xBEEFULL);
        return execute_index(idx, args, records);
    }
    throw std::runtime_error("unknown --scheme: " + args.scheme);
}

static int run_single(const Args& args) {
    auto records = make_dataset(args);
    auto result = run_config(args, records);
    print_result(args, result);
    write_result_csv(args, result);
    return 0;
}

static void print_attack_suite_header() {
    std::cout << std::left
              << std::setw(22) << "case"
              << std::right
              << std::setw(10) << "reg_auc"
              << std::setw(10) << "hot_auc"
              << std::setw(10) << "log_auc"
              << std::setw(10) << "mnt_auc"
              << std::setw(10) << "log_corr"
              << std::setw(10) << "mnt_corr"
              << std::setw(10) << "log_amb"
              << std::setw(10) << "sched"
              << std::setw(10) << "forced"
              << std::setw(10) << "q_ms"
              << std::setw(10) << "u_ms"
              << '\n';
}

static void print_attack_suite_row(const Args& args, const BenchResult& result) {
    std::string name = (args.scheme == "loci") ? args.variant : (args.scheme + "-" + args.variant);
    std::cout << std::left << std::setw(22) << name << std::right
              << std::setw(10) << result.eval.region_auc
              << std::setw(10) << result.eval.hotspot_auc
              << std::setw(10) << result.eval.log_growth_auc
              << std::setw(10) << result.eval.maintenance_auc
              << std::setw(10) << result.eval.log_length_correlation
              << std::setw(10) << result.eval.maintenance_correlation
              << std::setw(10) << result.eval.normalized_log_ambiguity
              << std::setw(10) << result.transcript.scheduled_refreshes
              << std::setw(10) << (result.transcript.forced_log_refreshes + result.transcript.forced_capacity_splits)
              << std::setw(10) << result.avg_query_ms
              << std::setw(10) << result.avg_update_ms
              << '\n';
}

static int run_attack_suite(Args args) {
    if (!args.workload_explicit) args.workload = "hotspot";
    auto records = make_dataset(args);

    std::vector<Args> cases;
    for (const char* variant : {"full", "nocert", "nopad", "noproto", "nopublicrefresh"}) {
        Args c = args;
        c.attack_suite = false;
        c.scheme = "loci";
        c.variant = variant;
        cases.push_back(c);
    }
    Args pgm_naive = args;
    pgm_naive.attack_suite = false;
    pgm_naive.scheme = "pgm";
    pgm_naive.variant = "naive";
    cases.push_back(pgm_naive);

    Args pgm_global = args;
    pgm_global.attack_suite = false;
    pgm_global.scheme = "pgm";
    pgm_global.variant = "globalpad";
    cases.push_back(pgm_global);

    Args fixed = args;
    fixed.attack_suite = false;
    fixed.scheme = "fixedcell";
    fixed.variant = "bitmap";
    cases.push_back(fixed);

    Args fbdsse = args;
    fbdsse.attack_suite = false;
    fbdsse.scheme = "fbdsse";
    fbdsse.variant = "treecover";
    cases.push_back(fbdsse);

    std::cout << "LOCI leakage attack suite\n";
    std::cout << "N=" << args.N << " ops=" << args.ops << " U=" << args.U
              << " workload=" << args.workload << " crypto=" << args.crypto << '\n';
    std::cout << std::fixed << std::setprecision(3);
    print_attack_suite_header();
    for (const auto& c : cases) {
        auto result = run_config(c, records);
        print_attack_suite_row(c, result);
        write_result_csv(c, result);
    }
    std::cout << "All suite correctness checks passed.\n";
    return 0;
}

int main(int argc, char** argv) {
    try {
        Args args = parse(argc, argv);
        if (args.attack_suite) return run_attack_suite(args);
        return run_single(args);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << '\n';
        return 1;
    }
}
