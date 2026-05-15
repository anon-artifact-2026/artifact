#!/usr/bin/env python3
"""Aggregate LOCI evaluation outputs under artifact_out/eval."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import math
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def scheme_alias(name: str) -> str:
    if name in {"GlobalPad", "PGM-Learned-GlobalPad"}:
        return "ResponseGlobalPad"
    return name


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fields = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
    else:
        fields = ["group", "dataset", "attribute", "N", "workload", "scheme", "metric_name", "selectivity", "axis", "budget", "theta", "B", "mean", "std", "n"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[float]] = defaultdict(list)
    meta: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("group", ""),
            row.get("dataset", ""),
            row.get("attribute", ""),
            row.get("N", ""),
            row.get("workload", ""),
            scheme_alias(row.get("scheme", "")),
            row.get("metric_name", ""),
            row.get("selectivity", ""),
            row.get("axis", ""),
            row.get("budget", ""),
            row.get("theta", ""),
            row.get("B", ""),
        )
        try:
            grouped[key].append(float(row.get("metric_value", "")))
        except ValueError:
            continue
        meta[key] = {
            "group": key[0],
            "dataset": key[1],
            "attribute": key[2],
            "N": key[3],
            "workload": key[4],
            "scheme": key[5],
            "metric_name": key[6],
            "selectivity": key[7],
            "axis": key[8],
            "budget": key[9],
            "theta": key[10],
            "B": key[11],
            "data_limit": row.get("data_limit", ""),
            "status": row.get("status", ""),
            "reason": row.get("reason", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
        }
    out = []
    for key, values in sorted(grouped.items()):
        finite = [x for x in values if not math.isnan(x)]
        mean = sum(finite) / len(finite) if finite else float("nan")
        var = sum((x - mean) ** 2 for x in finite) / len(finite) if finite else float("nan")
        row = dict(meta[key])
        row.update({"mean": mean, "std": var ** 0.5, "n": len(values)})
        out.append(row)
    return out


def timeout_rows(root: Path, existing_raw: list[dict[str, str]]) -> list[dict[str, str]]:
    existing = {
        (
            r.get("group", ""),
            r.get("dataset", ""),
            r.get("attribute", ""),
            r.get("N", ""),
            r.get("workload", ""),
            scheme_alias(r.get("scheme", "")),
            r.get("seed", ""),
            r.get("metric_name", ""),
            r.get("selectivity", ""),
            r.get("axis", ""),
            r.get("budget", ""),
            r.get("theta", ""),
            r.get("B", ""),
        )
        for r in existing_raw
    }
    rows: list[dict[str, str]] = []
    for path in root.glob("*/timeouts.csv"):
        for r in read_rows(path):
            key = (
                r.get("group", ""),
                r.get("dataset", ""),
                r.get("attribute", ""),
                r.get("N", ""),
                r.get("workload", ""),
                scheme_alias(r.get("scheme", "")),
                r.get("seed", ""),
                "timeout",
                r.get("selectivity", ""),
                r.get("axis", "scale"),
                r.get("budget", ""),
                r.get("theta", ""),
                r.get("B", ""),
            )
            if key in existing:
                continue
            rows.append(
                {
                    "group": r.get("group", ""),
                    "dataset": r.get("dataset", ""),
                    "attribute": r.get("attribute", ""),
                    "N": r.get("N", ""),
                    "workload": r.get("workload", ""),
                    "scheme": scheme_alias(r.get("scheme", "")),
                    "seed": r.get("seed", ""),
                    "metric_name": "timeout",
                    "metric_value": "1",
                    "selectivity": r.get("selectivity", ""),
                    "axis": r.get("axis", "scale"),
                    "budget": r.get("budget", ""),
                    "theta": r.get("theta", ""),
                    "B": r.get("B", ""),
                    "data_limit": r.get("data_limit", ""),
                    "status": "skipped" if r.get("reason", "").startswith("omitted") else "timeout",
                    "reason": r.get("reason", ""),
                    "elapsed_seconds": r.get("elapsed_seconds", ""),
                }
            )
    return rows


def status_rows(root: Path, existing_raw: list[dict[str, str]]) -> list[dict[str, str]]:
    existing = {
        (
            r.get("group", ""),
            r.get("dataset", ""),
            r.get("attribute", ""),
            r.get("N", ""),
            r.get("workload", ""),
            scheme_alias(r.get("scheme", "")),
            r.get("seed", ""),
            r.get("metric_name", ""),
            r.get("selectivity", ""),
            r.get("axis", ""),
            r.get("budget", ""),
            r.get("theta", ""),
            r.get("B", ""),
        )
        for r in existing_raw
    }
    rows: list[dict[str, str]] = []
    for path in root.glob("*/skipped_cases.csv"):
        for r in read_rows(path):
            status = r.get("status", "skipped") or "skipped"
            metric = "timeout" if status == "timeout" else status
            key = (
                r.get("group", ""),
                r.get("dataset", ""),
                r.get("attribute", ""),
                r.get("N", ""),
                r.get("workload", ""),
                scheme_alias(r.get("scheme", "")),
                r.get("seed", ""),
                metric,
                r.get("selectivity", ""),
                r.get("axis", ""),
                r.get("budget", ""),
                r.get("theta", ""),
                r.get("B", ""),
            )
            if key in existing:
                continue
            rows.append(
                {
                    "group": r.get("group", ""),
                    "dataset": r.get("dataset", ""),
                    "attribute": r.get("attribute", ""),
                    "N": r.get("N", ""),
                    "workload": r.get("workload", ""),
                    "scheme": scheme_alias(r.get("scheme", "")),
                    "seed": r.get("seed", ""),
                    "metric_name": metric,
                    "metric_value": "1",
                    "selectivity": r.get("selectivity", ""),
                    "axis": r.get("axis", ""),
                    "budget": r.get("budget", ""),
                    "theta": r.get("theta", ""),
                    "B": r.get("B", ""),
                    "data_limit": r.get("data_limit", ""),
                    "status": status,
                    "reason": r.get("reason", ""),
                    "elapsed_seconds": r.get("elapsed_seconds", ""),
                }
            )
    return rows


def pivot_for_table2(summary: list[dict[str, Any]], schemes: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = [
        "layout_shape_auc",
        "shape_auc",
        "patch_pressure_auc",
        "maintenance_cause_auc",
        "layout_shape_adv_auc",
        "patch_pressure_adv_auc",
        "maintenance_cause_adv_auc",
        "max_cert_probe_auc",
        "search_latency_ms",
        "update_latency_ms",
        "patch_update_latency_ms",
        "maintenance_latency_ms",
        "update_total_latency_ms",
        "refresh_count",
        "scheduled_refresh_count",
        "forced_log_refresh_count",
        "public_rollover_count",
        "split_count",
        "merge_count",
        "guide_retrain_count",
        "locator_rebuild_count",
        "response_bytes",
        "server_storage_bytes",
        "refresh_bytes",
    ]
    heatmap_labels = {
        "PGM-Learned-Naive": "Naive",
        "LOCI-NoCert": "NoCert",
        "LOCI-NoPad": "NoPad",
        "LOCI-NoPublicRefresh": "NoPubRef",
        "LOCI-NoProto": "NoProto",
        "LOCI-Full": "LOCI",
        "ResponseGlobalPad": "GlobalPad",
        "FixedCell-Bitmap": "FixedCell",
        "TreeCover": "TreeCover",
        "Sim-L_cert": "Sim-L_cert",
    }
    if schemes is None:
        schemes = [
            "PGM-Learned-Naive",
            "LOCI-NoCert",
            "LOCI-NoPad",
            "LOCI-NoPublicRefresh",
            "LOCI-NoProto",
            "LOCI-Full",
            "ResponseGlobalPad",
            "Sim-L_cert",
        ]
    schemes = [scheme_alias(s) for s in schemes]
    scheme_set = set(schemes)
    candidates: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in summary:
        if row.get("group") != "fig2":
            continue
        metric = row["metric_name"]
        if metric == "shape_auc":
            metric = "layout_shape_auc"
        scheme = scheme_alias(row["scheme"])
        if metric not in wanted or scheme not in scheme_set:
            continue
        candidates.setdefault((scheme, metric), []).append((int(float(row.get("N") or 0)), float(row["mean"])))
    best: dict[tuple[str, str], float] = {}
    for key, vals in candidates.items():
        vals.sort(key=lambda x: x[0], reverse=True)
        best[key] = vals[0][1]
    out = []
    for scheme in schemes:
        row = {"scheme": scheme, "heatmap_label": heatmap_labels.get(scheme, scheme)}
        for metric in wanted:
            if metric == "shape_auc":
                continue
            value = best.get((scheme, metric), "")
            if metric == "response_bytes" and value != "":
                row["response_kb"] = float(value) / 1024.0
            elif metric == "server_storage_bytes" and value != "":
                row["server_storage_mb"] = float(value) / (1024.0 * 1024.0)
            elif metric == "refresh_bytes" and value != "":
                row["refresh_bytes_kb"] = float(value) / 1024.0
            elif metric not in {"response_bytes", "server_storage_bytes", "refresh_bytes"}:
                row[metric] = value
        out.append(row)
    return out


def pivot_for_table2_extra(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return pivot_for_table2(
        summary,
        [
            "FixedCell-Bitmap",
            "TreeCover",
            "Sim-L_cert",
        ],
    )


def aggregate_exactness(root: Path) -> None:
    rows: list[dict[str, str]] = []
    for path in root.glob("*/exactness_summary.csv"):
        rows.extend(read_rows(path))
    out_dir = root / "appendix" / "exactness"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_rows(out_dir / "exactness_summary.csv", rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0].keys()) if rows else []
    lines = ["|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"] if fields else []
    for row in rows:
        lines.append("|" + "|".join(str(row.get(f, "")) for f in fields) + "|")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_latex(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    lines = ["\\begin{tabular}{" + "l" * len(fields) + "}", "\\toprule", " & ".join(fields) + " \\\\", "\\midrule"]
    for row in rows:
        lines.append(" & ".join(str(row.get(f, "")).replace("_", "\\_") for f in fields) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifact_out/eval"))
    parser.add_argument("--out", type=Path, help="alias for --root")
    parser.add_argument(
        "--write-legacy-table2-diagnostic",
        action="store_true",
        help="Write a non-canonical legacy Table 2 diagnostic under diagnostics/. Paper Table 2 is generated only by artifact_results_sp/scripts/make_paper_summaries.py.",
    )
    parser.add_argument(
        "--skip-legacy-table2",
        action="store_true",
        help="Skip legacy Table 2 output. This is the default and is used by artifact rerun scripts.",
    )
    args = parser.parse_args()
    if args.write_legacy_table2_diagnostic and args.skip_legacy_table2:
        parser.error("--write-legacy-table2-diagnostic and --skip-legacy-table2 are mutually exclusive")
    if args.out is not None:
        args.root = args.out

    raw = []
    for path in args.root.glob("*/raw_metrics.csv"):
        raw.extend(read_rows(path))
    raw.extend(timeout_rows(args.root, raw))
    raw.extend(status_rows(args.root, raw))
    summary = summarize(raw)
    write_rows(args.root / "all_raw_metrics.csv", raw)
    write_rows(args.root / "all_summary.csv", summary)

    if args.write_legacy_table2_diagnostic:
        diagnostics_dir = args.root / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        table2 = pivot_for_table2(summary)
        table2_extra = pivot_for_table2_extra(summary)
        for row in table2:
            row["notes"] = "legacy diagnostic only; not used by paper"
        for row in table2_extra:
            row["notes"] = "legacy diagnostic only; not used by paper"
        write_rows(diagnostics_dir / "legacy_noncanonical_table2_diagnostic.csv", table2)
        write_rows(diagnostics_dir / "legacy_noncanonical_table2_extra_baselines.csv", table2_extra)
    aggregate_exactness(args.root)
    print(f"aggregated {len(raw)} raw metric rows into {args.root / 'all_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
