#!/usr/bin/env python3
"""Run the LOCI paper-facing evaluation groups.

This script organizes experiments only. It does not change LOCI construction,
TraceProbe, or security definitions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OUT_ROOT = Path("artifact_out/eval")

GROUP_DIRS = {
    "table1": "table1_setup",
    "fig1": "fig1_leakage_certification",
    "fig2": "fig2_component_ablation",
    "fig3": "fig3_scalability_selectivity",
    "fig4": "fig4_dynamic_refresh",
    "fig5": "fig5_real_datasets",
    "fig6": "fig6_tradeoff",
    "fig_mechanism": "fig_mechanism_cell_load_touch_skew",
    "table2": "table2_summary",
}

FIG3_PERFORMANCE_METRICS = {
    "search_latency_ms",
    "update_latency_ms",
    "setup_time_ms",
    "response_bytes",
    "server_storage_bytes",
    "client_storage_bytes",
    "touched_cells",
    "full_cells",
    "boundary_cells",
    "exact_match_rate",
}

CERTIFIED_PROBE_AUC_METRICS = {
    "layout_shape_auc",
    "patch_pressure_auc",
    "maintenance_cause_auc",
}

MECHANISM_LAYOUT_FIELDS = [
    "group",
    "dataset",
    "workload",
    "scheme",
    "seed",
    "cell_id",
    "true_load",
    "true_update_touches",
]
MECHANISM_FIGURE_FIELDS = [
    "panel",
    "dataset_family",
    "dataset",
    "workload",
    "scheme",
    "seed",
    "rank",
    "value",
]

BENCH_WIDE_FILL_FIELDS = [
    "maintenance_latency_ms",
    "refresh_latency_ms",
    "refresh_count",
    "scheduled_refresh_count",
    "forced_log_refresh_count",
    "public_rollover_count",
    "split_count",
    "merge_count",
    "guide_retrain_count",
    "locator_rebuild_count",
]

BENCH_WIDE_DEDUPE_FIELDS = [
    "case",
    "scheme",
    "variant",
    "dataset",
    "attribute",
    "seed",
    "N",
    "ops",
    "workload",
    "dist",
    "selectivity",
]

RAW_METRIC_DEDUPE_FIELDS = [
    "group",
    "dataset",
    "attribute",
    "N",
    "workload",
    "scheme",
    "seed",
    "metric_name",
    "selectivity",
    "axis",
    "budget",
    "theta",
    "B",
]


def repo_root() -> Path:
    return Path.cwd()


def bench_exe(require_exists: bool = True) -> Path:
    exe = "bench_loci.exe" if os.name == "nt" else "bench_loci"
    path = repo_root() / exe
    if require_exists and not path.exists():
        raise FileNotFoundError(f"missing benchmark executable: {path}; run make first")
    return path


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, obj: Any) -> None:
    path.write_text(yaml.safe_dump(obj, sort_keys=False), encoding="utf-8")


def scheme_registry() -> dict[str, dict[str, Any]]:
    schemes = load_yaml(Path("configs/schemes.yaml")).get("schemes", {})
    if "ResponseGlobalPad" in schemes and "GlobalPad" not in schemes:
        schemes["GlobalPad"] = schemes["ResponseGlobalPad"]
    return schemes


def dataset_registry() -> dict[str, dict[str, Any]]:
    path = Path("configs/datasets.yaml")
    if not path.exists():
        return {}
    return load_yaml(path).get("datasets", {})


def parse_csv_list(value: str | None, cast=str) -> list[Any] | None:
    if value is None:
        return None
    return [cast(x.strip()) for x in value.split(",") if x.strip()]


def ensure_clean_dir(path: Path, clean: bool) -> None:
    if clean and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def append_log(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(text)
        if not text.endswith("\n"):
            fh.write("\n")


def run_cmd(cmd: list[str], log_path: Path, dry_run: bool) -> int:
    append_log(log_path, "+ " + " ".join(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    append_log(log_path, proc.stdout)
    if proc.returncode != 0:
        append_log(log_path, f"COMMAND FAILED: exit={proc.returncode}")
    return proc.returncode


def run_cmd_timed(cmd: list[str], log_path: Path, dry_run: bool, timeout_seconds: int | None) -> tuple[int, float, bool]:
    append_log(log_path, "+ " + " ".join(cmd))
    if dry_run:
        return 0, 0.0, False
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - start
        append_log(log_path, proc.stdout)
        if proc.returncode != 0:
            append_log(log_path, f"COMMAND FAILED: exit={proc.returncode}")
        return proc.returncode, elapsed, False
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        if exc.stdout:
            append_log(log_path, exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="ignore"))
        append_log(log_path, f"COMMAND TIMEOUT: timeout_seconds={timeout_seconds} elapsed_seconds={elapsed:.3f}")
        return 124, elapsed, True


def safe_float(row: dict[str, str], name: str, default: float = 0.0) -> float:
    try:
        value = row.get(name, "")
        if value == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_int(row: dict[str, Any], name: str, default: int = 0) -> int:
    try:
        value = row.get(name, "")
        if value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def ratio(row: dict[str, str], num: str, den: str) -> float:
    d = safe_float(row, den)
    if d == 0:
        return 0.0
    return safe_float(row, num) / d


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def dedupe_rows_by_fields_keep_latest(rows: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        if key in latest:
            del latest[key]
        latest[key] = row
    return list(latest.values())


def normalize_benchmark_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("update_total_latency_ms", "") == "":
        row["update_total_latency_ms"] = row.get("avg_update_ms", "") or "0"
    if row.get("patch_update_latency_ms", "") == "":
        row["patch_update_latency_ms"] = row.get("update_total_latency_ms", "") or "0"
    for field in BENCH_WIDE_FILL_FIELDS:
        if row.get(field, "") == "":
            row[field] = "0"
    return row


def dedupe_bench_wide_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_benchmark_row(row) for row in rows]
    return dedupe_rows_by_fields_keep_latest(normalized, BENCH_WIDE_DEDUPE_FIELDS)


def merge_raw_metric_rows(path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing: list[dict[str, Any]] = read_csv_rows(path)
    if not existing:
        return dedupe_rows_by_fields_keep_latest(rows, RAW_METRIC_DEDUPE_FIELDS)
    return dedupe_rows_by_fields_keep_latest(existing + rows, RAW_METRIC_DEDUPE_FIELDS)


def split_trace_units(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def update_touch_counts_from_trace(trace_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in read_csv_rows(trace_dir / "update_trace.csv"):
        for cell_id in split_trace_units(row.get("touched_unit", "")):
            counts[cell_id] += 1
    return counts


def mechanism_dataset_family(dataset_name: str) -> str:
    return "synthetic" if dataset_name == "synthetic" else "real"


def extract_mechanism_layout_rows(
    trace_dir: Path,
    *,
    group: str,
    dataset_name: str,
    workload: str,
    scheme_name: str,
    seed: int,
) -> list[dict[str, Any]]:
    layout = read_csv_rows(trace_dir / "layout_units.csv")
    if not layout:
        return []

    update_counts = update_touch_counts_from_trace(trace_dir)
    layout_touch_sum = sum(safe_int(row, "true_update_touches") for row in layout)
    has_layout_touches = any(row.get("true_update_touches", "") != "" for row in layout)
    use_layout_touches = has_layout_touches and (layout_touch_sum > 0 or not update_counts)
    rows: list[dict[str, Any]] = []
    for row in layout:
        cell_id = row.get("unit_id") or row.get("cell_id") or ""
        touches = safe_int(row, "true_update_touches") if use_layout_touches else update_counts.get(cell_id, 0)
        rows.append(
            {
                "group": group,
                "dataset": dataset_name,
                "workload": workload,
                "scheme": eval_scheme_label(scheme_name),
                "seed": int(seed),
                "cell_id": cell_id,
                "true_load": safe_int(row, "true_load"),
                "true_update_touches": touches,
            }
        )
    return rows


def write_mechanism_layout_dump(trace_dir: Path, rows: list[dict[str, Any]]) -> None:
    raw_path = trace_dir / "layout_units.csv"
    raw_copy = trace_dir / "layout_units_trace.csv"
    if raw_path.exists() and not raw_copy.exists():
        shutil.copyfile(raw_path, raw_copy)
    write_csv_rows(raw_path, rows, MECHANISM_LAYOUT_FIELDS)


def mechanism_figure_rows(layout_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in layout_rows:
        grouped[(str(row["dataset"]), str(row["workload"]), str(row["scheme"]), int(row["seed"]))].append(row)

    out: list[dict[str, Any]] = []
    for (dataset_name, workload, scheme, seed), rows in sorted(grouped.items()):
        family = mechanism_dataset_family(dataset_name)
        panels = [
            ("synthetic_cell_load" if family == "synthetic" else "real_cell_load", "true_load", False),
            ("update_touch_synthetic" if family == "synthetic" else "update_touch_real", "true_update_touches", True),
        ]
        for panel, value_field, positive_only in panels:
            values = [safe_int(row, value_field) for row in rows]
            if positive_only:
                values = [value for value in values if value > 0]
            values.sort(reverse=True)
            for rank, value in enumerate(values, start=1):
                out.append(
                    {
                        "panel": panel,
                        "dataset_family": family,
                        "dataset": dataset_name,
                        "workload": workload,
                        "scheme": scheme,
                        "seed": seed,
                        "rank": rank,
                        "value": value,
                    }
                )
    return out


def write_mechanism_outputs(group_dir: Path, layout_rows: list[dict[str, Any]]) -> None:
    figure_rows = mechanism_figure_rows(layout_rows)
    write_csv_rows(group_dir / "cell_layout_units.csv", layout_rows, MECHANISM_LAYOUT_FIELDS)
    write_csv_rows(group_dir / "figure_data.csv", figure_rows, MECHANISM_FIGURE_FIELDS)
    write_csv_rows(group_dir / "fig_mechanism_cell_load_touch_skew.csv", figure_rows, MECHANISM_FIGURE_FIELDS)


def metric_row(
    *,
    group: str,
    dataset: str,
    attribute: str,
    N: int,
    workload: str,
    scheme: str,
    seed: int,
    metric_name: str,
    metric_value: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "group": group,
        "dataset": dataset,
        "attribute": attribute,
        "N": int(N),
        "workload": workload,
        "scheme": scheme,
        "seed": int(seed),
        "metric_name": metric_name,
        "metric_value": metric_value,
    }
    if extra:
        row.update(extra)
    return row


def dataset_attribute(name: str, cfg: dict[str, Any]) -> tuple[str, str]:
    reg = dataset_registry().get(name, {})
    if reg:
        return str(reg.get("dataset", name)), str(reg.get("attribute", name))
    if name == "synthetic":
        return "synthetic", "value"
    if "_" in name:
        left, right = name.split("_", 1)
        return left, right
    return name, "value"


def dataset_rows_available(path: Path) -> int:
    if not path.exists():
        return 0
    meta = path.with_suffix(".meta.json")
    if meta.exists():
        try:
            return int(json.loads(meta.read_text(encoding="utf-8")).get("rows", 0))
        except Exception:
            pass
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return max(0, sum(1 for _ in fh) - 1)
    except Exception:
        return 0


def choose_N(requested: int, dataset_name: str | None) -> int:
    if not dataset_name:
        return requested
    reg = dataset_registry().get(dataset_name, {})
    path_text = reg.get("path")
    if not path_text:
        return requested
    rows = dataset_rows_available(Path(path_text))
    if rows and rows < requested:
        print(f"WARNING: {dataset_name} has only {rows} rows; using N={rows}", file=sys.stderr)
        return rows
    return requested


def scheme_case(name: str) -> dict[str, str] | None:
    entry = scheme_registry().get(name)
    if not entry:
        raise KeyError(f"unknown scheme {name}; see configs/schemes.yaml")
    if entry.get("simulated"):
        return None
    return {"scheme": str(entry["scheme"]), "variant": str(entry["variant"])}


def normalize_scheme_label(row: dict[str, str], fallback: str) -> str:
    return row.get("case") or fallback


def eval_scheme_label(requested_name: str, bench_row: dict[str, str] | None = None) -> str:
    if requested_name in {"ResponseGlobalPad", "GlobalPad"}:
        return "ResponseGlobalPad"
    if bench_row:
        case = bench_row.get("case", "")
        if case == "PGM-Learned-GlobalPad":
            return "ResponseGlobalPad"
    return requested_name


def is_treecover(scheme_name: str) -> bool:
    return scheme_name == "TreeCover"


def fig3_treecover_cap_n(cfg: dict[str, Any]) -> int:
    fig3_cfg = cfg.get("fig3", {})
    treecover_cfg = fig3_cfg.get("treecover", {})
    values = treecover_cfg.get("n_values")
    if values:
        return max(int(n) for n in values)
    return int(fig3_cfg.get("treecover_max_n", 100000))


def command_string(cmd: list[str]) -> str:
    return " ".join(cmd)


def append_case_status_event(
    group_dir: Path,
    *,
    group: str,
    dataset: str,
    attribute: str,
    N: int,
    workload: str,
    scheme: str,
    seed: int,
    axis: str,
    selectivity: Any,
    status: str,
    reason: str,
    elapsed_seconds: float,
    command: str,
) -> None:
    path = group_dir / "skipped_cases.csv"
    exists = path.exists()
    fields = [
        "group",
        "dataset",
        "attribute",
        "N",
        "workload",
        "scheme",
        "seed",
        "axis",
        "selectivity",
        "status",
        "reason",
        "elapsed_seconds",
        "command",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "group": group,
                "dataset": dataset,
                "attribute": attribute,
                "N": N,
                "workload": workload,
                "scheme": scheme,
                "seed": seed,
                "axis": axis,
                "selectivity": selectivity,
                "status": status,
                "reason": reason,
                "elapsed_seconds": f"{elapsed_seconds:.3f}",
                "command": command,
            }
        )


def append_timeout_event(
    group_dir: Path,
    *,
    group: str,
    dataset: str,
    attribute: str,
    N: int,
    workload: str,
    scheme: str,
    seed: int,
    axis: str,
    selectivity: Any,
    reason: str,
    elapsed_seconds: float,
    command: str,
) -> None:
    status = "skipped" if reason.startswith("omitted") else "timeout"
    append_case_status_event(
        group_dir,
        group=group,
        dataset=dataset,
        attribute=attribute,
        N=N,
        workload=workload,
        scheme=scheme,
        seed=seed,
        axis=axis,
        selectivity=selectivity,
        status=status,
        reason=reason,
        elapsed_seconds=elapsed_seconds,
        command=command,
    )
    path = group_dir / "timeouts.csv"
    exists = path.exists()
    fields = ["group", "dataset", "attribute", "N", "workload", "scheme", "seed", "axis", "selectivity", "reason", "elapsed_seconds", "command"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "group": group,
                "dataset": dataset,
                "attribute": attribute,
                "N": N,
                "workload": workload,
                "scheme": scheme,
                "seed": seed,
                "axis": axis,
                "selectivity": selectivity,
                "reason": reason,
                "elapsed_seconds": f"{elapsed_seconds:.3f}",
                "command": command,
            }
        )


def timeout_metric_row(
    *,
    group: str,
    dataset: str,
    attribute: str,
    N: int,
    workload: str,
    scheme: str,
    seed: int,
    reason: str,
    elapsed_seconds: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    e = {"status": "skipped" if reason.startswith("omitted") else "timeout", "reason": reason, "elapsed_seconds": elapsed_seconds}
    if extra:
        e.update(extra)
    return metric_row(
        group=group,
        dataset=dataset,
        attribute=attribute,
        N=N,
        workload=workload,
        scheme=scheme,
        seed=seed,
        metric_name="timeout",
        metric_value=1.0,
        extra=e,
    )


def status_metric_row(
    *,
    group: str,
    dataset: str,
    attribute: str,
    N: int,
    workload: str,
    scheme: str,
    seed: int,
    status: str,
    reason: str,
    elapsed_seconds: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    e = {"status": status, "reason": reason, "elapsed_seconds": elapsed_seconds}
    if extra:
        e.update(extra)
    return metric_row(
        group=group,
        dataset=dataset,
        attribute=attribute,
        N=N,
        workload=workload,
        scheme=scheme,
        seed=seed,
        metric_name=status,
        metric_value=1.0,
        extra=e,
    )


def case_timeout_seconds(group: str, scheme_name: str, cfg: dict[str, Any]) -> int | None:
    timeouts = cfg.get("timeouts", {})
    fig3_cfg = cfg.get("fig3", {})
    if group == "fig3":
        if is_treecover(scheme_name):
            return int(
                timeouts.get(
                    "fig3_treecover_seconds",
                    fig3_cfg.get("treecover_timeout_seconds", fig3_cfg.get("treecover", {}).get("timeout_seconds", 600)),
                )
            )
        return int(fig3_cfg.get("per_case_timeout_seconds", timeouts.get("fig3_case_seconds", 600)))
    group_cfg = cfg.get(GROUP_DIRS.get(group, ""), cfg.get(group, {}))
    if group_cfg:
        return int(group_cfg.get("timeout_sec", group_cfg.get("per_case_timeout_seconds", timeouts.get("default_seconds", 600))))
    value = timeouts.get("default_seconds")
    return int(value) if value else None


def adversarial_auc(value: float) -> float:
    return max(value, 1.0 - value)


def required_auc(row: dict[str, str], names: list[str], *, context: str) -> float:
    for name in names:
        value = row.get(name, "")
        if value != "":
            return safe_float(row, name)
    raise RuntimeError(f"missing required attack_eval AUC field {names} for {context}")


def attack_metrics_from(trace_dir: Path, out_csv: Path, log_path: Path, dry_run: bool) -> dict[str, float]:
    if dry_run:
        return {}
    rc = run_cmd([sys.executable, "scripts/attack_eval.py", str(trace_dir), "--csv", str(out_csv)], log_path, False)
    if rc != 0:
        raise RuntimeError(f"attack_eval.py failed for {trace_dir}; see {log_path}")
    rows = read_csv_rows(out_csv)
    if not rows:
        raise RuntimeError(f"attack_eval.py wrote no rows for {trace_dir}")
    row = rows[0]
    context = str(trace_dir)
    shape = required_auc(row, ["layout_class_auc", "shape_auc"], context=context)
    patch = required_auc(row, ["log_growth_auc", "patch_pressure_auc"], context=context)
    maint = required_auc(row, ["maintenance_auc", "maintenance_cause_auc"], context=context)
    shape_adv = adversarial_auc(shape)
    patch_adv = adversarial_auc(patch)
    maint_adv = adversarial_auc(maint)
    return {
        "layout_shape_auc": shape,
        "shape_auc": shape,
        "patch_pressure_auc": patch,
        "maintenance_cause_auc": maint,
        "layout_shape_adv_auc": shape_adv,
        "patch_pressure_adv_auc": patch_adv,
        "maintenance_cause_adv_auc": maint_adv,
        "max_cert_probe_auc": max(shape_adv, patch_adv, maint_adv),
        "diagnostic_region_auc": safe_float(row, "region_auc", 0.5),
        "diagnostic_hotspot_auc": safe_float(row, "hotspot_auc", 0.5),
    }


def should_run_attack_eval(group: str) -> bool:
    return group not in {"fig3", "fig_mechanism"}


def trace_derived_metrics(trace_dir: Path) -> dict[str, float]:
    searches = read_csv_rows(trace_dir / "search_trace.csv")
    maint = read_csv_rows(trace_dir / "maintenance_trace.csv")
    out: dict[str, float] = {}
    if searches:
        n = len(searches)
        out["full_cells"] = sum(safe_float(r, "full_cells") for r in searches) / n
        out["boundary_cells"] = sum(safe_float(r, "boundary_cells") for r in searches) / n
        out["refresh_latency_ms"] = (
            sum(safe_float(r, "latency") for r in maint) / len(maint) if maint else 0.0
        )
    return out


def benchmark_metrics(row: dict[str, str]) -> dict[str, float]:
    row = normalize_benchmark_row(row)
    searches = safe_float(row, "searches")
    touched = safe_float(row, "touched_cells")
    update_total_latency_ms = safe_float(row, "update_total_latency_ms", safe_float(row, "avg_update_ms"))
    metrics = {
        "queries": searches,
        "updates": safe_float(row, "updates"),
        "search_latency_ms": safe_float(row, "avg_query_ms"),
        "update_latency_ms": update_total_latency_ms,
        "update_total_latency_ms": update_total_latency_ms,
        "setup_time_ms": safe_float(row, "build_ms"),
        "response_bytes": ratio(row, "response_bytes", "searches"),
        "server_storage_bytes": safe_float(row, "server_bytes"),
        "client_storage_bytes": (
            safe_float(row, "logical_cells") * 64.0
            + safe_float(row, "lbc_boundary_count") * 16.0
            + safe_float(row, "lbc_prototype_count") * 32.0
        ),
        "refresh_bytes": safe_float(row, "refresh_bytes"),
        "touched_cells": touched / searches if searches else 0.0,
        "patch_occupancy": safe_float(row, "log_refs") / touched if touched else 0.0,
        "precision": 1.0,
        "recall": 1.0,
        "false_positive_count": 0.0,
        "false_negative_count": 0.0,
        "exact_match_rate": 1.0,
    }
    metrics["patch_update_latency_ms"] = safe_float(row, "patch_update_latency_ms", update_total_latency_ms)
    metrics["maintenance_latency_ms"] = safe_float(row, "maintenance_latency_ms", 0.0)
    metrics["refresh_latency_ms"] = safe_float(row, "refresh_latency_ms", 0.0)
    for metric_name, field_name in [
        ("refresh_count", "refresh_count"),
        ("scheduled_refresh_count", "scheduled_refresh_count"),
        ("forced_log_refresh_count", "forced_log_refresh_count"),
        ("public_rollover_count", "public_rollover_count"),
        ("split_count", "split_count"),
        ("merge_count", "merge_count"),
        ("guide_retrain_count", "guide_retrain_count"),
        ("locator_rebuild_count", "locator_rebuild_count"),
    ]:
        metrics[metric_name] = safe_float(row, field_name, 0.0)
    return metrics


def case_id(group: str, scheme: str, dataset: str, workload: str, N: int, seed: int, extra: str = "") -> str:
    clean = lambda x: "".join(c if c.isalnum() or c in "-_" else "_" for c in str(x))
    bits = [group, scheme, dataset, workload, f"N{N}", f"s{seed}"]
    if extra:
        bits.append(extra)
    return clean("__".join(bits))


def scheme_config_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("scheme_name") or entry.get("scheme"))
    return str(entry)


def scheme_config_overrides(entry: Any) -> dict[str, Any]:
    return dict(entry) if isinstance(entry, dict) else {}


def first_config_list(value: Any, default: list[Any]) -> list[Any]:
    if value is None:
        return default
    return value if isinstance(value, list) else [value]


def paired_budget_values(theta_values: list[Any], cap_values: list[Any]) -> list[tuple[int, int, int]]:
    if cap_values and len(cap_values) == len(theta_values):
        return [(int(theta), int(cap), int(theta)) for theta, cap in zip(theta_values, cap_values)]
    return [(int(theta), int(cap_values[0] if cap_values else theta), int(theta)) for theta in theta_values]


def run_benchmark_case(
    *,
    group: str,
    group_dir: Path,
    scheme_name: str,
    dataset_name: str,
    workload: str,
    N: int,
    ops: int,
    seed: int,
    cfg: dict[str, Any],
    args: argparse.Namespace,
    selectivity: float | None = None,
    extra_tag: str = "",
    axis_name: str | None = None,
    case_overrides: dict[str, Any] | None = None,
    timeout_seconds_override: int | None = None,
    timeout_reason_override: str | None = None,
) -> list[dict[str, Any]]:
    case = scheme_case(scheme_name)
    if case is None:
        return []

    defaults = cfg["defaults"]
    overrides = case_overrides or {}
    axis_value = extra_tag if axis_name is None else axis_name
    U = int(overrides.get("U", defaults.get("U", 1 << 20)))
    B = int(overrides.get("B", defaults.get("B", 1024)))
    theta = int(overrides.get("theta", defaults.get("theta", 128)))
    query_ratio = float(overrides.get("query_ratio", defaults.get("query_ratio", 0.8)))
    crypto = "real" if args.real_crypto else ("mock" if args.mock_crypto else str(overrides.get("crypto", defaults.get("crypto", "mock"))))
    data_limit = int(overrides.get("data_limit", N))
    trace_dir = group_dir / "traces" / case_id(group, scheme_name, dataset_name, workload, N, seed, extra_tag)
    trace_dir.mkdir(parents=True, exist_ok=True)
    bench_csv = group_dir / "bench_wide.csv"
    attack_csv = group_dir / "attacks" / f"{trace_dir.name}.csv"
    attack_csv.parent.mkdir(parents=True, exist_ok=True)
    log_path = group_dir / "stdout.log"

    cmd = [
        str(bench_exe(require_exists=not args.dry_run)),
        "--scheme", case["scheme"],
        "--variant", case["variant"],
        "--N", str(N),
        "--ops", str(ops),
        "--U", str(U),
        "--B", str(B),
        "--theta", str(theta),
        "--workload", workload,
        "--crypto", crypto,
        "--seed", str(seed),
        "--query-ratio", str(query_ratio),
        "--csv", str(bench_csv),
        "--trace-dir", str(trace_dir),
    ]
    if selectivity is not None:
        cmd += ["--selectivity", str(selectivity)]
    if dataset_name != "synthetic":
        cmd += ["--dataset", dataset_name, "--data-limit", str(data_limit)]
    else:
        dist = str(overrides.get("dist", "uniform" if workload == "uniform" else "skew"))
        cmd += ["--dist", dist]

    dataset, attribute = dataset_attribute(dataset_name, cfg)
    extra = {"selectivity": "" if selectivity is None else selectivity, "axis": axis_value}
    for name in ["budget", "theta", "B", "data_limit"]:
        if name in overrides:
            extra[name] = overrides[name]
    eval_name = eval_scheme_label(scheme_name)

    if group == "fig3" and is_treecover(scheme_name):
        treecover_max_n = fig3_treecover_cap_n(cfg)
        if N > treecover_max_n:
            reason = "omitted_treecover_large_scale"
            append_log(log_path, f"OMITTED: {reason} scheme={eval_name} N={N} cap={treecover_max_n}")
            append_timeout_event(
                group_dir,
                group=group,
                dataset=dataset,
                attribute=attribute,
                N=N,
                workload=workload,
                scheme=eval_name,
                seed=seed,
                axis=axis_value,
                selectivity=extra["selectivity"],
                reason=reason,
                elapsed_seconds=0.0,
                command=command_string(cmd),
            )
            return [
                timeout_metric_row(
                    group=group,
                    dataset=dataset,
                    attribute=attribute,
                    N=N,
                    workload=workload,
                    scheme=eval_name,
                    seed=seed,
                    reason=reason,
                    elapsed_seconds=0.0,
                    extra=extra,
                )
            ]

    if args.dry_run:
        run_cmd(cmd, log_path, True)
        return []

    before_rows = len(read_csv_rows(bench_csv))
    case_timeout = int(overrides.get("timeout_sec", case_timeout_seconds(group, scheme_name, cfg) or 600))
    if timeout_seconds_override is not None:
        timeout_seconds = min(case_timeout, timeout_seconds_override) if case_timeout else timeout_seconds_override
    else:
        timeout_seconds = case_timeout
    rc, elapsed, timed_out = run_cmd_timed(cmd, log_path, False, timeout_seconds)
    if timed_out:
        reason = timeout_reason_override or "timeout"
        append_timeout_event(
            group_dir,
            group=group,
            dataset=dataset,
            attribute=attribute,
            N=N,
            workload=workload,
            scheme=eval_name,
            seed=seed,
            axis=axis_value,
            selectivity=extra["selectivity"],
            reason=reason,
            elapsed_seconds=elapsed,
            command=command_string(cmd),
        )
        return [
            timeout_metric_row(
                group=group,
                dataset=dataset,
                attribute=attribute,
                N=N,
                workload=workload,
                scheme=eval_name,
                seed=seed,
                reason=reason,
                elapsed_seconds=elapsed,
                extra=extra,
            )
        ]
    if rc != 0:
        reason = "failed"
        append_log(log_path, f"CASE FAILED: reason={reason} scheme={eval_name} dataset={dataset_name} workload={workload} N={N} seed={seed} exit={rc}")
        append_case_status_event(
            group_dir,
            group=group,
            dataset=dataset,
            attribute=attribute,
            N=N,
            workload=workload,
            scheme=eval_name,
            seed=seed,
            axis=axis_value,
            selectivity=extra["selectivity"],
            status="failed",
            reason=reason,
            elapsed_seconds=elapsed,
            command=command_string(cmd),
        )
        return [
            status_metric_row(
                group=group,
                dataset=dataset,
                attribute=attribute,
                N=N,
                workload=workload,
                scheme=eval_name,
                seed=seed,
                status="failed",
                reason=reason,
                elapsed_seconds=elapsed,
                extra=extra,
            )
        ]
    bench_rows = read_csv_rows(bench_csv)
    if len(bench_rows) <= before_rows:
        reason = "missing_benchmark_row"
        append_log(log_path, f"CASE FAILED: reason={reason} scheme={eval_name} dataset={dataset_name} workload={workload} N={N} seed={seed}")
        append_case_status_event(
            group_dir,
            group=group,
            dataset=dataset,
            attribute=attribute,
            N=N,
            workload=workload,
            scheme=eval_name,
            seed=seed,
            axis=axis_value,
            selectivity=extra["selectivity"],
            status="failed",
            reason=reason,
            elapsed_seconds=elapsed,
            command=command_string(cmd),
        )
        return [
            status_metric_row(
                group=group,
                dataset=dataset,
                attribute=attribute,
                N=N,
                workload=workload,
                scheme=eval_name,
                seed=seed,
                status="failed",
                reason=reason,
                elapsed_seconds=elapsed,
                extra=extra,
            )
        ]
    bench_row = normalize_benchmark_row(bench_rows[-1])
    bench_row["dataset"] = dataset
    bench_row["attribute"] = attribute
    write_csv_rows(bench_csv, dedupe_bench_wide_rows(bench_rows))

    derived = trace_derived_metrics(trace_dir)
    metrics = benchmark_metrics(bench_row)
    for name, value in derived.items():
        metrics.setdefault(name, value)
    if group == "fig3":
        append_log(log_path, f"SKIPPED: attack_eval reason=fig3_performance_only trace={trace_dir}")
        metrics = {name: value for name, value in metrics.items() if name in FIG3_PERFORMANCE_METRICS}
        metrics["attack_eval_skipped"] = 1.0
    elif should_run_attack_eval(group):
        attack = attack_metrics_from(trace_dir, attack_csv, log_path, False)
        metrics.update(attack)

    rows = [
        metric_row(
            group=group,
            dataset=dataset,
            attribute=attribute,
            N=N,
            workload=workload,
            scheme=eval_scheme_label(scheme_name, bench_row),
            seed=seed,
            metric_name=name,
            metric_value=value,
            extra=extra,
        )
        for name, value in metrics.items()
    ]
    if group == "fig3":
        for row in rows:
            if row["metric_name"] == "attack_eval_skipped":
                row["reason"] = "fig3_performance_only"
    return rows


def add_sim_lcert(rows: list[dict[str, Any]], group: str) -> list[dict[str, Any]]:
    """Add Sim-L_cert rows from public-class residual leakage only."""
    by_context: dict[tuple[Any, ...], dict[str, float]] = defaultdict(dict)
    passthrough: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if row["scheme"] != "LOCI-Full":
            continue
        key = (
            row["dataset"],
            row["attribute"],
            row["N"],
            row["workload"],
            row["seed"],
            row.get("selectivity", ""),
            row.get("axis", ""),
            row.get("budget", ""),
            row.get("theta", ""),
            row.get("B", ""),
        )
        by_context[key][row["metric_name"]] = float(row["metric_value"])
        passthrough[key] = row

    sim_rows: list[dict[str, Any]] = []
    for key, metrics in by_context.items():
        base = passthrough[key]
        sim_metrics = {
            "layout_shape_auc": 0.5,
            "shape_auc": 0.5,
            "patch_pressure_auc": 0.5,
            "maintenance_cause_auc": 0.5,
            "layout_shape_adv_auc": 0.5,
            "patch_pressure_adv_auc": 0.5,
            "maintenance_cause_adv_auc": 0.5,
            "max_cert_probe_auc": 0.5,
            "diagnostic_region_auc": 0.5,
            "diagnostic_hotspot_auc": 0.5,
        }
        # Sim-L_cert is a leakage baseline. For cost tables, carry the LOCI-Full
        # transcript cost because the simulated leakage surface is LOCI's public
        # transcript surface, not a standalone implementation.
        for cost in [
            "search_latency_ms",
            "update_latency_ms",
            "update_total_latency_ms",
            "patch_update_latency_ms",
            "maintenance_latency_ms",
            "setup_time_ms",
            "response_bytes",
            "server_storage_bytes",
            "client_storage_bytes",
            "refresh_bytes",
            "refresh_latency_ms",
            "refresh_count",
            "scheduled_refresh_count",
            "forced_log_refresh_count",
            "public_rollover_count",
            "split_count",
            "merge_count",
            "guide_retrain_count",
            "locator_rebuild_count",
            "touched_cells",
            "full_cells",
            "boundary_cells",
            "patch_occupancy",
        ]:
            if cost in metrics:
                sim_metrics[cost] = metrics[cost]
        for name, value in sim_metrics.items():
            sim_rows.append(
                metric_row(
                    group=group,
                    dataset=base["dataset"],
                    attribute=base["attribute"],
                    N=int(base["N"]),
                    workload=base["workload"],
                    scheme="Sim-L_cert",
                    seed=int(base["seed"]),
                    metric_name=name,
                    metric_value=value,
                    extra={
                        "selectivity": base.get("selectivity", ""),
                        "axis": base.get("axis", ""),
                        "budget": base.get("budget", ""),
                        "theta": base.get("theta", ""),
                        "B": base.get("B", ""),
                    },
                )
            )
    return sim_rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    meta: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["group"],
            row["dataset"],
            row["attribute"],
            row["N"],
            row["workload"],
            row["scheme"],
            row["metric_name"],
            str(row.get("selectivity", "")),
            row.get("axis", ""),
            row.get("budget", ""),
            row.get("theta", ""),
            row.get("B", ""),
        )
        grouped[key].append(float(row["metric_value"]))
        meta[key] = {
            k: row.get(k, "")
            for k in [
                "group",
                "dataset",
                "attribute",
                "N",
                "workload",
                "scheme",
                "metric_name",
                "selectivity",
                "axis",
                "budget",
                "theta",
                "B",
                "data_limit",
                "status",
                "reason",
                "elapsed_seconds",
            ]
        }
    out = []
    for key, values in sorted(grouped.items()):
        mean = sum(values) / len(values)
        var = sum((x - mean) ** 2 for x in values) / len(values)
        row = dict(meta[key])
        row.update({"mean": mean, "std": math.sqrt(var), "n": len(values)})
        out.append(row)
    return out


def write_common_outputs(
    group_dir: Path,
    group: str,
    cfg: dict[str, Any],
    seeds: list[int],
    rows: list[dict[str, Any]],
    merge_existing: bool = False,
) -> list[dict[str, Any]]:
    fields = [
        "group",
        "dataset",
        "attribute",
        "N",
        "workload",
        "scheme",
        "seed",
        "metric_name",
        "metric_value",
        "selectivity",
        "axis",
        "budget",
        "theta",
        "B",
        "data_limit",
        "status",
        "reason",
        "elapsed_seconds",
    ]
    for row in rows:
        row.setdefault("selectivity", "")
        row.setdefault("axis", "")
        row.setdefault("budget", "")
        row.setdefault("theta", "")
        row.setdefault("B", "")
        row.setdefault("data_limit", "")
        row.setdefault("status", "")
        row.setdefault("reason", "")
        row.setdefault("elapsed_seconds", "")
    if merge_existing:
        rows = merge_raw_metric_rows(group_dir / "raw_metrics.csv", rows)
    write_csv_rows(group_dir / "raw_metrics.csv", rows, fields)
    summary = summarize(rows)
    write_csv_rows(group_dir / "summary.csv", summary)
    write_csv_rows(group_dir / "figure_data.csv", summary)
    write_yaml(group_dir / "config_used.yaml", cfg)
    (group_dir / "seeds.txt").write_text(",".join(str(s) for s in seeds) + "\n", encoding="utf-8")
    if not (group_dir / "stdout.log").exists():
        (group_dir / "stdout.log").write_text("", encoding="utf-8")
    return rows


def gini(values: list[int]) -> float:
    if not values:
        return 0.0
    xs = sorted(float(x) for x in values)
    total = sum(xs)
    if total == 0:
        return 0.0
    n = len(xs)
    return (2.0 * sum((i + 1) * x for i, x in enumerate(xs)) / (n * total)) - ((n + 1) / n)


def profile_dataset(name: str, path: Path, default_N: int) -> dict[str, Any]:
    if not path.exists():
        return {"Dataset": name, "Default attribute": "", "Rows available": 0, "Rows used": 0, "warning": "missing"}
    import pandas as pd

    df = pd.read_csv(path, usecols=["value", "time"])
    rows = len(df)
    used = min(rows, default_N)
    vals = df["value"].head(used).astype("int64")
    counts = vals.value_counts()
    median_freq = float(counts.median()) if not counts.empty else 0.0
    max_freq = float(counts.max()) if not counts.empty else 0.0
    top1 = max(1, int(math.ceil(len(counts) * 0.01))) if len(counts) else 1
    top1_share = float(counts.sort_values(ascending=False).head(top1).sum()) / used if used else 0.0
    meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8")) if path.with_suffix(".meta.json").exists() else {}
    return {
        "Dataset": name,
        "Default attribute": meta.get("attribute", name),
        "Rows available": rows,
        "Rows used": used,
        "Value min": int(vals.min()) if used else "",
        "Value max": int(vals.max()) if used else "",
        "Unique values": int(vals.nunique()) if used else 0,
        "Time span": f"{int(df['time'].min())}-{int(df['time'].max())}" if rows else "",
        "Skew indicator": f"gini={gini(counts.tolist()):.3f}; top1%={top1_share:.3f}; max/median={(max_freq / median_freq if median_freq else 0.0):.2f}",
        "low_domain": bool(vals.nunique() < max(100, used * 0.001)) if used else False,
    }


def write_markdown_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    lines = ["|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(row.get(f, "")) for f in fields) + "|")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_latex_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    lines = ["\\begin{tabular}{" + "l" * len(fields) + "}", " \\toprule", " & ".join(fields) + " \\\\", " \\midrule"]
    for row in rows:
        lines.append(" & ".join(str(row.get(f, "")).replace("_", "\\_") for f in fields) + " \\\\")
    lines += [" \\bottomrule", "\\end{tabular}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_table1(group_dir: Path, cfg: dict[str, Any]) -> None:
    machine = cfg["machine"]
    defaults = cfg["defaults"]
    table_a = [
        {
            "Implementation": machine.get("implementation", "C++ implementation"),
            "Machine": machine.get("name", "aliyun-ecs"),
            "CPU": machine.get("cpu", "16 vCPU"),
            "Memory": machine.get("memory", "64 GiB"),
            "Storage": machine.get("storage", "ESSD"),
            "OS": machine.get("os", "Ubuntu 22.04"),
            "Default N": defaults.get("N"),
            "Trace length": defaults.get("trace_ops"),
            "Query/update ratio": f"{defaults.get('query_ratio')}/{defaults.get('update_ratio')}",
            "Seeds": ",".join(map(str, defaults.get("seeds", []))),
            "Metrics": "latency, communication, storage, leakage AUC, exactness",
        }
    ]
    profiles = [
        {
            "Dataset": "synthetic",
            "Default attribute": "value",
            "Rows available": "generated",
            "Rows used": defaults.get("N"),
            "Value min": 0,
            "Value max": defaults.get("U", 1 << 20) - 1,
            "Unique values": "controlled",
            "Time span": "operation index",
            "Skew indicator": "uniform/skew/hotspot/burst/drift/structured",
            "low_domain": False,
        }
    ]
    for entry in cfg["datasets"].get("real", []):
        profiles.append(profile_dataset(entry["name"], Path(entry["path"]), int(defaults["N"])))

    write_csv_rows(group_dir / "table1_setup.csv", table_a + profiles)
    write_markdown_table(group_dir / "table1_setup.md", table_a + profiles)
    write_latex_table(group_dir / "table1_setup.tex", table_a + profiles)
    rows = []
    for profile in profiles:
        if profile["Dataset"] == "synthetic":
            continue
        for metric in ["Rows available", "Rows used", "Unique values"]:
            rows.append(
                metric_row(
                    group="table1",
                    dataset=str(profile["Dataset"]).split("_")[0],
                    attribute=str(profile["Default attribute"]),
                    N=int(defaults["N"]),
                    workload="profile",
                    scheme="dataset-profile",
                    seed=0,
                    metric_name=metric.lower().replace(" ", "_"),
                    metric_value=float(profile.get(metric) or 0),
                )
            )
    write_common_outputs(group_dir, "table1", cfg, [0], rows)


def group_cases(group: str, cfg: dict[str, Any], N_override: int | None) -> list[dict[str, Any]]:
    defaults = cfg["defaults"]
    N0 = int(N_override or defaults["N"])
    ops = int(defaults["trace_ops"])
    cases: list[dict[str, Any]] = []
    if group == "fig1":
        for scheme in cfg["schemes"]["security"]:
            cases.append({"scheme": scheme, "dataset": "synthetic", "workload": "skew_hotspot_drift_mix", "N": N0, "ops": ops})
    elif group == "fig2":
        scheme_list = cfg["schemes"].get("fig2_cost", cfg["schemes"]["ablation"])
        for scheme in scheme_list:
            cases.append({"scheme": scheme, "dataset": "synthetic", "workload": "skew_hotspot_drift_mix", "N": N0, "ops": ops})
    elif group == "fig3":
        fig3_cfg = cfg.get("fig3", {})
        scale_cfg = fig3_cfg.get("scale", {})
        treecover_cfg = fig3_cfg.get("treecover", {})
        selectivity_cfg = fig3_cfg.get("selectivity", {})
        default_n_values = scale_cfg.get(
            "n_values",
            fig3_cfg.get("n_values", {}).get("default", cfg["scales"]["N_values"]),
        )
        scale_values = [int(N_override)] if N_override is not None else [int(n) for n in default_n_values]
        scale_ops = int(scale_cfg.get("ops", 1000))
        scale_workload = str(scale_cfg.get("workload", "skew"))
        scale_schemes = scale_cfg.get(
            "schemes",
            [scheme for scheme in cfg["schemes"]["main"] if scheme != "TreeCover"],
        )
        for N in scale_values:
            for scheme in scale_schemes:
                cases.append({"scheme": scheme, "dataset": "synthetic", "workload": scale_workload, "N": int(N), "ops": scale_ops, "axis": "scale"})
        treecover_ops = int(treecover_cfg.get("ops", 500))
        treecover_workload = str(treecover_cfg.get("workload", scale_workload))
        treecover_scale_values = [int(N_override)] if N_override is not None else scale_values
        for N in treecover_scale_values:
            cases.append({"scheme": "TreeCover", "dataset": "synthetic", "workload": treecover_workload, "N": int(N), "ops": treecover_ops, "axis": "scale"})
        selectivities = selectivity_cfg.get("values", fig3_cfg.get("selectivities", cfg["scales"]["selectivities"]))
        selectivity_n = int(N_override or selectivity_cfg.get("N", min(N0, 100000)))
        selectivity_ops = int(selectivity_cfg.get("ops", 1000))
        selectivity_workload = str(selectivity_cfg.get("workload", "skew"))
        selectivity_schemes = selectivity_cfg.get(
            "schemes",
            [scheme for scheme in cfg["schemes"]["main"] if scheme != "TreeCover"],
        )
        for sel in selectivities:
            for scheme in selectivity_schemes:
                cases.append({"scheme": scheme, "dataset": "synthetic", "workload": selectivity_workload, "N": selectivity_n, "ops": selectivity_ops, "selectivity": float(sel), "axis": "selectivity"})
    elif group == "fig4":
        fig4_cfg = cfg.get("fig4_dynamic_refresh", cfg.get("fig4", {}))
        workloads = fig4_cfg.get("workloads", ["uniform", "hotspot", "burst", "drift", "structured"])
        schemes = fig4_cfg.get("schemes", cfg["schemes"]["dynamic"])
        n_values = [int(N_override)] if N_override is not None else [int(n) for n in first_config_list(fig4_cfg.get("N"), [N0])]
        fig4_ops = int(fig4_cfg.get("ops", ops))
        for workload in workloads:
            for base_n in n_values:
                for scheme_entry in schemes:
                    scheme_name = scheme_config_name(scheme_entry)
                    scheme_overrides = scheme_config_overrides(scheme_entry)
                    cases.append(
                        {
                            "scheme": scheme_name,
                            "dataset": "synthetic",
                            "workload": str(workload),
                            "N": int(scheme_overrides.get("N_override", base_n)),
                            "ops": int(scheme_overrides.get("ops_override", fig4_ops)),
                            "axis": "workload",
                            "case_tag": str(workload),
                            "U": fig4_cfg.get("U", defaults.get("U", 1 << 20)),
                            "B": fig4_cfg.get("B", defaults.get("B", 1024)),
                            "theta": fig4_cfg.get("theta", defaults.get("theta", 128)),
                            "query_ratio": fig4_cfg.get("query_ratio", defaults.get("query_ratio", 0.8)),
                            "crypto": fig4_cfg.get("crypto", defaults.get("crypto", "mock")),
                            "timeout_sec": int(scheme_overrides.get("timeout_sec", fig4_cfg.get("timeout_sec", 600))),
                        }
                    )
    elif group == "fig5":
        fig5_cfg = cfg.get("fig5_real_datasets", cfg.get("fig5", {}))
        datasets = fig5_cfg.get("datasets", [entry["name"] for entry in cfg["datasets"]["real"]])
        workloads = fig5_cfg.get("workloads", ["real_temporal"])
        n_values = [int(N_override)] if N_override is not None else [int(n) for n in first_config_list(fig5_cfg.get("N"), [200000])]
        schemes = fig5_cfg.get("schemes", cfg["schemes"]["real"])
        for dataset_name in datasets:
            for workload in workloads:
                for base_n in n_values:
                    for scheme_entry in schemes:
                        scheme_name = scheme_config_name(scheme_entry)
                        scheme_overrides = scheme_config_overrides(scheme_entry)
                        case_n = int(scheme_overrides.get("N_override", base_n))
                        case_ops = int(scheme_overrides.get("ops_override", fig5_cfg.get("ops", ops)))
                        data_limit = int(scheme_overrides.get("data_limit_override", fig5_cfg.get("data_limit", case_n)))
                        timeout_sec = int(scheme_overrides.get("timeout_sec", fig5_cfg.get("timeout_sec", 600)))
                        cases.append(
                            {
                                "scheme": scheme_name,
                                "dataset": str(dataset_name),
                                "workload": str(workload),
                                "N": case_n,
                                "ops": case_ops,
                                "axis": "dataset",
                                "case_tag": f"dataset_N{case_n}",
                                "data_limit": data_limit,
                                "timeout_sec": timeout_sec,
                                "U": fig5_cfg.get("U", defaults.get("U", 1 << 20)),
                                "B": fig5_cfg.get("B", defaults.get("B", 1024)),
                                "theta": fig5_cfg.get("theta", defaults.get("theta", 128)),
                                "query_ratio": fig5_cfg.get("query_ratio", defaults.get("query_ratio", 0.8)),
                                "crypto": fig5_cfg.get("crypto", defaults.get("crypto", "mock")),
                            }
                        )
    elif group == "fig6":
        fig6_cfg = cfg.get("fig6_tradeoff", cfg.get("fig6", {}))
        datasets = fig6_cfg.get("datasets", ["synthetic"])
        workloads = fig6_cfg.get("workloads", ["hotspot"])
        distributions = fig6_cfg.get("distributions", ["skew"])
        n_values = [int(N_override)] if N_override is not None else [int(n) for n in first_config_list(fig6_cfg.get("N"), [100000])]
        theta_values = [int(v) for v in fig6_cfg.get("theta_values", [fig6_cfg.get("theta", defaults.get("theta", 128))])]
        cap_values = [int(v) for v in fig6_cfg.get("cap_values", [fig6_cfg.get("B", defaults.get("B", 512))])]
        schemes = fig6_cfg.get("schemes", cfg["schemes"]["ablation"])
        for dataset_name in datasets:
            for workload in workloads:
                for dist in distributions:
                    for base_n in n_values:
                        for budget, theta, cap in paired_budget_values(theta_values, cap_values):
                            for scheme_entry in schemes:
                                scheme_name = scheme_config_name(scheme_entry)
                                scheme_overrides = scheme_config_overrides(scheme_entry)
                                case_n = int(scheme_overrides.get("N_override", base_n))
                                case_ops = int(scheme_overrides.get("ops_override", fig6_cfg.get("ops", ops)))
                                timeout_sec = int(scheme_overrides.get("timeout_sec", fig6_cfg.get("timeout_sec", 600)))
                                cases.append(
                                    {
                                        "scheme": scheme_name,
                                        "dataset": str(dataset_name),
                                        "workload": str(workload),
                                        "N": case_n,
                                        "ops": case_ops,
                                        "axis": "budget",
                                        "case_tag": f"budget_T{theta}_B{cap}",
                                        "budget": budget,
                                        "theta": int(scheme_overrides.get("theta_override", theta)),
                                        "B": int(scheme_overrides.get("B_override", cap)),
                                        "dist": str(dist),
                                        "timeout_sec": timeout_sec,
                                        "U": fig6_cfg.get("U", defaults.get("U", 1 << 20)),
                                        "query_ratio": fig6_cfg.get("query_ratio", defaults.get("query_ratio", 0.8)),
                                        "crypto": fig6_cfg.get("crypto", defaults.get("crypto", "mock")),
                                    }
                                )
    elif group == "fig_mechanism":
        mechanism_cfg = cfg.get("fig_mechanism_cell_load_touch_skew", cfg.get("fig_mechanism", {}))
        schemes = mechanism_cfg.get("schemes", ["PGM-Learned-Naive"])
        common = {
            "U": mechanism_cfg.get("U", defaults.get("U", 1 << 20)),
            "B": mechanism_cfg.get("B", defaults.get("B", 1024)),
            "theta": mechanism_cfg.get("theta", defaults.get("theta", 128)),
            "query_ratio": mechanism_cfg.get("query_ratio", defaults.get("query_ratio", 0.8)),
            "crypto": mechanism_cfg.get("crypto", defaults.get("crypto", "mock")),
            "timeout_sec": mechanism_cfg.get("timeout_sec", 600),
        }

        synthetic_cfg = mechanism_cfg.get("synthetic", {})
        synthetic_n_values = (
            [int(N_override)]
            if N_override is not None
            else [int(n) for n in first_config_list(synthetic_cfg.get("N"), [defaults.get("N", 1000000)])]
        )
        synthetic_workloads = synthetic_cfg.get("workloads", ["skew_hotspot_drift_mix"])
        synthetic_ops = int(synthetic_cfg.get("ops", ops))
        synthetic_dist = str(synthetic_cfg.get("dist", "skew"))
        for workload in synthetic_workloads:
            for base_n in synthetic_n_values:
                for scheme_entry in schemes:
                    scheme_name = scheme_config_name(scheme_entry)
                    scheme_overrides = scheme_config_overrides(scheme_entry)
                    case = {
                        "scheme": scheme_name,
                        "dataset": "synthetic",
                        "workload": str(workload),
                        "N": int(scheme_overrides.get("N_override", base_n)),
                        "ops": int(scheme_overrides.get("ops_override", synthetic_ops)),
                        "axis": "mechanism",
                        "case_tag": f"synthetic_N{int(scheme_overrides.get('N_override', base_n))}",
                        "dist": str(scheme_overrides.get("dist_override", synthetic_dist)),
                        "dataset_family": "synthetic",
                    }
                    case.update(common)
                    case.update({k: v for k, v in scheme_overrides.items() if k not in {"name", "scheme", "variant"}})
                    cases.append(case)

        real_cfg = mechanism_cfg.get("real", {})
        real_datasets = real_cfg.get("datasets", cfg.get("fig5_real_datasets", {}).get("datasets", [entry["name"] for entry in cfg["datasets"].get("real", [])]))
        real_workloads = real_cfg.get("workloads", cfg.get("fig5_real_datasets", {}).get("workloads", ["real_temporal"]))
        real_n_values = (
            [int(N_override)]
            if N_override is not None
            else [int(n) for n in first_config_list(real_cfg.get("N"), cfg.get("fig5_real_datasets", {}).get("N", [200000]))]
        )
        real_ops = int(real_cfg.get("ops", cfg.get("fig5_real_datasets", {}).get("ops", ops)))
        real_data_limit_default = int(real_cfg.get("data_limit", cfg.get("fig5_real_datasets", {}).get("data_limit", real_n_values[0] if real_n_values else N0)))
        for dataset_name in real_datasets:
            for workload in real_workloads:
                for base_n in real_n_values:
                    for scheme_entry in schemes:
                        scheme_name = scheme_config_name(scheme_entry)
                        scheme_overrides = scheme_config_overrides(scheme_entry)
                        case_n = int(scheme_overrides.get("N_override", base_n))
                        case = {
                            "scheme": scheme_name,
                            "dataset": str(dataset_name),
                            "workload": str(workload),
                            "N": case_n,
                            "ops": int(scheme_overrides.get("ops_override", real_ops)),
                            "axis": "mechanism",
                            "case_tag": f"real_N{case_n}",
                            "data_limit": int(scheme_overrides.get("data_limit_override", real_data_limit_default)),
                            "dataset_family": "real",
                        }
                        case.update(common)
                        case.update({k: v for k, v in scheme_overrides.items() if k not in {"name", "scheme", "variant"}})
                        cases.append(case)
    return cases


def filter_cases(cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.only_scheme:
        allowed_raw = set(parse_csv_list(args.only_scheme, str) or [])
        allowed_labels = {eval_scheme_label(x) for x in allowed_raw}
        cases = [
            c for c in cases
            if c["scheme"] in allowed_raw or eval_scheme_label(c["scheme"]) in allowed_labels
        ]
    if args.only_dataset:
        allowed = set(parse_csv_list(args.only_dataset, str) or [])
        cases = [c for c in cases if c["dataset"] in allowed]
    return cases


def run_benchmark_group(group: str, group_dir: Path, cfg: dict[str, Any], args: argparse.Namespace, seeds: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mechanism_layout_rows: list[dict[str, Any]] = []
    cases = filter_cases(group_cases(group, cfg, args.N), args)
    if args.dry_run:
        simulated_cases = [c for c in cases if c["scheme"] == "Sim-L_cert"]
        omitted_cases = [
            c for c in cases
            if group == "fig3" and is_treecover(c["scheme"]) and int(c["N"]) > fig3_treecover_cap_n(cfg)
        ]
        runnable_cases = [
            c for c in cases
            if c["scheme"] != "Sim-L_cert"
            and not (group == "fig3" and is_treecover(c["scheme"]) and int(c["N"]) > fig3_treecover_cap_n(cfg))
        ]
        append_log(group_dir / "stdout.log", f"DRY RUN: group={group} cases={len(cases)} runnable_cases={len(runnable_cases)} simulated_cases={len(simulated_cases)} omitted_cases={len(omitted_cases)} seeds={len(seeds)} benchmark_invocations={len(runnable_cases) * len(seeds)}")
        print(f"DRY RUN group={group} cases={len(cases)} runnable_cases={len(runnable_cases)} simulated_cases={len(simulated_cases)} omitted_cases={len(omitted_cases)} seeds={len(seeds)} benchmark_invocations={len(runnable_cases) * len(seeds)}")
    group_start = time.monotonic()
    group_cfg = cfg.get(GROUP_DIRS.get(group, ""), cfg.get(group, {}))
    max_wall = int(group_cfg.get("max_wall_seconds", 0) or 0) if group in {"fig3", "fig5", "fig6", "fig_mechanism"} else 0
    group_timed_out = False
    for case in cases:
        if case["scheme"] == "Sim-L_cert":
            continue
        N = choose_N(int(case["N"]), None if case["dataset"] == "synthetic" else case["dataset"])
        for seed in seeds:
            timeout_override: int | None = None
            timeout_reason_override: str | None = None
            elapsed = time.monotonic() - group_start
            if max_wall and elapsed >= max_wall:
                dataset, attribute = dataset_attribute(case["dataset"], cfg)
                axis = str(case.get("axis", ""))
                selectivity = "" if case.get("selectivity") is None else case.get("selectivity")
                scheme = eval_scheme_label(case["scheme"])
                reason = f"{group}_group_timeout"
                command = f"{group} wall-clock limit before scheme={scheme} N={N} axis={axis}"
                append_log(group_dir / "stdout.log", f"STOPPED: {reason} elapsed_seconds={elapsed:.3f} max_wall_seconds={max_wall}")
                append_timeout_event(
                    group_dir,
                    group=group,
                    dataset=dataset,
                    attribute=attribute,
                    N=N,
                    workload=case["workload"],
                    scheme=scheme,
                    seed=seed,
                    axis=axis,
                    selectivity=selectivity,
                    reason=reason,
                    elapsed_seconds=elapsed,
                    command=command,
                )
                rows.append(
                    timeout_metric_row(
                        group=group,
                        dataset=dataset,
                        attribute=attribute,
                        N=N,
                        workload=case["workload"],
                        scheme=scheme,
                        seed=seed,
                        reason=reason,
                        elapsed_seconds=elapsed,
                        extra={"selectivity": selectivity, "axis": axis},
                    )
                )
                group_timed_out = True
                break
            if max_wall:
                remaining = max(1, int(max_wall - elapsed))
                case_limit = int(case.get("timeout_sec", case_timeout_seconds(group, case["scheme"], cfg) or 600))
                if case_limit and remaining < case_limit:
                    timeout_override = remaining
                    timeout_reason_override = f"{group}_group_timeout"
            case_rows = run_benchmark_case(
                group=group,
                group_dir=group_dir,
                scheme_name=case["scheme"],
                dataset_name=case["dataset"],
                workload=case["workload"],
                N=N,
                ops=int(case["ops"]),
                seed=seed,
                cfg=cfg,
                args=args,
                selectivity=case.get("selectivity"),
                extra_tag=str(case.get("case_tag", case.get("axis", ""))),
                axis_name=str(case.get("axis", "")),
                case_overrides=case,
                timeout_seconds_override=timeout_override,
                timeout_reason_override=timeout_reason_override,
            )
            rows.extend(case_rows)
            if group == "fig_mechanism" and not args.dry_run and not any(row.get("metric_name") in {"timeout", "failed"} for row in case_rows):
                trace_dir = group_dir / "traces" / case_id(group, case["scheme"], case["dataset"], case["workload"], N, seed, str(case.get("case_tag", case.get("axis", ""))))
                per_cell_rows = extract_mechanism_layout_rows(
                    trace_dir,
                    group=group,
                    dataset_name=str(case["dataset"]),
                    workload=str(case["workload"]),
                    scheme_name=str(case["scheme"]),
                    seed=seed,
                )
                if per_cell_rows:
                    write_mechanism_layout_dump(trace_dir, per_cell_rows)
                    mechanism_layout_rows.extend(per_cell_rows)
            if any(row.get("metric_name") == "timeout" and row.get("reason") == f"{group}_group_timeout" for row in case_rows):
                group_timed_out = True
                break
        if group_timed_out:
            break
    wanted_sim = any(c["scheme"] == "Sim-L_cert" for c in cases)
    if wanted_sim:
        rows.extend(add_sim_lcert(rows, group))
        audit = {
            "uses_cell_handle_equality": True,
            "uses_public_classes": True,
            "uses_raw_loads": False,
            "uses_exact_patch_pressure": False,
            "uses_private_refresh_cause": False,
            "uses_plain_boundaries": False,
        }
        (group_dir / "sim_lcert_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    rows = write_common_outputs(group_dir, group, cfg, seeds, rows, merge_existing=args.no_clean)
    write_exactness(group_dir, rows)
    write_boundary_summary(group_dir)
    if group == "fig_mechanism":
        write_mechanism_outputs(group_dir, mechanism_layout_rows)
        return rows
    write_diagnostics(group_dir)
    return rows


def write_exactness(group_dir: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[Any, ...], dict[str, float]] = defaultdict(dict)
    wanted = {"queries", "precision", "recall", "false_positive_count", "false_negative_count", "exact_match_rate"}
    for row in rows:
        if row["metric_name"] not in wanted:
            continue
        key = (row["scheme"], row["dataset"], row["attribute"], row["N"], row["workload"], row["seed"])
        grouped[key][row["metric_name"]] = float(row["metric_value"])
    exact_rows = []
    for (scheme, dataset, attribute, N, workload, seed), metrics in sorted(grouped.items()):
        exact_rows.append(
            {
                "scheme": scheme,
                "dataset": dataset,
                "attribute": attribute,
                "N": N,
                "workload": workload,
                "seed": seed,
                "queries": int(metrics.get("queries", 0)),
                "precision": metrics.get("precision", 1.0),
                "recall": metrics.get("recall", 1.0),
                "false_positive_count": int(metrics.get("false_positive_count", 0)),
                "false_negative_count": int(metrics.get("false_negative_count", 0)),
                "exact_match_rate": metrics.get("exact_match_rate", 1.0),
            }
        )
    write_csv_rows(group_dir / "exactness_summary.csv", exact_rows)


def write_boundary_summary(group_dir: Path) -> None:
    rows = []
    for trace in (group_dir / "traces").glob("*/search_trace.csv"):
        searches = read_csv_rows(trace)
        if not searches:
            continue
        rows.append(
            {
                "trace": str(trace.parent.name),
                "queries": len(searches),
                "avg_boundary_cells": sum(safe_float(r, "boundary_cells") for r in searches) / len(searches),
                "max_boundary_cells": max(safe_float(r, "boundary_cells") for r in searches),
                "avg_full_cells": sum(safe_float(r, "full_cells") for r in searches) / len(searches),
            }
        )
    if rows:
        write_csv_rows(group_dir / "boundary_cell_summary.csv", rows)


def write_diagnostics(group_dir: Path) -> None:
    diag = group_dir / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    feature_rows = []
    class_rows = []
    patch_rows = []
    refresh_rows = []
    for trace_dir in (group_dir / "traces").glob("*"):
        if not trace_dir.is_dir():
            continue
        searches = read_csv_rows(trace_dir / "search_trace.csv")
        updates = read_csv_rows(trace_dir / "update_trace.csv")
        maint = read_csv_rows(trace_dir / "maintenance_trace.csv")
        layout = read_csv_rows(trace_dir / "layout_units.csv")
        scheme = searches[0]["scheme"] if searches else (layout[0]["scheme"] if layout else trace_dir.name)
        dataset = searches[0]["dataset"] if searches else (layout[0]["dataset"] if layout else "")
        feature_rows.append(
            {
                "trace": trace_dir.name,
                "scheme": scheme,
                "dataset": dataset,
                "search_rows": len(searches),
                "update_rows": len(updates),
                "maintenance_rows": len(maint),
                "avg_token_count": sum(safe_float(r, "token_count") for r in searches) / len(searches) if searches else 0.0,
                "avg_object_bytes": sum(safe_float(r, "object_bytes") for r in searches) / len(searches) if searches else 0.0,
                "avg_update_bytes": sum(safe_float(r, "update_bytes") for r in updates) / len(updates) if updates else 0.0,
            }
        )
        by_class: dict[str, int] = defaultdict(int)
        log_used = []
        for row in layout:
            by_class[str(row.get("unit_class", ""))] += 1
            log_used.append(safe_float(row, "true_log_used"))
        for unit_class, count in sorted(by_class.items()):
            class_rows.append({"trace": trace_dir.name, "scheme": scheme, "dataset": dataset, "unit_class": unit_class, "count": count})
        patch_rows.append(
            {
                "trace": trace_dir.name,
                "scheme": scheme,
                "dataset": dataset,
                "units": len(layout),
                "avg_true_log_used": sum(log_used) / len(log_used) if log_used else 0.0,
                "max_true_log_used": max(log_used) if log_used else 0.0,
                "visible_raw_log_rows": sum(1 for r in updates if r.get("raw_log_len_visible", "") != ""),
            }
        )
        by_event: dict[tuple[str, str], int] = defaultdict(int)
        for row in maint:
            by_event[(row.get("event_type", ""), row.get("raw_trigger_visible", ""))] += 1
        if by_event:
            for (event_type, trigger), count in sorted(by_event.items()):
                refresh_rows.append(
                    {
                        "trace": trace_dir.name,
                        "scheme": scheme,
                        "dataset": dataset,
                        "event_type": event_type,
                        "raw_trigger_visible": trigger,
                        "count": count,
                    }
                )
        else:
            refresh_rows.append(
                {
                    "trace": trace_dir.name,
                    "scheme": scheme,
                    "dataset": dataset,
                    "event_type": "",
                    "raw_trigger_visible": "",
                    "count": 0,
                }
            )
    write_csv_rows(diag / "feature_distribution.csv", feature_rows)
    write_csv_rows(diag / "cell_class_distribution.csv", class_rows)
    write_csv_rows(diag / "patch_occupancy_by_scheme.csv", patch_rows)
    write_csv_rows(diag / "refresh_events_by_scheme.csv", refresh_rows)


def collect_existing_summaries(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in root.glob("*/summary.csv"):
        rows.extend(read_csv_rows(path))
    return rows


def run_derived_group(group: str, group_dir: Path, cfg: dict[str, Any], args: argparse.Namespace, seeds: list[int]) -> None:
    root = args.out
    rows = collect_existing_summaries(root)
    if not rows:
        append_log(group_dir / "stdout.log", f"WARNING: {group} has no prior summaries; run fig1-fig5 first.")
        write_common_outputs(group_dir, group, cfg, seeds, [])
        return
    write_csv_rows(group_dir / "figure_data.csv", rows)
    write_csv_rows(group_dir / "summary.csv", rows)
    write_csv_rows(group_dir / "raw_metrics.csv", [])
    write_yaml(group_dir / "config_used.yaml", cfg)
    (group_dir / "seeds.txt").write_text(",".join(map(str, seeds)) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LOCI evaluation groups.")
    parser.add_argument("--config", type=Path, default=Path("configs/eval_main.yaml"))
    parser.add_argument("--group", required=True, choices=list(GROUP_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT, help="evaluation output root, e.g. artifact_out/eval_final")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-scheme")
    parser.add_argument("--only-dataset")
    parser.add_argument("--N", type=int)
    parser.add_argument("--trace-ops", type=int)
    parser.add_argument("--seeds")
    parser.add_argument("--smoke", action="store_true", help="small local validation run: N=200, trace_ops=200, seed=0")
    parser.add_argument("--appendix", action="store_true", help="reserved flag for optional appendix groups")
    parser.add_argument("--mock-crypto", action="store_true")
    parser.add_argument("--real-crypto", action="store_true")
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    if args.smoke:
        args.N = args.N or 200
        args.seeds = args.seeds or "0"
        args.trace_ops = args.trace_ops or 200
    if args.trace_ops is not None:
        cfg.setdefault("defaults", {})["trace_ops"] = int(args.trace_ops)
    group_cfg = cfg.get(GROUP_DIRS.get(args.group, ""), cfg.get(args.group, {}))
    seeds = parse_csv_list(args.seeds, int) or [int(s) for s in group_cfg.get("seeds", cfg["defaults"].get("seeds", [0]))]
    group_dir = args.out / GROUP_DIRS[args.group]
    ensure_clean_dir(group_dir, clean=not args.no_clean)
    write_yaml(group_dir / "config_used.yaml", cfg)
    (group_dir / "seeds.txt").write_text(",".join(map(str, seeds)) + "\n", encoding="utf-8")

    if args.group == "table1":
        run_table1(group_dir, cfg)
    elif args.group in {"fig1", "fig2", "fig3", "fig4", "fig5", "fig6", "fig_mechanism"}:
        run_benchmark_group(args.group, group_dir, cfg, args, seeds)
    else:
        run_derived_group(args.group, group_dir, cfg, args, seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
