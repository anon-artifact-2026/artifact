#!/usr/bin/env python3
"""Evaluate transcript-only inference attacks against exported LOCI traces.

The script treats search/update/maintenance traces as server-visible input.
Private labels from layout_units.csv are used only after scoring, to compute
precision@k and AUC-style evaluation metrics.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path


def split_units(value: str) -> list[str]:
    if not value:
        return []
    return [x for x in value.split(";") if x]


def label_score(value: str) -> float:
    labels = {"none": 0.0, "low": 1.0, "mid": 2.0, "high": 3.0}
    if value in labels:
        return labels[value]
    try:
        return float(value)
    except ValueError:
        return 0.0


def numeric(row: dict[str, str], name: str, default: float = 0.0) -> float:
    value = row.get(name, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def parse_region(row: dict[str, str]) -> tuple[float, float] | None:
    lo = row.get("region_lo", "")
    hi = row.get("region_hi", "")
    if lo != "" and hi != "":
        try:
            return float(lo), float(hi)
        except ValueError:
            pass
    label = row.get("hidden_region_label", "")
    if "-" not in label:
        return None
    left, right = label.split("-", 1)
    try:
        return float(left), float(right)
    except ValueError:
        return None


def hotspot_region(dataset: str) -> tuple[float, float] | None:
    if "hotspot" not in dataset:
        return None
    match = re.search(r"-U(\d+)", dataset)
    if not match:
        return None
    universe = float(match.group(1))
    center = universe / 3.0
    width = max(1.0, universe / 100.0)
    return center - width, center + width


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def top_k_indices(values: list[float], k: int) -> list[int]:
    return sorted(range(len(values)), key=lambda i: (-values[i], i))[:k]


def precision_at_k(pred: list[float], truth: list[float], k: int) -> float:
    if not pred or len(pred) != len(truth) or k <= 0:
        return 0.0
    k = min(k, len(pred))
    p = set(top_k_indices(pred, k))
    t = set(top_k_indices(truth, k))
    return len(p & t) / float(k)


def auc_top_truth(pred: list[float], truth: list[float], positives: int) -> float:
    if not pred or len(pred) != len(truth) or positives <= 0 or positives >= len(pred):
        return 0.0
    pos = set(top_k_indices(truth, positives))
    wins = 0.0
    pairs = 0.0
    for i in range(len(pred)):
        if i not in pos:
            continue
        for j in range(len(pred)):
            if j in pos:
                continue
            if pred[i] > pred[j]:
                wins += 1.0
            elif pred[i] == pred[j]:
                wins += 0.5
            pairs += 1.0
    return wins / pairs if pairs else 0.0


def auc_binary(pred: list[float], truth: list[float]) -> float:
    if not pred or len(pred) != len(truth):
        return 0.0
    pos = [i for i, y in enumerate(truth) if y > 0.0]
    neg = [i for i, y in enumerate(truth) if y <= 0.0]
    if not pos or not neg:
        return 0.0
    wins = 0.0
    pairs = 0.0
    for i in pos:
        for j in neg:
            if pred[i] > pred[j]:
                wins += 1.0
            elif pred[i] == pred[j]:
                wins += 0.5
            pairs += 1.0
    return wins / pairs if pairs else 0.0


def auc_metric(pred: list[float], truth: list[float], k: int) -> float:
    positive_values = {y for y in truth if y > 0.0}
    nonpositive = any(y <= 0.0 for y in truth)
    if 0 < len(positive_values) <= 2 and nonpositive:
        return auc_binary(pred, truth)
    return auc_top_truth(pred, truth, k)


def corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx == 0.0 or dy == 0.0:
        return 0.0
    return num / math.sqrt(dx * dy)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def add_feature(features, key, name: str, value: float) -> None:
    features[key][name] += value


def max_feature(features, key, name: str, value: float) -> None:
    features[key][name] = max(features[key][name], value)


def evaluate(trace_dir: Path, top_k: int | None) -> list[dict[str, object]]:
    features = defaultdict(lambda: defaultdict(float))

    for row in read_csv(trace_dir / "search_trace.csv"):
        units = split_units(row.get("touched_units", ""))
        if not units:
            continue
        share = 1.0 / len(units)
        bytes_seen = float(row.get("object_bytes") or 0)
        token_count = float(row.get("token_count") or 0)
        for unit in units:
            key = (row["scheme"], row["dataset"], unit)
            add_feature(features, key, "search_touches", 1.0)
            add_feature(features, key, "object_bytes", bytes_seen * share)
            add_feature(features, key, "token_pressure", token_count * share)

    for row in read_csv(trace_dir / "update_trace.csv"):
        units = split_units(row.get("touched_unit", ""))
        for unit in units:
            key = (row["scheme"], row["dataset"], unit)
            add_feature(features, key, "update_touches", 1.0)
            add_feature(features, key, "update_bytes", float(row.get("update_bytes") or 0))
            raw = row.get("raw_log_len_visible", "")
            if raw:
                try:
                    max_feature(features, key, "visible_log_len", float(raw))
                except ValueError:
                    pass

    for row in read_csv(trace_dir / "maintenance_trace.csv"):
        units = split_units(row.get("touched_units", ""))
        for unit in units:
            key = (row["scheme"], row["dataset"], unit)
            add_feature(features, key, "maintenance_events", 1.0)
            trigger = row.get("raw_trigger_visible", "")
            if trigger:
                add_feature(features, key, "visible_private_maintenance", 1.0)
            if trigger == "log_full":
                add_feature(features, key, "visible_log_full_triggers", 1.0)
            elif trigger in {"capacity", "manual", "load"}:
                add_feature(features, key, "visible_capacity_triggers", 1.0)

    layout = read_csv(trace_dir / "layout_units.csv")
    grouped: dict[tuple[str, str], list[tuple[dict[str, float], dict[str, str]]]] = defaultdict(list)
    for row in layout:
        key = (row["scheme"], row["dataset"], row["unit_id"])
        grouped[(row["scheme"], row["dataset"])].append((features[key], row))

    results: list[dict[str, object]] = []
    for (scheme, dataset), rows in sorted(grouped.items()):
        if not rows:
            continue
        n = len(rows)
        k = top_k if top_k is not None else max(1, (n + 4) // 5)
        k = min(k, n)

        hot_region = hotspot_region(dataset)
        region_truth: list[float] = []
        for _, r in rows:
            region = parse_region(r)
            if hot_region and region:
                region_truth.append(1.0 if overlaps(region, hot_region) else 0.0)
            else:
                region_truth.append(numeric(r, "true_load", label_score(r.get("hidden_load_label", ""))))

        load_truth = [numeric(r, "true_load", label_score(r.get("hidden_load_label", ""))) for _, r in rows]
        hotspot_truth = [numeric(r, "true_update_touches", label_score(r.get("update_intensity_label", ""))) for _, r in rows]
        log_truth = [numeric(r, "true_log_used") for _, r in rows]
        maintenance_truth = [
            numeric(r, "private_maintenance_events", numeric(r, "private_log_full_events"))
            for _, r in rows
        ]
        distinct_truth = [numeric(r, "distinct_values") for _, r in rows]

        region_pred = [
            f["search_touches"]
            + 0.001 * f["object_bytes"]
            + 0.01 * f["token_pressure"]
            + f["visible_log_len"]
            + 2.0 * f["visible_private_maintenance"]
            for f, _ in rows
        ]
        load_pred = [
            f["search_touches"] + 0.001 * f["object_bytes"] + 0.01 * f["token_pressure"]
            for f, _ in rows
        ]
        layout_class_pred = [numeric(r, "unit_class") for _, r in rows]
        hotspot_pred = [f["update_touches"] for f, _ in rows]
        hotspot_log_pred = [f["visible_log_len"] for f, _ in rows]
        log_pred = [f["visible_log_len"] for f, _ in rows]
        maintenance_pred = [
            f["visible_private_maintenance"] + f["visible_log_full_triggers"] + f["visible_capacity_triggers"]
            for f, _ in rows
        ]

        results.append(
            {
                "scheme": scheme,
                "dataset": dataset,
                "units": n,
                "top_k": k,
                "region_precision_at_k": precision_at_k(region_pred, region_truth, k),
                "hotspot_precision_at_k": precision_at_k(hotspot_pred, hotspot_truth, k),
                "hotspot_log_precision_at_k": precision_at_k(hotspot_log_pred, hotspot_truth, k),
                "layout_class_precision_at_k": precision_at_k(layout_class_pred, load_truth, k),
                "distinct_precision_at_k": precision_at_k(region_pred, distinct_truth, k),
                "region_auc": auc_metric(region_pred, region_truth, k),
                "load_auc": auc_metric(load_pred, load_truth, k),
                "layout_class_auc": auc_metric(layout_class_pred, load_truth, k),
                "hotspot_auc": auc_metric(hotspot_pred, hotspot_truth, k),
                "hotspot_log_auc": auc_metric(hotspot_log_pred, hotspot_truth, k),
                "log_growth_auc": auc_metric(log_pred, hotspot_truth, k),
                "maintenance_auc": auc_metric(maintenance_pred, maintenance_truth, k),
                "log_correlation": corr(log_pred, hotspot_truth),
                "log_truth_correlation": corr(log_pred, log_truth),
                "maintenance_correlation": corr(maintenance_pred, maintenance_truth),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()

    rows = evaluate(args.trace_dir, args.top_k)
    fields = [
        "scheme",
        "dataset",
        "units",
        "top_k",
        "region_precision_at_k",
        "hotspot_precision_at_k",
        "hotspot_log_precision_at_k",
        "layout_class_precision_at_k",
        "distinct_precision_at_k",
        "region_auc",
        "load_auc",
        "layout_class_auc",
        "hotspot_auc",
        "hotspot_log_auc",
        "log_growth_auc",
        "maintenance_auc",
        "log_correlation",
        "log_truth_correlation",
        "maintenance_correlation",
    ]

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    writer = csv.DictWriter(__import__("sys").stdout, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
