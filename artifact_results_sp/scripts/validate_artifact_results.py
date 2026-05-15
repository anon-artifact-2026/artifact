#!/usr/bin/env python3
"""Validate LOCI open artifact result layout and metric provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path


SUCCESS = "artifact_results_sp validation passed: paper figures map to 7 benchmark groups; table1/table2 are not independent experiments; AUC and cost metric sources are separated; residual Lcert probe separated from certified-probe AUC."

SUMMARY_FILES = [
    "fig6_mechanism_summary.csv",
    "fig7_attack_auc_summary.csv",
    "fig8_absolute_cost_summary.csv",
    "fig9_scale_selectivity_summary.csv",
    "fig10_workload_robustness_summary.csv",
    "fig11_real_trace_summary.csv",
    "fig12_budget_sensitivity_summary.csv",
    "table2_summary.csv",
]

PAPER_AUC_FIGS = {"fig7_attack_auc", "fig10_workload", "fig11_real_trace", "fig12_budget"}
BAD_AUC_NAMES = {"eval_region_auc", "region_auc", "hotspot_auc", "eval_hotspot_auc"}
CERT_ADV_NAMES = {"layout_shape_adv_auc", "patch_pressure_adv_auc", "maintenance_cause_adv_auc"}
RESIDUAL_METRICS = {
    "density_lcert_auc",
    "density_lcert_adv_auc",
    "hotspot_lcert_auc",
    "hotspot_lcert_adv_auc",
    "adjacency_lcert_auc",
    "adjacency_lcert_adv_auc",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_auc_metric(name: str, auc_mode: str) -> bool:
    return name.endswith("_auc") or auc_mode in {"raw_auc", "adv_auc"}


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def validate_figure_map(root: Path, errors: list[str]) -> None:
    rows = read_csv(root / "manifests" / "figure_source_map.csv")
    mapping = {row.get("paper_fig"): row.get("benchmark_group") for row in rows}
    expected = {
        "fig6_mechanism": "fig_mechanism",
        "fig7_attack_auc": "fig2_component_ablation",
        "fig8_absolute_cost": "fig2_component_ablation",
        "fig9_scale_select": "fig3_scalability_selectivity",
        "fig10_workload": "fig4_dynamic_refresh",
        "fig11_real_trace": "fig5_real_datasets",
        "fig12_budget": "fig6_tradeoff",
        "table2_summary": "derived",
    }
    for fig, group in expected.items():
        if mapping.get(fig) != group:
            errors.append(f"figure_source_map.csv must map {fig} -> {group}; found {mapping.get(fig)!r}")
    if "residual_lcert_probe" in mapping and mapping.get("residual_lcert_probe") != "fig13_lcert_residual":
        errors.append(f"figure_source_map.csv must map residual_lcert_probe -> fig13_lcert_residual; found {mapping.get('residual_lcert_probe')!r}")
    if "table1" in mapping:
        errors.append("table1 must not appear as an independent paper figure in figure_source_map.csv")


def validate_master(master: list[dict[str, str]], errors: list[str]) -> None:
    if not master:
        errors.append("normalized/master_long.csv has no rows")
        return

    for idx, row in enumerate(master, 2):
        metric = row.get("metric_name", "")
        if row.get("is_paper_metric") == "true" and metric in BAD_AUC_NAMES:
            errors.append(f"master_long.csv line {idx}: paper metric uses forbidden AUC name {metric}")
        if metric in {"diagnostic_region_auc", "diagnostic_hotspot_auc"} and row.get("is_paper_metric") != "false":
            errors.append(f"master_long.csv line {idx}: {metric} must be is_paper_metric=false")
        if row.get("is_paper_metric") == "true" and row.get("metric_source") == "bench_wide.csv" and is_auc_metric(metric, row.get("auc_mode", "")):
            errors.append(f"master_long.csv line {idx}: AUC paper metric {metric} cannot come from bench_wide.csv")
        if metric in RESIDUAL_METRICS:
            if row.get("paper_fig") != "residual_lcert_probe":
                errors.append(f"master_long.csv line {idx}: residual Lcert metric appears outside residual_lcert_probe")
            if row.get("metric_source") != "lcert_residual_eval.py":
                errors.append(f"master_long.csv line {idx}: residual Lcert metric must have metric_source=lcert_residual_eval.py")
            if row.get("evaluator") != "lcert_residual":
                errors.append(f"master_long.csv line {idx}: residual Lcert metric must have evaluator=lcert_residual")
            if row.get("is_paper_metric") != "false":
                errors.append(f"master_long.csv line {idx}: residual Lcert metric must be is_paper_metric=false")
            if row.get("feature_scope") == "strict_lcert_only" and row.get("forbidden_features_used", ""):
                errors.append(f"master_long.csv line {idx}: strict_lcert_only residual row has forbidden_features_used={row.get('forbidden_features_used')!r}")
            text = " ".join([row.get("notes", ""), row.get("interpretation", "")])
            if not any(phrase in text for phrase in ["residual certified-view leakage", "declared certified leakage", "simulator baseline"]):
                errors.append(f"master_long.csv line {idx}: residual Lcert row needs residual/simulator interpretation")

    for fig in PAPER_AUC_FIGS:
        attack_rows = [
            row
            for row in master
            if row.get("profile") == "paper_full"
            and row.get("paper_fig") == fig
            and row.get("metric_source") == "attack_eval.py"
            and row.get("metric_name") in {"layout_shape_auc", "patch_pressure_auc", "maintenance_cause_auc"}
        ]
        if not attack_rows:
            errors.append(f"{fig} paper_full has no attack_eval.py certified-probe AUC rows")

    contexts: dict[tuple[str, ...], dict[str, float]] = defaultdict(dict)
    context_fields = [
        "profile",
        "paper_fig",
        "dataset",
        "workload",
        "scheme",
        "variant",
        "N",
        "ops",
        "budget",
        "selectivity",
        "seed",
        "source_csv",
    ]
    for row in master:
        if row.get("metric_name") in CERT_ADV_NAMES or row.get("metric_name") == "max_cert_probe_auc":
            value = parse_float(row.get("metric_value", ""))
            if value is None:
                continue
            contexts[tuple(row.get(k, "") for k in context_fields)][row.get("metric_name", "")] = value
            if row.get("metric_name") == "max_cert_probe_auc":
                if row.get("metric_source") != "derived":
                    errors.append(f"max_cert_probe_auc must have metric_source=derived: {row.get('source_csv')} {row.get('source_row_id')}")
                expected_note = "derived_from=layout_shape_adv_auc,patch_pressure_adv_auc,maintenance_cause_adv_auc"
                if expected_note not in row.get("notes", ""):
                    errors.append(f"max_cert_probe_auc notes must state certified-probe derivation: {row.get('source_csv')} {row.get('source_row_id')}")
    for ctx, metrics in contexts.items():
        if "max_cert_probe_auc" not in metrics:
            continue
        if not CERT_ADV_NAMES.issubset(metrics):
            errors.append(f"max_cert_probe_auc context is missing one of the three certified adv AUCs: {ctx}")
            continue
        expected = max(metrics[name] for name in CERT_ADV_NAMES)
        if abs(metrics["max_cert_probe_auc"] - expected) > 1e-12:
            errors.append(f"max_cert_probe_auc is not max of the three certified probes for context {ctx}")


def validate_summaries(root: Path, errors: list[str]) -> None:
    summary_dir = root / "summaries"
    for name in SUMMARY_FILES:
        path = summary_dir / name
        if not path.exists():
            errors.append(f"missing summary file: {path}")
            continue
        rows = read_csv(path)
        if not rows:
            errors.append(f"summary file has no rows: {path}")
        for idx, row in enumerate(rows, 2):
            if not row.get("source_csv"):
                errors.append(f"{name} line {idx}: source_csv is empty")
            if not row.get("source_row_id"):
                errors.append(f"{name} line {idx}: source_row_id is empty")
            if row.get("is_paper_metric") == "true" and row.get("metric_name") in BAD_AUC_NAMES:
                errors.append(f"{name} line {idx}: forbidden paper AUC metric {row.get('metric_name')}")
            if row.get("profile") == "paper_full" and row.get("paper_fig") != "table2_summary":
                seeds = {s for s in row.get("seeds", "").split(",") if s}
                if seeds and seeds != {"0", "1", "2"}:
                    errors.append(f"{name} line {idx}: paper_full row must aggregate seeds 0,1,2; found {row.get('seeds')!r}")

    fig8_rows = read_csv(summary_dir / "fig8_absolute_cost_summary.csv")
    for idx, row in enumerate(fig8_rows, 2):
        if is_auc_metric(row.get("metric_name", ""), row.get("auc_mode", "")):
            errors.append(f"fig8_absolute_cost_summary.csv line {idx}: Fig.8 summary must not contain AUC metrics")
        sources = [s for s in row.get("source_csv", "").split(";") if s]
        for source in sources:
            if not source.endswith("fig8_absolute_cost/bench_wide.csv"):
                errors.append(f"fig8_absolute_cost_summary.csv line {idx}: source must be fig2_component_ablation bench_wide copied under fig8_absolute_cost; found {source}")

    table2 = read_csv(summary_dir / "table2_summary.csv")
    for idx, row in enumerate(table2, 2):
        if row.get("benchmark_group") != "derived":
            errors.append(f"table2_summary.csv line {idx}: benchmark_group must be derived")
        if "not_independent_benchmark=true" not in row.get("notes", ""):
            errors.append(f"table2_summary.csv line {idx}: notes must mark table2 as not an independent benchmark")
        if row.get("metric_name") in RESIDUAL_METRICS or row.get("paper_fig") == "residual_lcert_probe":
            errors.append(f"table2_summary.csv line {idx}: residual Lcert metrics must not appear in table2")

    for name in ["fig7_attack_auc_summary.csv", "fig10_workload_robustness_summary.csv", "fig11_real_trace_summary.csv", "fig12_budget_sensitivity_summary.csv"]:
        for idx, row in enumerate(read_csv(summary_dir / name), 2):
            if row.get("is_paper_metric") == "true" and row.get("metric_name") in BAD_AUC_NAMES:
                errors.append(f"{name} line {idx}: forbidden paper AUC metric {row.get('metric_name')}")
            if row.get("is_paper_metric") == "true" and is_auc_metric(row.get("metric_name", ""), row.get("auc_mode", "")):
                if row.get("metric_source") not in {"attack_eval.py", "derived"}:
                    errors.append(f"{name} line {idx}: paper AUC metric must come from attack_eval.py or derived, found {row.get('metric_source')}")
            if row.get("metric_name") in RESIDUAL_METRICS or row.get("paper_fig") == "residual_lcert_probe":
                errors.append(f"{name} line {idx}: residual Lcert metrics must not appear in certified-probe AUC summaries")

    residual_summary = summary_dir / "residual_lcert_probe_summary.csv"
    if residual_summary.exists():
        for idx, row in enumerate(read_csv(residual_summary), 2):
            if row.get("feature_scope") == "strict_lcert_only":
                text = " ".join([row.get("notes", ""), row.get("interpretation", "")])
                if not any(phrase in text for phrase in ["residual certified-view leakage", "declared_certified_leakage", "simulator_baseline", "simulator baseline"]):
                    errors.append(f"residual_lcert_probe_summary.csv line {idx}: missing residual certified-view interpretation")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_data_checksums(repo_root: Path, errors: list[str]) -> None:
    data_root = repo_root / "data" / "processed"
    manifest = repo_root / "data" / "sha256_manifest.txt"
    if not data_root.exists():
        errors.append("data/processed does not exist")
        return
    csv_files = sorted(data_root.rglob("*.csv"))
    if not csv_files:
        errors.append("data/processed contains no CSV files")
    if not manifest.exists():
        errors.append("data/sha256_manifest.txt is missing")
        return
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            errors.append(f"malformed data checksum line: {line}")
            continue
        entries[parts[1].replace("\\", "/")] = parts[0]
    if not entries:
        errors.append("data/sha256_manifest.txt has no checksum entries")
    for path in csv_files:
        rel = path.relative_to(repo_root).as_posix()
        expected = entries.get(rel)
        if expected is None:
            errors.append(f"data checksum missing for {rel}")
            continue
        actual = sha256(path)
        if actual != expected:
            errors.append(f"data checksum mismatch for {rel}")


def validate_no_noncanonical_outputs(repo_root: Path, errors: list[str]) -> None:
    results_dir = repo_root / "results"
    if results_dir.exists():
        errors.append("repo root results/ must not exist; Fig.6 mechanism outputs must stay under the run group directory")
    artifact_out = repo_root / "artifact_out"
    if not artifact_out.exists():
        return
    for path in artifact_out.rglob("table2_summary.csv"):
        if path.parent.name == "table2_summary":
            errors.append(f"legacy non-canonical table2 output must not exist: {path}")


def validate_raw_source_manifest(root: Path, repo_root: Path, errors: list[str]) -> None:
    manifest = root / "manifests" / "source_files.csv"
    if not manifest.exists():
        errors.append("manifests/source_files.csv is missing")
        return
    repo_resolved = repo_root.resolve()
    actual: set[str] = set()
    raw_root = root / "raw"
    if raw_root.exists():
        for path in raw_root.rglob("*.csv"):
            try:
                actual.add(path.resolve().relative_to(repo_resolved).as_posix())
            except ValueError:
                actual.add(str(path).replace("\\", "/"))
    declared = {
        row.get("source_csv", "").replace("\\", "/").removeprefix("./")
        for row in read_csv(manifest)
        if row.get("source_csv")
    }
    missing = declared - actual
    stale = actual - declared
    for path in sorted(missing):
        errors.append(f"source_files.csv lists missing raw CSV: {path}")
    for path in sorted(stale):
        errors.append(f"raw CSV is missing from source_files.csv: {path}")


def validate_residual_raw(root: Path, errors: list[str]) -> None:
    for path in sorted((root / "raw").glob("*/residual_lcert_probe/residual_lcert_raw.csv")):
        for idx, row in enumerate(read_csv(path), 2):
            if row.get("feature_scope") == "strict_lcert_only" and row.get("forbidden_features_used", ""):
                errors.append(f"{path} line {idx}: strict_lcert_only row has forbidden_features_used={row.get('forbidden_features_used')!r}")
            text = " ".join([row.get("notes", ""), row.get("interpretation", "")])
            if not any(phrase in text for phrase in ["residual certified-view leakage", "declared_certified_leakage", "simulator_baseline", "simulator baseline"]):
                errors.append(f"{path} line {idx}: missing residual certified-view interpretation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=Path("artifact_results_sp"))
    parser.add_argument("--profile", choices=["paper_full", "quick", "all"], default="all", help="Accepted for command compatibility; validation checks available artifact rows.")
    args = parser.parse_args()

    errors: list[str] = []
    repo_root = args.artifact_root.parent
    validate_no_noncanonical_outputs(repo_root, errors)
    validate_figure_map(args.artifact_root, errors)
    validate_master(read_csv(args.artifact_root / "normalized" / "master_long.csv"), errors)
    validate_summaries(args.artifact_root, errors)
    validate_raw_source_manifest(args.artifact_root, repo_root, errors)
    validate_residual_raw(args.artifact_root, errors)
    validate_data_checksums(repo_root, errors)

    if errors:
        print("artifact_results_sp validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(SUCCESS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
