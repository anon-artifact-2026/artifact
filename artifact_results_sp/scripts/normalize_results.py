#!/usr/bin/env python3
"""Normalize LOCI paper experiment outputs into a provenance-rich long CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


MASTER_FIELDS = [
    "paper_fig",
    "benchmark_group",
    "profile",
    "source_csv",
    "source_archive_or_run_id",
    "source_row_id",
    "config_file",
    "config_hash",
    "git_commit_if_available",
    "host",
    "os",
    "cpu",
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
    "timeout_s",
    "metric_name",
    "metric_value",
    "metric_unit",
    "metric_source",
    "evaluator",
    "auc_mode",
    "is_paper_metric",
    "notes",
    "view",
    "task",
    "feature_scope",
    "label_source",
    "allowed_features_used",
    "forbidden_features_used",
    "interpretation",
    "simulator_missing",
]


FIGURE_MAP = [
    {
        "paper_fig": "fig6_mechanism",
        "benchmark_group": "fig_mechanism",
        "group_dir": "fig_mechanism_cell_load_touch_skew",
        "sources": "mechanism CSV",
    },
    {
        "paper_fig": "fig7_attack_auc",
        "benchmark_group": "fig2_component_ablation",
        "group_dir": "fig2_component_ablation",
        "sources": "attack_eval.py outputs",
    },
    {
        "paper_fig": "fig8_absolute_cost",
        "benchmark_group": "fig2_component_ablation",
        "group_dir": "fig2_component_ablation",
        "sources": "bench_wide.csv only",
    },
    {
        "paper_fig": "fig9_scale_select",
        "benchmark_group": "fig3_scalability_selectivity",
        "group_dir": "fig3_scalability_selectivity",
        "sources": "bench_wide.csv",
    },
    {
        "paper_fig": "fig10_workload",
        "benchmark_group": "fig4_dynamic_refresh",
        "group_dir": "fig4_dynamic_refresh",
        "sources": "attack_eval.py outputs",
    },
    {
        "paper_fig": "fig11_real_trace",
        "benchmark_group": "fig5_real_datasets",
        "group_dir": "fig5_real_datasets",
        "sources": "attack_eval.py outputs + bench_wide.csv",
    },
    {
        "paper_fig": "fig12_budget",
        "benchmark_group": "fig6_tradeoff",
        "group_dir": "fig6_tradeoff",
        "sources": "attack_eval.py outputs + bench_wide.csv",
    },
]


METRIC_DEFINITIONS = [
    ("layout_shape_auc", "AUC for certified layout-shape probe from attack_eval.py layout_class_auc", "auc", "attack_eval.py", "raw_auc", "true"),
    ("patch_pressure_auc", "AUC for certified patch-pressure probe from attack_eval.py log_growth_auc", "auc", "attack_eval.py", "raw_auc", "true"),
    ("maintenance_cause_auc", "AUC for certified maintenance-cause probe from attack_eval.py maintenance_auc", "auc", "attack_eval.py", "raw_auc", "true"),
    ("layout_shape_adv_auc", "max(layout_shape_auc, 1-layout_shape_auc)", "auc", "derived", "adv_auc", "true"),
    ("patch_pressure_adv_auc", "max(patch_pressure_auc, 1-patch_pressure_auc)", "auc", "derived", "adv_auc", "true"),
    ("maintenance_cause_adv_auc", "max(maintenance_cause_auc, 1-maintenance_cause_auc)", "auc", "derived", "adv_auc", "true"),
    ("max_cert_probe_auc", "max of the three certified-probe adversarial AUCs", "auc", "derived", "adv_auc", "true"),
    ("diagnostic_region_auc", "Diagnostic dense-region AUC preserved from attack_eval.py region_auc; excluded from paper certified-probe max", "auc", "attack_eval.py", "raw_auc", "false"),
    ("diagnostic_hotspot_auc", "Diagnostic hotspot AUC preserved from attack_eval.py hotspot_auc; excluded from paper certified-probe max", "auc", "attack_eval.py", "raw_auc", "false"),
    ("search_latency_ms", "Benchmark average search latency", "ms", "bench_wide.csv", "not_auc", "true"),
    ("patch_update_latency_ms", "Benchmark fixed-class patch update latency when available", "ms", "bench_wide.csv", "not_auc", "true"),
    ("update_latency_ms", "Benchmark average update latency; included for scale/selectivity compatibility", "ms", "bench_wide.csv", "not_auc", "true"),
    ("maintenance_latency_ms", "Benchmark maintenance portion of update path when available", "ms", "bench_wide.csv", "not_auc", "true"),
    ("response_bytes", "Per-search response bytes, computed as response_bytes/searches when searches is present", "bytes", "bench_wide.csv", "not_auc", "true"),
    ("response_mib", "response_bytes divided by 2^20", "MiB", "derived", "not_auc", "true"),
    ("server_storage_bytes", "Server-side storage bytes", "bytes", "bench_wide.csv", "not_auc", "true"),
    ("server_storage_mib", "server_storage_bytes divided by 2^20", "MiB", "derived", "not_auc", "true"),
    ("refresh_count", "Benchmark refresh event count", "count", "bench_wide.csv", "not_auc", "true"),
    ("forced_rollover_count", "Forced public rollover/log refresh count when available", "count", "bench_wide.csv", "not_auc", "true"),
    ("true_cell_load", "Mechanism diagnostic raw cell load", "records", "mechanism CSV", "not_auc", "true"),
    ("real_cell_load", "Mechanism diagnostic real-trace cell load", "records", "mechanism CSV", "not_auc", "true"),
    ("update_touches", "Mechanism diagnostic update touches per cell", "count", "mechanism CSV", "not_auc", "true"),
    ("touch_skew", "Mechanism diagnostic skew summary computed by make_paper_summaries.py", "ratio", "derived", "not_auc", "true"),
    ("density_lcert_auc", "Residual certified-view density probe restricted to declared Lcert features", "auc", "lcert_residual_eval.py", "raw_auc", "false"),
    ("density_lcert_adv_auc", "max(density_lcert_auc, 1-density_lcert_auc)", "auc", "lcert_residual_eval.py", "adv_auc", "false"),
    ("hotspot_lcert_auc", "Residual certified-view hotspot probe restricted to declared Lcert features", "auc", "lcert_residual_eval.py", "raw_auc", "false"),
    ("hotspot_lcert_adv_auc", "max(hotspot_lcert_auc, 1-hotspot_lcert_auc)", "auc", "lcert_residual_eval.py", "adv_auc", "false"),
    ("adjacency_lcert_auc", "Residual certified-view adjacency probe over repeated certified cover relations", "auc", "lcert_residual_eval.py", "raw_auc", "false"),
    ("adjacency_lcert_adv_auc", "max(adjacency_lcert_auc, 1-adjacency_lcert_auc)", "auc", "lcert_residual_eval.py", "adv_auc", "false"),
]

RAW_PROFILES = {"paper_full", "quick"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def float_or_blank(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        x = float(value)
    except Exception:
        return ""
    if math.isnan(x) or math.isinf(x):
        return ""
    return repr(x)


def parse_float(row: dict[str, str], names: list[str]) -> float | None:
    for name in names:
        value = row.get(name, "")
        if value != "":
            try:
                return float(value)
            except ValueError:
                pass
    return None


def adv_auc(value: float) -> float:
    return max(value, 1.0 - value)


def git_commit() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=True)
        return proc.stdout.strip()
    except Exception:
        return ""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def copy_if_exists(src: Path, dst: Path) -> Path | None:
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return dst
    shutil.copy2(src, dst)
    return dst


def clear_profile_raw(artifact_root: Path, profile: str) -> None:
    if profile not in RAW_PROFILES:
        raise RuntimeError(f"refusing to clear raw output for unsupported profile {profile!r}")
    artifact_resolved = artifact_root.resolve()
    raw_root = (artifact_root / "raw").resolve()
    try:
        raw_root.relative_to(artifact_resolved)
    except ValueError as exc:
        raise RuntimeError(f"refusing to clear raw root outside artifact root: {raw_root}") from exc
    target = (raw_root / profile).resolve()
    expected = (raw_root / profile).resolve()
    if target != expected or target.name != profile:
        raise RuntimeError(f"refusing to clear unexpected raw profile path: {target}")
    try:
        target.relative_to(raw_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to clear path outside artifact raw root: {target}") from exc
    if target == raw_root:
        raise RuntimeError(f"refusing to clear raw root itself: {target}")
    print(f"clearing stale raw profile directory: {target}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def parse_attack_name(path: Path) -> dict[str, str]:
    stem = path.stem
    parts = stem.split("__")
    meta = {"seed": "", "N": "", "scheme": "", "dataset": "", "workload": "", "budget": ""}
    if len(parts) >= 6:
        meta["scheme"] = parts[1]
        meta["dataset"] = parts[2]
        meta["workload"] = parts[3]
        for p in parts[4:]:
            if p.startswith("N"):
                meta["N"] = p[1:]
            elif re.fullmatch(r"s\d+", p):
                meta["seed"] = p[1:]
            elif p.startswith("budget_"):
                meta["budget"] = p.replace("budget_T", "").split("_", 1)[0]
    return meta


def base_row(
    *,
    paper_fig: str,
    benchmark_group: str,
    profile: str,
    source_csv: Path,
    source_row_id: str,
    run_root: Path,
    config_file: Path,
    config_hash: str,
    machine: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "paper_fig": paper_fig,
        "benchmark_group": benchmark_group,
        "profile": profile,
        "source_csv": str(source_csv).replace("\\", "/"),
        "source_archive_or_run_id": run_root.name,
        "source_row_id": source_row_id,
        "config_file": str(config_file).replace("\\", "/"),
        "config_hash": config_hash,
        "git_commit_if_available": git_commit(),
        "host": machine.get("name", platform.node()),
        "os": machine.get("os", platform.platform()),
        "cpu": machine.get("cpu", platform.processor()),
        "seed": meta.get("seed", ""),
        "dataset": meta.get("dataset", ""),
        "workload": meta.get("workload", ""),
        "scheme": meta.get("scheme", ""),
        "variant": meta.get("variant", ""),
        "N": meta.get("N", ""),
        "ops": meta.get("ops", ""),
        "query_ratio": meta.get("query_ratio", ""),
        "update_ratio": meta.get("update_ratio", ""),
        "budget": meta.get("budget", ""),
        "selectivity": meta.get("selectivity", ""),
        "timeout_s": meta.get("timeout_s", ""),
        "metric_name": "",
        "metric_value": "",
        "metric_unit": "",
        "metric_source": "",
        "evaluator": "",
        "auc_mode": "not_auc",
        "is_paper_metric": "true",
        "notes": "",
        "view": meta.get("view", ""),
        "task": meta.get("task", ""),
        "feature_scope": meta.get("feature_scope", ""),
        "label_source": meta.get("label_source", ""),
        "allowed_features_used": meta.get("allowed_features_used", ""),
        "forbidden_features_used": meta.get("forbidden_features_used", ""),
        "interpretation": meta.get("interpretation", ""),
        "simulator_missing": meta.get("simulator_missing", ""),
    }


def normalize_attack_file(
    *,
    path: Path,
    copied_path: Path,
    paper_fig: str,
    benchmark_group: str,
    profile: str,
    run_root: Path,
    config_file: Path,
    config_hash: str,
    machine: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = read_csv(path)
    if not rows:
        return []
    src = rows[0]
    meta = parse_attack_name(path)
    if src.get("scheme"):
        meta["scheme"] = src["scheme"]
    if src.get("dataset") and not meta.get("dataset"):
        meta["dataset"] = src["dataset"]
    raw = {
        "layout_shape_auc": parse_float(src, ["layout_class_auc", "shape_auc"]),
        "patch_pressure_auc": parse_float(src, ["log_growth_auc", "patch_pressure_auc"]),
        "maintenance_cause_auc": parse_float(src, ["maintenance_auc", "maintenance_cause_auc"]),
    }
    out: list[dict[str, Any]] = []
    if any(v is None for v in raw.values()):
        return out
    for name, value in raw.items():
        row = base_row(
            paper_fig=paper_fig,
            benchmark_group=benchmark_group,
            profile=profile,
            source_csv=copied_path,
            source_row_id="row0",
            run_root=run_root,
            config_file=config_file,
            config_hash=config_hash,
            machine=machine,
            meta=meta,
        )
        row.update(metric_name=name, metric_value=repr(value), metric_unit="auc", metric_source="attack_eval.py", evaluator="attack_eval", auc_mode="raw_auc")
        out.append(row)
    adv = {name.replace("_auc", "_adv_auc"): adv_auc(float(value)) for name, value in raw.items() if value is not None}
    for name, value in adv.items():
        row = base_row(
            paper_fig=paper_fig,
            benchmark_group=benchmark_group,
            profile=profile,
            source_csv=copied_path,
            source_row_id="row0",
            run_root=run_root,
            config_file=config_file,
            config_hash=config_hash,
            machine=machine,
            meta=meta,
        )
        raw_name = name.replace("_adv_auc", "_auc")
        row.update(metric_name=name, metric_value=repr(value), metric_unit="auc", metric_source="derived", evaluator="derived_summary", auc_mode="adv_auc", notes=f"derived_from={raw_name}")
        out.append(row)
    max_value = max(adv.values())
    row = base_row(
        paper_fig=paper_fig,
        benchmark_group=benchmark_group,
        profile=profile,
        source_csv=copied_path,
        source_row_id="row0",
        run_root=run_root,
        config_file=config_file,
        config_hash=config_hash,
        machine=machine,
        meta=meta,
    )
    row.update(
        metric_name="max_cert_probe_auc",
        metric_value=repr(max_value),
        metric_unit="auc",
        metric_source="derived",
        evaluator="derived_summary",
        auc_mode="adv_auc",
        notes="derived_from=layout_shape_adv_auc,patch_pressure_adv_auc,maintenance_cause_adv_auc",
    )
    out.append(row)
    for source_name, metric_name in [("region_auc", "diagnostic_region_auc"), ("hotspot_auc", "diagnostic_hotspot_auc")]:
        value = parse_float(src, [source_name])
        if value is None:
            continue
        diag = base_row(
            paper_fig=paper_fig,
            benchmark_group=benchmark_group,
            profile=profile,
            source_csv=copied_path,
            source_row_id="row0",
            run_root=run_root,
            config_file=config_file,
            config_hash=config_hash,
            machine=machine,
            meta=meta,
        )
        diag.update(metric_name=metric_name, metric_value=repr(value), metric_unit="auc", metric_source="attack_eval.py", evaluator="attack_eval", auc_mode="raw_auc", is_paper_metric="false", notes=f"preserved_from={source_name}; excluded_from=max_cert_probe_auc")
        out.append(diag)
    return out


def normalize_bench_file(
    *,
    path: Path,
    copied_path: Path,
    paper_fig: str,
    benchmark_group: str,
    profile: str,
    run_root: Path,
    config_file: Path,
    config_hash: str,
    machine: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = read_csv(path)
    out: list[dict[str, Any]] = []
    metric_fields = [
        ("search_latency_ms", ["avg_query_ms", "search_latency_ms"], "ms"),
        ("patch_update_latency_ms", ["patch_update_latency_ms", "update_total_latency_ms", "avg_update_ms", "update_latency_ms"], "ms"),
        ("maintenance_latency_ms", ["maintenance_latency_ms"], "ms"),
        ("update_latency_ms", ["update_total_latency_ms", "avg_update_ms", "update_latency_ms"], "ms"),
        ("server_storage_bytes", ["server_bytes", "server_storage_bytes"], "bytes"),
        ("refresh_count", ["refresh_count", "refreshes"], "count"),
        ("scheduled_refresh_count", ["scheduled_refresh_count", "scheduled_refreshes"], "count"),
        ("forced_rollover_count", ["forced_log_refresh_count", "forced_log_refreshes", "public_rollover_count"], "count"),
    ]
    for idx, src in enumerate(rows):
        meta = {
            "seed": src.get("seed", ""),
            "dataset": src.get("case", src.get("dataset", "")),
            "workload": src.get("workload", ""),
            "scheme": src.get("case", src.get("scheme", "")),
            "variant": src.get("variant", ""),
            "N": src.get("N", ""),
            "ops": src.get("ops", ""),
            "query_ratio": src.get("query_ratio", ""),
            "budget": src.get("budget", src.get("theta", "")) if paper_fig == "fig12_budget" else src.get("budget", ""),
            "selectivity": src.get("selectivity", ""),
        }
        if src.get("dataset") and src.get("dataset") != "synthetic":
            meta["dataset"] = src["dataset"]
        searches = parse_float(src, ["searches"])
        total_response = parse_float(src, ["response_bytes"])
        response_bytes = total_response / searches if total_response is not None and searches else total_response
        if response_bytes is not None:
            for name, value, unit, source in [
                ("response_bytes", response_bytes, "bytes", "bench_wide.csv"),
                ("response_mib", response_bytes / (1024.0 * 1024.0), "MiB", "derived"),
            ]:
                row = base_row(paper_fig=paper_fig, benchmark_group=benchmark_group, profile=profile, source_csv=copied_path, source_row_id=f"row{idx}", run_root=run_root, config_file=config_file, config_hash=config_hash, machine=machine, meta=meta)
                row.update(metric_name=name, metric_value=repr(value), metric_unit=unit, metric_source=source, evaluator="benchmark" if source == "bench_wide.csv" else "derived_summary")
                out.append(row)
        for name, aliases, unit in metric_fields:
            value = parse_float(src, aliases)
            if value is None:
                continue
            row = base_row(paper_fig=paper_fig, benchmark_group=benchmark_group, profile=profile, source_csv=copied_path, source_row_id=f"row{idx}", run_root=run_root, config_file=config_file, config_hash=config_hash, machine=machine, meta=meta)
            row.update(metric_name=name, metric_value=repr(value), metric_unit=unit, metric_source="bench_wide.csv", evaluator="benchmark")
            out.append(row)
            if name == "server_storage_bytes":
                mib = base_row(paper_fig=paper_fig, benchmark_group=benchmark_group, profile=profile, source_csv=copied_path, source_row_id=f"row{idx}", run_root=run_root, config_file=config_file, config_hash=config_hash, machine=machine, meta=meta)
                mib.update(metric_name="server_storage_mib", metric_value=repr(value / (1024.0 * 1024.0)), metric_unit="MiB", metric_source="derived", evaluator="derived_summary")
                out.append(mib)
    return out


def normalize_mechanism_file(
    *,
    path: Path,
    copied_path: Path,
    profile: str,
    run_root: Path,
    config_file: Path,
    config_hash: str,
    machine: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, src in enumerate(read_csv(path)):
        panel = src.get("panel", "")
        if panel == "synthetic_cell_load":
            metric_name = "true_cell_load"
        elif panel == "real_cell_load":
            metric_name = "real_cell_load"
        elif panel.startswith("update_touch"):
            metric_name = "update_touches"
        else:
            metric_name = panel or "mechanism_value"
        meta = {
            "seed": src.get("seed", ""),
            "dataset": src.get("dataset", ""),
            "workload": src.get("workload", ""),
            "scheme": src.get("scheme", ""),
        }
        row = base_row(
            paper_fig="fig6_mechanism",
            benchmark_group="fig_mechanism",
            profile=profile,
            source_csv=copied_path,
            source_row_id=f"row{idx}",
            run_root=run_root,
            config_file=config_file,
            config_hash=config_hash,
            machine=machine,
            meta=meta,
        )
        row.update(metric_name=metric_name, metric_value=src.get("value", ""), metric_unit="count", metric_source="mechanism CSV", evaluator="mechanism")
        out.append(row)
    return out


def residual_metric_names(task: str) -> tuple[str, str] | None:
    if task == "residual_density":
        return "density_lcert_auc", "density_lcert_adv_auc"
    if task == "residual_hotspot":
        return "hotspot_lcert_auc", "hotspot_lcert_adv_auc"
    if task == "residual_adjacency":
        return "adjacency_lcert_auc", "adjacency_lcert_adv_auc"
    return None


def normalize_residual_file(
    *,
    path: Path,
    copied_path: Path,
    profile: str,
    run_root: Path,
    config_file: Path,
    config_hash: str,
    machine: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, src in enumerate(read_csv(path)):
        names = residual_metric_names(src.get("task", ""))
        if names is None:
            continue
        meta = {
            "seed": src.get("seed", ""),
            "dataset": src.get("dataset", ""),
            "workload": src.get("workload", ""),
            "scheme": src.get("scheme", ""),
            "variant": src.get("view", ""),
            "N": src.get("N", ""),
            "ops": src.get("ops", ""),
            "view": src.get("view", ""),
            "task": src.get("task", ""),
            "feature_scope": src.get("feature_scope", ""),
            "label_source": src.get("label_source", ""),
            "allowed_features_used": src.get("allowed_features_used", ""),
            "forbidden_features_used": src.get("forbidden_features_used", ""),
            "interpretation": src.get("interpretation", ""),
            "simulator_missing": src.get("simulator_missing", ""),
        }
        note_parts = [
            src.get("notes", ""),
            "residual certified-view leakage; not included in max_cert_probe_auc",
        ]
        notes = "; ".join(part for part in note_parts if part)
        for metric_name, value_name, auc_mode in [
            (names[0], "auc", "raw_auc"),
            (names[1], "adv_auc", "adv_auc"),
        ]:
            value = parse_float(src, [value_name])
            if value is None:
                continue
            row = base_row(
                paper_fig="residual_lcert_probe",
                benchmark_group="fig13_lcert_residual",
                profile=profile,
                source_csv=copied_path,
                source_row_id=f"row{idx}",
                run_root=run_root,
                config_file=config_file,
                config_hash=config_hash,
                machine=machine,
                meta=meta,
            )
            row.update(
                metric_name=metric_name,
                metric_value=repr(value),
                metric_unit="auc",
                metric_source="lcert_residual_eval.py",
                evaluator="lcert_residual",
                auc_mode=auc_mode,
                is_paper_metric="false",
                notes=notes,
            )
            out.append(row)
    return out


def normalize_profile(artifact_root: Path, profile: str, run_root: Path, config_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not run_root.exists():
        return [], []
    copied_config = copy_if_exists(config_path, artifact_root / "configs" / config_path.name) or config_path
    config_hash = sha256(copied_config) if copied_config.exists() else ""
    config = load_yaml(copied_config)
    machine = config.get("machine", {}) if isinstance(config, dict) else {}
    all_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for entry in FIGURE_MAP:
        paper_fig = entry["paper_fig"]
        group_dir = run_root / entry["group_dir"]
        raw_dir = artifact_root / "raw" / profile / paper_fig
        if paper_fig == "fig6_mechanism":
            src = group_dir / "fig_mechanism_cell_load_touch_skew.csv"
            copied = copy_if_exists(src, raw_dir / src.name)
            if copied:
                all_rows.extend(normalize_mechanism_file(path=src, copied_path=copied, profile=profile, run_root=run_root, config_file=copied_config, config_hash=config_hash, machine=machine))
                source_rows.append({"profile": profile, "paper_fig": paper_fig, "source_csv": str(copied).replace("\\", "/"), "sha256": sha256(copied)})
            continue
        if paper_fig in {"fig7_attack_auc", "fig10_workload", "fig11_real_trace", "fig12_budget"}:
            for src in sorted((group_dir / "attacks").glob("*.csv")):
                copied = copy_if_exists(src, raw_dir / "attacks" / src.name)
                if copied:
                    all_rows.extend(normalize_attack_file(path=src, copied_path=copied, paper_fig=paper_fig, benchmark_group=entry["benchmark_group"], profile=profile, run_root=run_root, config_file=copied_config, config_hash=config_hash, machine=machine))
                    source_rows.append({"profile": profile, "paper_fig": paper_fig, "source_csv": str(copied).replace("\\", "/"), "sha256": sha256(copied)})
        if paper_fig in {"fig8_absolute_cost", "fig9_scale_select", "fig11_real_trace", "fig12_budget"}:
            src = group_dir / "bench_wide.csv"
            copied = copy_if_exists(src, raw_dir / src.name)
            if copied:
                all_rows.extend(normalize_bench_file(path=src, copied_path=copied, paper_fig=paper_fig, benchmark_group=entry["benchmark_group"], profile=profile, run_root=run_root, config_file=copied_config, config_hash=config_hash, machine=machine))
                source_rows.append({"profile": profile, "paper_fig": paper_fig, "source_csv": str(copied).replace("\\", "/"), "sha256": sha256(copied)})
    residual_src = run_root / "lcert_residual" / "residual_lcert_raw.csv"
    residual_dst = artifact_root / "raw" / profile / "residual_lcert_probe" / "residual_lcert_raw.csv"
    copied = copy_if_exists(residual_src, residual_dst)
    if copied:
        all_rows.extend(normalize_residual_file(path=residual_src, copied_path=copied, profile=profile, run_root=run_root, config_file=copied_config, config_hash=config_hash, machine=machine))
        source_rows.append({"profile": profile, "paper_fig": "residual_lcert_probe", "source_csv": str(copied).replace("\\", "/"), "sha256": sha256(copied)})
    return all_rows, source_rows


def write_manifests(artifact_root: Path, source_rows: list[dict[str, Any]], profiles: list[tuple[str, Path, Path]]) -> None:
    figure_rows = []
    for row in FIGURE_MAP:
        figure_rows.append(
            {
                "paper_fig": row["paper_fig"],
                "benchmark_group": row["benchmark_group"],
                "group_dir": row["group_dir"],
                "metric_sources": row["sources"],
                "notes": "table1 is dataset profile only; table2_summary is derived from fig2 attack_eval.py and fig2 bench_wide.csv",
            }
        )
    figure_rows.append(
        {
            "paper_fig": "table2_summary",
            "benchmark_group": "derived",
            "group_dir": "fig2_component_ablation",
            "metric_sources": "fig2 attack_eval.py + fig2 bench_wide.csv",
            "notes": "derived summary, not an independent benchmark group",
        }
    )
    figure_rows.append(
        {
            "paper_fig": "residual_lcert_probe",
            "benchmark_group": "fig13_lcert_residual",
            "group_dir": "lcert_residual",
            "metric_sources": "lcert_residual_eval.py post-processing over fig2 traces",
            "notes": "auxiliary residual certified-view leakage analysis; not one of the seven main benchmark groups; excluded from table2 and max_cert_probe_auc",
        }
    )
    write_csv(artifact_root / "manifests" / "figure_source_map.csv", figure_rows, ["paper_fig", "benchmark_group", "group_dir", "metric_sources", "notes"])
    write_csv(artifact_root / "manifests" / "metric_definitions.csv", [
        {
            "metric_name": name,
            "definition": definition,
            "metric_unit": unit,
            "metric_source": source,
            "auc_mode": auc_mode,
            "is_paper_metric": is_paper,
        }
        for name, definition, unit, source, auc_mode, is_paper in METRIC_DEFINITIONS
    ], ["metric_name", "definition", "metric_unit", "metric_source", "auc_mode", "is_paper_metric"])
    write_csv(artifact_root / "manifests" / "source_files.csv", source_rows, ["profile", "paper_fig", "source_csv", "sha256"])
    generated_from = {
        "paper_full": "archived-full-normalized",
        "quick": "quick-rerun",
    }
    run_status = {
        "paper_full": "not-rerun-in-this-cleanup",
        "quick": "completed-or-existing",
    }
    notes = {
        "paper_full": "run_full.sh can rerun full profile",
        "quick": "used for pipeline validation",
    }
    write_csv(artifact_root / "manifests" / "run_manifest.csv", [
        {
            "artifact_version": "artifact-v1",
            "profile": profile,
            "config_file": str(config).replace("\\", "/"),
            "config_hash": sha256(config) if config.exists() else "",
            "generated_from": generated_from.get(profile, "existing-run-root"),
            "run_status": run_status.get(profile, "existing"),
            "notes": notes.get(profile, ""),
            "run_root": str(run_root).replace("\\", "/"),
            "exists": str(run_root.exists()).lower(),
        }
        for profile, run_root, config in profiles
    ], ["artifact_version", "profile", "config_file", "config_hash", "generated_from", "run_status", "notes", "run_root", "exists"])
    sha_rows = []
    for path in sorted(artifact_root.rglob("*")):
        if path.is_file() and path.name != "sha256_manifest.txt":
            sha_rows.append(f"{sha256(path)}  {path.relative_to(artifact_root).as_posix()}")
    (artifact_root / "manifests" / "sha256_manifest.txt").write_text("\n".join(sha_rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=Path("artifact_results_sp"))
    parser.add_argument("--paper-root", type=Path, default=Path("artifact_out/eval_full_sp"))
    parser.add_argument("--quick-root", type=Path, default=Path("artifact_out/eval_quick_sp"))
    parser.add_argument("--paper-config", type=Path, default=Path("artifact_results_sp/configs/eval_full_sp.yaml"))
    parser.add_argument("--quick-config", type=Path, default=Path("artifact_results_sp/configs/eval_quick.yaml"))
    parser.add_argument("--profile", choices=["paper_full", "quick", "all"], default="all", help="Profile to refresh. Other existing profiles in master_long.csv are preserved.")
    args = parser.parse_args()

    args.artifact_root.mkdir(parents=True, exist_ok=True)
    all_profiles = [
        ("paper_full", args.paper_root, args.paper_config),
        ("quick", args.quick_root, args.quick_config),
    ]
    profiles = [p for p in all_profiles if args.profile == "all" or p[0] == args.profile]
    rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    existing_master = read_csv(args.artifact_root / "normalized" / "master_long.csv")
    if args.profile != "all" and existing_master:
        rows.extend([row for row in existing_master if row.get("profile") != args.profile])
    for profile, run_root, config in profiles:
        clear_profile_raw(args.artifact_root, profile)
        profile_rows, profile_sources = normalize_profile(args.artifact_root, profile, run_root, config)
        rows.extend(profile_rows)
        source_rows.extend(profile_sources)
    write_csv(args.artifact_root / "normalized" / "master_long.csv", rows, MASTER_FIELDS)
    write_csv(args.artifact_root / "normalized" / "master_wide_optional.csv", rows, MASTER_FIELDS)
    if args.profile == "all":
        manifest_profiles = all_profiles
        manifest_sources = source_rows
    else:
        manifest_profiles = all_profiles
        existing_sources = read_csv(args.artifact_root / "manifests" / "source_files.csv")
        manifest_sources = [row for row in existing_sources if row.get("profile") != args.profile] + source_rows
    write_manifests(args.artifact_root, manifest_sources, manifest_profiles)
    print(f"normalized {len(rows)} metric rows into {args.artifact_root / 'normalized' / 'master_long.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
