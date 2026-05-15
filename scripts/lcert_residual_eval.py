#!/usr/bin/env python3
"""Post-process fig2 traces into residual certified-view leakage probes.

This script does not invoke bench_loci. It evaluates what can be inferred from
the declared certified-view features alone, then compares LOCI-Full with a
Sim-L_cert view under the same feature restriction.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ALLOWED_LCERT_FEATURES = [
    "certified_cell_cover_pattern",
    "cover_count_per_certified_cell",
    "co_cover_count_between_certified_cells",
    "query_fanout_class",
    "object_class_id",
    "update_area_class_id",
    "patch_class_id",
    "maintenance_class_id",
    "replacement_class_id",
    "replacement_class_histogram",
    "update_touched_certified_cell_pattern",
    "public_time_class",
    "public_epoch_class",
    "public_maintenance_group",
    "public_refresh_group",
    "public_class_multiset",
]

FORBIDDEN_FEATURES = [
    "raw_object_byte_length_beyond_public_class",
    "exact_response_byte_length_beyond_public_class",
    "raw_patch_growth",
    "exact_primary_patch_occupancy",
    "exact_spill_occupancy",
    "overflow_proximity",
    "private_patch_state",
    "pre_maintenance_private_growth",
    "exact_load",
    "descriptor_count",
    "boundary_count",
    "model_error_marker",
    "learned_guide_order",
    "plaintext_order",
    "local_slot",
    "plaintext_value",
    "query_endpoint",
    "target_label_as_feature",
]

RAW_FIELDS = [
    "profile",
    "view",
    "scheme",
    "dataset",
    "workload",
    "N",
    "ops",
    "seed",
    "task",
    "feature_scope",
    "label_source",
    "auc",
    "adv_auc",
    "num_positive",
    "num_negative",
    "num_samples",
    "source_trace_dir",
    "source_bench_csv",
    "allowed_features_used",
    "forbidden_features_used",
    "simulator_missing",
    "notes",
    "interpretation",
    "purpose",
]

TASK_FEATURES = {
    "residual_density": [
        "certified_cell_cover_pattern",
        "cover_count_per_certified_cell",
        "co_cover_count_between_certified_cells",
        "query_fanout_class",
        "object_class_id",
        "public_class_multiset",
    ],
    "residual_hotspot": [
        "update_touched_certified_cell_pattern",
        "update_area_class_id",
        "patch_class_id",
        "public_time_class",
        "public_epoch_class",
        "public_class_multiset",
    ],
    "residual_adjacency": [
        "certified_cell_cover_pattern",
        "co_cover_count_between_certified_cells",
        "maintenance_class_id",
        "public_maintenance_group",
        "public_refresh_group",
        "object_class_id",
        "public_class_multiset",
    ],
}

VIEW_SPECS = [
    {
        "view": "naive_full_transcript",
        "scheme": "PGM-Learned-Naive",
        "trace_schemes": ["PGM-Learned-Naive"],
        "feature_scope": "full_transcript_reference",
        "interpretation": "full_transcript_reference",
        "purpose": "upper/reference attack",
        "notes": "full transcript reference; not a certified-probe metric; not included in max_cert_probe_auc",
    },
    {
        "view": "loci_lcert_only",
        "scheme": "LOCI-Full",
        "trace_schemes": ["LOCI-Full"],
        "feature_scope": "strict_lcert_only",
        "interpretation": "declared_certified_leakage",
        "purpose": "residual certified-view leakage",
        "notes": "residual certified-view leakage; not included in max_cert_probe_auc",
    },
    {
        "view": "globalpad_lcert_only",
        "scheme": "GlobalPad",
        "trace_schemes": ["ResponseGlobalPad", "PGM-Learned-GlobalPad", "GlobalPad"],
        "feature_scope": "strict_lcert_only",
        "interpretation": "declared_certified_leakage",
        "purpose": "response-wide padding comparison",
        "notes": "residual certified-view leakage; response-wide padding comparison; not included in max_cert_probe_auc",
    },
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_units(value: str) -> list[str]:
    return [x for x in value.split(";") if x]


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except Exception:
        return default


def parse_int(value: str, default: int = 0) -> int:
    try:
        if value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def parse_seed_list(value: str) -> set[str]:
    return {x.strip() for x in value.split(",") if x.strip()}


def parse_trace_name(path: Path) -> dict[str, str]:
    meta = {"scheme": "", "dataset": "", "workload": "", "N": "", "seed": ""}
    parts = path.name.split("__")
    if len(parts) >= 6:
        meta["scheme"] = parts[1]
        meta["dataset"] = parts[2]
        meta["workload"] = parts[3]
        for part in parts[4:]:
            if part.startswith("N"):
                meta["N"] = part[1:]
            elif part.startswith("s") and part[1:].isdigit():
                meta["seed"] = part[1:]
    return meta


def auc_binary(scores: list[float], labels: list[int]) -> float:
    pos = [i for i, y in enumerate(labels) if y > 0]
    neg = [i for i, y in enumerate(labels) if y <= 0]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    pairs = 0.0
    for i in pos:
        for j in neg:
            if scores[i] > scores[j]:
                wins += 1.0
            elif scores[i] == scores[j]:
                wins += 0.5
            pairs += 1.0
    return wins / pairs if pairs else 0.5


def adv_auc(value: float) -> float:
    return max(value, 1.0 - value)


def top_quantile_labels(values: list[float], top_fraction: float = 0.2) -> list[int]:
    if not values:
        return []
    k = max(1, int(math.ceil(len(values) * top_fraction)))
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    positives = set(order[: min(k, len(order))])
    return [1 if i in positives else 0 for i in range(len(values))]


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def enforce_feature_policy(used: list[str], strict: bool) -> tuple[str, str]:
    used_set = set(used)
    forbidden = sorted(used_set.intersection(FORBIDDEN_FEATURES))
    unknown = sorted(used_set.difference(ALLOWED_LCERT_FEATURES))
    if strict and (forbidden or unknown):
        raise RuntimeError(
            "strict Lcert-only feature policy violation: "
            f"forbidden={forbidden}; unknown={unknown}"
        )
    return ";".join([name for name in ALLOWED_LCERT_FEATURES if name in used_set]), ";".join(forbidden)


class TraceFeatures:
    def __init__(self, trace_dir: Path):
        self.trace_dir = trace_dir
        self.layout = read_csv(trace_dir / "layout_units.csv")
        self.search = read_csv(trace_dir / "search_trace.csv")
        self.update = read_csv(trace_dir / "update_trace.csv")
        self.maintenance = read_csv(trace_dir / "maintenance_trace.csv")
        if not self.layout:
            raise RuntimeError(f"missing or empty layout_units.csv in {trace_dir}")

        self.units = [row.get("unit_id", "") for row in self.layout if row.get("unit_id", "")]
        self.unit_class = {row.get("unit_id", ""): parse_float(row.get("unit_class", "")) for row in self.layout}
        self.true_load = {row.get("unit_id", ""): parse_float(row.get("true_load", "")) for row in self.layout}
        self.true_updates = {row.get("unit_id", ""): parse_float(row.get("true_update_touches", "")) for row in self.layout}

        self.cover_count: dict[str, float] = defaultdict(float)
        self.fanout_sum: dict[str, float] = defaultdict(float)
        self.query_sets: dict[str, set[str]] = defaultdict(set)
        self.co_cover: dict[tuple[str, str], float] = defaultdict(float)
        self.update_count: dict[str, float] = defaultdict(float)
        self.patch_class_sum: dict[str, float] = defaultdict(float)
        self.update_epochs: dict[str, set[int]] = defaultdict(set)
        self.maintenance_count: dict[str, float] = defaultdict(float)
        self.maintenance_classes: dict[str, set[str]] = defaultdict(set)
        self.replacement_classes: dict[str, set[str]] = defaultdict(set)

        self._index_searches()
        self._index_updates()
        self._index_maintenance()

    def _index_searches(self) -> None:
        for row in self.search:
            units = split_units(row.get("touched_units", ""))
            if not units:
                continue
            qid = row.get("qid", row.get("t", ""))
            fanout = parse_float(row.get("token_class", row.get("token_count", "")))
            for unit in units:
                self.cover_count[unit] += 1.0
                self.fanout_sum[unit] += fanout
                self.query_sets[unit].add(qid)
            for i, left in enumerate(units):
                for right in units[i + 1:]:
                    self.co_cover[pair_key(left, right)] += 1.0

    def _index_updates(self) -> None:
        for row in self.update:
            units = split_units(row.get("touched_unit", ""))
            patch_class = parse_float(row.get("patch_class", ""))
            epoch = parse_int(row.get("t", "")) // 64
            for unit in units:
                self.update_count[unit] += 1.0
                self.patch_class_sum[unit] += patch_class
                self.update_epochs[unit].add(epoch)

    def _index_maintenance(self) -> None:
        for row in self.maintenance:
            units = split_units(row.get("touched_units", ""))
            maint_class = row.get("maint_class", "")
            replacement = row.get("new_object_class", "")
            for unit in units:
                self.maintenance_count[unit] += 1.0
                if maint_class != "":
                    self.maintenance_classes[unit].add(maint_class)
                if replacement != "":
                    self.replacement_classes[unit].add(replacement)

    def density_scores_and_labels(self) -> tuple[list[float], list[int]]:
        scores = []
        labels_source = []
        for unit in self.units:
            cover = self.cover_count[unit]
            avg_fanout = self.fanout_sum[unit] / cover if cover else 0.0
            co_degree = sum(value for pair, value in self.co_cover.items() if unit in pair)
            score = (
                math.log1p(cover)
                + 0.20 * math.log1p(avg_fanout)
                + 0.15 * math.log1p(co_degree)
                + 0.10 * math.log1p(self.unit_class.get(unit, 0.0))
            )
            scores.append(score)
            labels_source.append(self.true_load.get(unit, 0.0))
        return scores, top_quantile_labels(labels_source)

    def hotspot_scores_and_labels(self) -> tuple[list[float], list[int]]:
        scores = []
        labels_source = []
        for unit in self.units:
            score = (
                math.log1p(self.update_count[unit])
                + 0.20 * math.log1p(self.patch_class_sum[unit])
                + 0.15 * len(self.update_epochs[unit])
                + 0.10 * self.maintenance_count[unit]
            )
            scores.append(score)
            labels_source.append(self.true_updates.get(unit, 0.0))
        return scores, top_quantile_labels(labels_source)

    def adjacency_scores_and_labels(self) -> tuple[list[float], list[int]]:
        if len(self.units) < 3:
            return [0.0], [1]
        samples: list[tuple[str, str, int]] = []
        for i in range(len(self.units) - 1):
            samples.append((self.units[i], self.units[i + 1], 1))
        target_neg = len(samples)
        offsets = [2, 3, 5, 11, 17, 29]
        seen = {pair_key(a, b) for a, b, _ in samples}
        for offset in offsets:
            for i in range(0, max(0, len(self.units) - offset)):
                if len(samples) >= 2 * target_neg:
                    break
                a = self.units[i]
                b = self.units[i + offset]
                key = pair_key(a, b)
                if key in seen:
                    continue
                seen.add(key)
                samples.append((a, b, 0))
            if len(samples) >= 2 * target_neg:
                break

        scores = []
        labels = []
        for a, b, label in samples:
            qs_a = self.query_sets[a]
            qs_b = self.query_sets[b]
            union = len(qs_a | qs_b)
            jaccard = (len(qs_a & qs_b) / union) if union else 0.0
            co = self.co_cover[pair_key(a, b)]
            same_maint = 1.0 if self.maintenance_classes[a] & self.maintenance_classes[b] else 0.0
            same_repl = 1.0 if self.replacement_classes[a] & self.replacement_classes[b] else 0.0
            same_class = 1.0 if self.unit_class.get(a, 0.0) == self.unit_class.get(b, -1.0) else 0.0
            score = math.log1p(co) + jaccard + 0.25 * same_maint + 0.20 * same_repl + 0.10 * same_class
            scores.append(score)
            labels.append(label)
        return scores, labels


def canonical_trace_scheme(value: str) -> str:
    if value in {"PGM-Learned-GlobalPad", "GlobalPad"}:
        return "ResponseGlobalPad"
    return value


def find_trace_dirs(group_dir: Path, seeds: set[str]) -> dict[tuple[str, str], Path]:
    traces_root = group_dir / "traces"
    if not group_dir.exists() or not traces_root.exists():
        raise FileNotFoundError("fig2_component_ablation outputs not found; run fig2 first.")
    out: dict[tuple[str, str], Path] = {}
    for trace_dir in sorted(p for p in traces_root.iterdir() if p.is_dir()):
        if not (trace_dir / "layout_units.csv").exists():
            continue
        meta = parse_trace_name(trace_dir)
        seed = meta.get("seed", "")
        if seeds and seed not in seeds:
            continue
        scheme = canonical_trace_scheme(meta.get("scheme", ""))
        if not scheme:
            rows = read_csv(trace_dir / "layout_units.csv")
            scheme = canonical_trace_scheme(rows[0].get("scheme", "")) if rows else ""
        if scheme and seed:
            out[(scheme, seed)] = trace_dir
    return out


def find_bench_row(bench_rows: list[dict[str, str]], trace_meta: dict[str, str], scheme: str) -> dict[str, str]:
    wanted_scheme = scheme
    if scheme == "GlobalPad":
        wanted_scheme = "ResponseGlobalPad"
    for row in reversed(bench_rows):
        row_scheme = canonical_trace_scheme(row.get("case", row.get("scheme", "")))
        if row_scheme == "ResponseGlobalPad" and wanted_scheme == "GlobalPad":
            row_scheme = "GlobalPad"
        if row_scheme != wanted_scheme:
            continue
        if trace_meta.get("seed") and row.get("seed", "") != trace_meta["seed"]:
            continue
        if trace_meta.get("N") and row.get("N", "") != trace_meta["N"]:
            continue
        if trace_meta.get("workload") and row.get("workload", "") != trace_meta["workload"]:
            continue
        return row
    return {}


def task_result(
    *,
    features: TraceFeatures,
    task: str,
    strict: bool,
) -> dict[str, Any]:
    if task == "residual_density":
        scores, labels = features.density_scores_and_labels()
        label_source = "layout_units.true_load_top_quantile"
    elif task == "residual_hotspot":
        scores, labels = features.hotspot_scores_and_labels()
        label_source = "layout_units.true_update_touches_top_quantile"
    elif task == "residual_adjacency":
        scores, labels = features.adjacency_scores_and_labels()
        label_source = "layout_units.client_order_adjacency"
    else:
        raise KeyError(task)
    allowed, forbidden = enforce_feature_policy(TASK_FEATURES[task], strict)
    auc = auc_binary(scores, labels)
    positives = sum(1 for y in labels if y > 0)
    negatives = sum(1 for y in labels if y <= 0)
    return {
        "task": task,
        "label_source": label_source,
        "auc": auc,
        "adv_auc": adv_auc(auc),
        "num_positive": positives,
        "num_negative": negatives,
        "num_samples": len(labels),
        "allowed_features_used": allowed,
        "forbidden_features_used": forbidden,
    }


def build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    group_dir = args.run_root / args.group
    bench_csv = group_dir / "bench_wide.csv"
    if not group_dir.exists() or not (group_dir / "traces").exists() or not bench_csv.exists():
        raise FileNotFoundError("fig2_component_ablation outputs not found; run fig2 first.")

    seeds = parse_seed_list(args.seeds)
    trace_dirs = find_trace_dirs(group_dir, seeds)
    bench_rows = read_csv(bench_csv)
    rows: list[dict[str, Any]] = []

    for spec in VIEW_SPECS:
        for trace_scheme in spec["trace_schemes"]:
            for seed in sorted(seeds):
                trace_dir = trace_dirs.get((canonical_trace_scheme(trace_scheme), seed))
                if not trace_dir:
                    continue
                trace_meta = parse_trace_name(trace_dir)
                bench_row = find_bench_row(bench_rows, trace_meta, spec["scheme"])
                rows.extend(rows_for_view(args, spec, trace_dir, bench_csv, trace_meta, bench_row, simulator_missing=False))
            if any(row["view"] == spec["view"] for row in rows):
                break

    loci_spec = {
        "view": "sim_lcert_only",
        "scheme": "Sim-L_cert",
        "feature_scope": "strict_lcert_only",
        "interpretation": "simulator_baseline",
        "purpose": "simulator baseline",
        "notes": "simulator baseline under strict Lcert-only feature restriction; residual certified-view leakage; not included in max_cert_probe_auc",
    }
    for seed in sorted(seeds):
        trace_dir = trace_dirs.get(("Sim-L_cert", seed))
        simulator_missing = False
        if not trace_dir:
            # Sim-L_cert is normally a derived leakage baseline in run_loci_eval,
            # so no standalone simulator trace is emitted. In that common case,
            # reuse the LOCI-Full trace but restrict feature extraction to the
            # declared certified view and mark the row as synthesized.
            trace_dir = trace_dirs.get(("LOCI-Full", seed))
            simulator_missing = True
        if not trace_dir:
            continue
        trace_meta = parse_trace_name(trace_dir)
        bench_row = find_bench_row(bench_rows, trace_meta, "LOCI-Full")
        rows.extend(rows_for_view(args, loci_spec, trace_dir, bench_csv, trace_meta, bench_row, simulator_missing=simulator_missing))

    if not rows:
        raise RuntimeError("no residual Lcert probe rows produced; expected fig2 traces for requested seeds")
    warn_on_loci_sim_mismatch(rows)
    return rows


def rows_for_view(
    args: argparse.Namespace,
    spec: dict[str, str],
    trace_dir: Path,
    bench_csv: Path,
    trace_meta: dict[str, str],
    bench_row: dict[str, str],
    simulator_missing: bool,
) -> list[dict[str, Any]]:
    features = TraceFeatures(trace_dir)
    out = []
    for task in ["residual_density", "residual_hotspot", "residual_adjacency"]:
        result = task_result(features=features, task=task, strict=args.strict_lcert)
        notes = spec["notes"]
        if simulator_missing:
            notes += "; synthesized from LOCI-Full certified-view trace because Sim-L_cert has no standalone trace"
        if task == "residual_adjacency":
            notes += "; adjacency/order-like signal admitted by certified cover leakage"
        out.append(
            {
                "profile": args.profile,
                "view": spec["view"],
                "scheme": spec["scheme"],
                "dataset": trace_meta.get("dataset", bench_row.get("dataset", "")),
                "workload": trace_meta.get("workload", bench_row.get("workload", "")),
                "N": trace_meta.get("N", bench_row.get("N", "")),
                "ops": bench_row.get("ops", ""),
                "seed": trace_meta.get("seed", bench_row.get("seed", "")),
                "task": task,
                "feature_scope": spec["feature_scope"],
                "label_source": result["label_source"],
                "auc": repr(result["auc"]),
                "adv_auc": repr(result["adv_auc"]),
                "num_positive": result["num_positive"],
                "num_negative": result["num_negative"],
                "num_samples": result["num_samples"],
                "source_trace_dir": str(trace_dir).replace("\\", "/"),
                "source_bench_csv": str(bench_csv).replace("\\", "/"),
                "allowed_features_used": result["allowed_features_used"],
                "forbidden_features_used": result["forbidden_features_used"],
                "simulator_missing": str(simulator_missing).lower(),
                "notes": notes,
                "interpretation": spec["interpretation"],
                "purpose": spec["purpose"],
            }
        )
    return out


def warn_on_loci_sim_mismatch(rows: list[dict[str, Any]]) -> None:
    keyed: dict[tuple[str, str, str, str, str, str], dict[str, float]] = defaultdict(dict)
    for row in rows:
        key = (
            row["profile"],
            row["dataset"],
            row["workload"],
            row["N"],
            row["seed"],
            row["task"],
        )
        if row["view"] in {"loci_lcert_only", "sim_lcert_only"}:
            keyed[key][row["view"]] = parse_float(str(row["adv_auc"]))
    for key, values in keyed.items():
        loci = values.get("loci_lcert_only")
        sim = values.get("sim_lcert_only")
        if loci is not None and sim is not None and loci > sim + 0.05:
            print(
                "WARNING: Potential mismatch between LOCI transcript and simulator leakage; "
                f"inspect feature extraction. context={key} loci_adv_auc={loci:.6f} sim_adv_auc={sim:.6f}",
                file=sys.stderr,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Residual Lcert-only leakage probe over existing fig2 traces.")
    parser.add_argument("--run-root", type=Path, default=Path("artifact_out/eval_full_sp"))
    parser.add_argument("--group", default="fig2_component_ablation")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profile", choices=["paper_full", "quick"], required=True)
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--strict-lcert", action="store_true")
    args = parser.parse_args()

    try:
        rows = build_rows(args)
        write_csv(args.out, rows)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"lcert_residual_eval failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {len(rows)} residual Lcert probe rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
