#!/usr/bin/env python3
"""Build paper-facing summaries from artifact_results_sp/normalized/master_long.csv."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


SUMMARY_FIELDS = [
    "paper_fig",
    "benchmark_group",
    "profile",
    "dataset",
    "workload",
    "scheme",
    "variant",
    "N",
    "ops",
    "query_ratio",
    "update_ratio",
    "budget",
    "selectivity",
    "metric_name",
    "metric_unit",
    "metric_source",
    "evaluator",
    "auc_mode",
    "is_paper_metric",
    "mean",
    "std",
    "min",
    "max",
    "sample_count",
    "seeds",
    "source_csv",
    "source_row_id",
    "source_archive_or_run_id",
    "config_file",
    "config_hash",
    "notes",
]


SUMMARY_FILES = {
    "fig6_mechanism": "fig6_mechanism_summary.csv",
    "fig7_attack_auc": "fig7_attack_auc_summary.csv",
    "fig8_absolute_cost": "fig8_absolute_cost_summary.csv",
    "fig9_scale_select": "fig9_scale_selectivity_summary.csv",
    "fig10_workload": "fig10_workload_robustness_summary.csv",
    "fig11_real_trace": "fig11_real_trace_summary.csv",
    "fig12_budget": "fig12_budget_sensitivity_summary.csv",
}


TABLE2_METRICS = {
    "layout_shape_auc",
    "patch_pressure_auc",
    "maintenance_cause_auc",
    "layout_shape_adv_auc",
    "patch_pressure_adv_auc",
    "maintenance_cause_adv_auc",
    "max_cert_probe_auc",
    "search_latency_ms",
    "patch_update_latency_ms",
    "response_mib",
    "server_storage_mib",
    "maintenance_latency_ms",
    "refresh_count",
    "scheduled_refresh_count",
    "forced_rollover_count",
}

RESIDUAL_SUMMARY_FIELDS = [
    "profile",
    "view",
    "scheme",
    "dataset",
    "workload",
    "N",
    "ops",
    "seed_count",
    "task",
    "raw_auc_mean",
    "raw_auc_std",
    "adv_auc_mean",
    "adv_auc_std",
    "feature_scope",
    "interpretation",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_custom_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: str) -> float | None:
    try:
        x = float(value)
    except Exception:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def compact_values(values: list[str]) -> str:
    clean = sorted({v for v in values if v != ""})
    return ";".join(clean)


def compact_source_ids(values: list[str]) -> str:
    clean = sorted({v for v in values if v != ""})
    if not clean:
        return ""
    if len(clean) <= 12:
        return ";".join(clean)
    return f"count={len(clean)};first={clean[0]};last={clean[-1]}"


def aggregate(rows: list[dict[str, str]], *, force_paper_fig: str | None = None, force_group: str | None = None, extra_note: str = "") -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    key_fields = [
        "paper_fig",
        "benchmark_group",
        "profile",
        "dataset",
        "workload",
        "scheme",
        "variant",
        "N",
        "ops",
        "query_ratio",
        "update_ratio",
        "budget",
        "selectivity",
        "metric_name",
        "metric_unit",
        "metric_source",
        "evaluator",
        "auc_mode",
        "is_paper_metric",
    ]
    for row in rows:
        patched = dict(row)
        if force_paper_fig is not None:
            patched["paper_fig"] = force_paper_fig
        if force_group is not None:
            patched["benchmark_group"] = force_group
        grouped[tuple(patched.get(k, "") for k in key_fields)].append(patched)

    out: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        vals = [v for v in (as_float(item.get("metric_value", "")) for item in items) if v is not None]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / len(vals)
        base = {field: value for field, value in zip(key_fields, key)}
        notes = compact_values([item.get("notes", "") for item in items])
        if extra_note:
            notes = ";".join([part for part in [notes, extra_note] if part])
        base.update(
            {
                "mean": repr(mean),
                "std": repr(math.sqrt(var)),
                "min": repr(min(vals)),
                "max": repr(max(vals)),
                "sample_count": str(len(vals)),
                "seeds": ",".join(sorted({item.get("seed", "") for item in items if item.get("seed", "") != ""}, key=lambda x: int(float(x)) if x.replace(".", "", 1).isdigit() else x)),
                "source_csv": compact_values([item.get("source_csv", "") for item in items]),
                "source_row_id": compact_source_ids([item.get("source_row_id", "") for item in items]),
                "source_archive_or_run_id": compact_values([item.get("source_archive_or_run_id", "") for item in items]),
                "config_file": compact_values([item.get("config_file", "") for item in items]),
                "config_hash": compact_values([item.get("config_hash", "") for item in items]),
                "notes": notes,
            }
        )
        out.append(base)
    return out


def append_touch_skew(master_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    key_fields = [
        "paper_fig",
        "benchmark_group",
        "profile",
        "source_csv",
        "config_file",
        "config_hash",
        "seed",
        "dataset",
        "workload",
        "scheme",
        "variant",
        "N",
        "ops",
        "query_ratio",
        "update_ratio",
        "budget",
        "selectivity",
    ]
    for row in master_rows:
        if row.get("paper_fig") == "fig6_mechanism" and row.get("metric_name") == "update_touches":
            groups[tuple(row.get(k, "") for k in key_fields)].append(row)
    derived: list[dict[str, str]] = []
    for _, items in groups.items():
        values = sorted(v for v in (as_float(item.get("metric_value", "")) for item in items) if v is not None)
        if not values:
            continue
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
        skew = max(values) / median if median > 0 else 0.0
        row = dict(items[0])
        row.update(
            {
                "metric_name": "touch_skew",
                "metric_value": repr(skew),
                "metric_unit": "ratio",
                "metric_source": "derived",
                "evaluator": "derived_summary",
                "auc_mode": "not_auc",
                "is_paper_metric": "true",
                "source_row_id": compact_source_ids([item.get("source_row_id", "") for item in items]),
                "notes": "derived_from=update_touches; value=max_cell_touches/median_cell_touches",
            }
        )
        derived.append(row)
    return master_rows + derived


def make_table2(master_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in master_rows
        if row.get("profile") == "paper_full"
        and row.get("paper_fig") in {"fig7_attack_auc", "fig8_absolute_cost"}
        and row.get("metric_name") in TABLE2_METRICS
        and row.get("is_paper_metric") == "true"
    ]
    return aggregate(
        rows,
        force_paper_fig="table2_summary",
        force_group="derived",
        extra_note="derived_from=fig2_attack_eval.py+fig2_component_ablation/bench_wide.csv; not_independent_benchmark=true",
    )


def metric_task(metric_name: str) -> tuple[str, str] | None:
    mapping = {
        "density_lcert_auc": ("residual_density", "raw"),
        "density_lcert_adv_auc": ("residual_density", "adv"),
        "hotspot_lcert_auc": ("residual_hotspot", "raw"),
        "hotspot_lcert_adv_auc": ("residual_hotspot", "adv"),
        "adjacency_lcert_auc": ("residual_adjacency", "raw"),
        "adjacency_lcert_adv_auc": ("residual_adjacency", "adv"),
    }
    return mapping.get(metric_name)


def mean_std(values: list[float]) -> tuple[str, str]:
    if not values:
        return "", ""
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return repr(mean), repr(math.sqrt(var))


def make_residual_summary(master_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = defaultdict(lambda: {"raw": [], "adv": [], "seeds": set(), "notes": []})
    key_fields = [
        "profile",
        "view",
        "scheme",
        "dataset",
        "workload",
        "N",
        "ops",
        "task",
        "feature_scope",
        "interpretation",
    ]
    for row in master_rows:
        if row.get("paper_fig") != "residual_lcert_probe":
            continue
        task_kind = metric_task(row.get("metric_name", ""))
        if task_kind is None:
            continue
        task, kind = task_kind
        patched = dict(row)
        patched["task"] = patched.get("task") or task
        key = tuple(patched.get(field, "") for field in key_fields)
        value = as_float(row.get("metric_value", ""))
        if value is not None:
            grouped[key][kind].append(value)
        if row.get("seed", ""):
            grouped[key]["seeds"].add(row.get("seed", ""))
        if row.get("notes", ""):
            grouped[key]["notes"].append(row.get("notes", ""))

    out: list[dict[str, Any]] = []
    for key, payload in sorted(grouped.items()):
        base = {field: value for field, value in zip(key_fields, key)}
        raw_mean, raw_std = mean_std(payload["raw"])
        adv_mean, adv_std = mean_std(payload["adv"])
        interpretation = base.get("interpretation", "")
        notes = compact_values(payload["notes"])
        if base.get("task") == "residual_adjacency" and "not_a_violation_of_transcript_discipline" not in interpretation:
            interpretation = ";".join([part for part in [interpretation, "not_a_violation_of_transcript_discipline"] if part])
        out.append(
            {
                "profile": base.get("profile", ""),
                "view": base.get("view", ""),
                "scheme": base.get("scheme", ""),
                "dataset": base.get("dataset", ""),
                "workload": base.get("workload", ""),
                "N": base.get("N", ""),
                "ops": base.get("ops", ""),
                "seed_count": str(len(payload["seeds"])),
                "task": base.get("task", ""),
                "raw_auc_mean": raw_mean,
                "raw_auc_std": raw_std,
                "adv_auc_mean": adv_mean,
                "adv_auc_std": adv_std,
                "feature_scope": base.get("feature_scope", ""),
                "interpretation": interpretation,
                "notes": notes,
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=Path("artifact_results_sp"))
    parser.add_argument("--profile", choices=["paper_full", "quick", "all"], default="all", help="Accepted for reproducibility scripts; summaries remain combined across available profiles.")
    args = parser.parse_args()

    master_path = args.artifact_root / "normalized" / "master_long.csv"
    master_rows = append_touch_skew(read_csv(master_path))
    summary_dir = args.artifact_root / "summaries"

    for paper_fig, filename in SUMMARY_FILES.items():
        rows = [row for row in master_rows if row.get("paper_fig") == paper_fig]
        write_csv(summary_dir / filename, aggregate(rows))
    write_csv(summary_dir / "table2_summary.csv", make_table2(master_rows))
    write_custom_csv(summary_dir / "residual_lcert_probe_summary.csv", make_residual_summary(master_rows), RESIDUAL_SUMMARY_FIELDS)
    print(f"wrote summaries to {summary_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
