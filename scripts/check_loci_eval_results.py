#!/usr/bin/env python3
"""Validate LOCI evaluation trends and sanity checks.

The script reports warnings only. It never rewrites results.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def f(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def scheme_alias(name: str) -> str:
    if name in {"GlobalPad", "PGM-Learned-GlobalPad"}:
        return "ResponseGlobalPad"
    return name


def metric_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    attack_metrics = {
        "layout_shape_auc",
        "layout_shape_adv_auc",
        "patch_pressure_auc",
        "patch_pressure_adv_auc",
        "maintenance_cause_auc",
        "maintenance_cause_adv_auc",
        "max_cert_probe_auc",
    }
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.get("group") == "fig3" and row.get("metric_name", "") in attack_metrics:
            continue
        grouped[(scheme_alias(row.get("scheme", "")), row.get("metric_name", ""))].append(f(row.get("mean", row.get("metric_value", ""))))
    return {k: sum(v) / len(v) for k, v in grouped.items() if v}


def warn(lines: list[str], title: str, causes: list[str]) -> None:
    lines.append(f"WARNING: {title}")
    lines.append("Possible causes:")
    for cause in causes:
        lines.append(f"  - {cause}")
    lines.append("")


def info(lines: list[str], title: str) -> None:
    lines.append(f"INFO: {title}")
    lines.append("")


def case_label(row: dict[str, str]) -> str:
    bits = [
        row.get("group", ""),
        scheme_alias(row.get("scheme", "")),
        row.get("dataset", ""),
        f"N={row.get('N', '')}",
        f"seed={row.get('seed', '')}",
    ]
    axis = row.get("axis", "")
    if axis:
        bits.append(f"axis={axis}")
    return " / ".join(x for x in bits if x)


def close(a: float, b: float, eps: float = 0.08) -> bool:
    return abs(a - b) <= eps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifact_out/eval"))
    parser.add_argument("--out", type=Path, help="alias for --root")
    args = parser.parse_args()
    if args.out is not None:
        args.root = args.out

    rows = read_rows(args.root / "all_summary.csv")
    if not rows:
        for path in args.root.glob("*/summary.csv"):
            rows.extend(read_rows(path))
    idx = metric_index(rows)
    lines: list[str] = []

    naive = idx.get(("PGM-Learned-Naive", "max_cert_probe_auc"))
    full = idx.get(("LOCI-Full", "max_cert_probe_auc"))
    sim = idx.get(("Sim-L_cert", "max_cert_probe_auc"))
    if naive is not None and full is not None and naive <= full:
        warn(lines, "Naive max_cert_probe_auc is not higher than LOCI-Full max_cert_probe_auc.", [
            "workload does not expose learned-layout variation",
            "TraceProbe feature extraction is too weak",
            "LOCI-Full still exposes residual information comparable to Naive",
        ])
    if full is not None and sim is not None and not close(full, sim):
        warn(lines, "LOCI-Full max_cert_probe_auc is not close to Sim-L_cert max_cert_probe_auc.", [
            "LOCI transcript exposes more than certified public classes",
            "Sim-L_cert model is too conservative",
            "attack_eval uses a feature not represented in Sim-L_cert",
        ])

    checks = [
        ("LOCI-NoCert", "layout_shape_adv_auc", "NoCert did not increase layout_shape_adv_auc.", [
            "certification is not actually disabled",
            "layout-shape attack feature is underpowered",
            "workload lacks enough learned-cell density variation",
        ]),
        ("LOCI-NoPad", "patch_pressure_adv_auc", "NoPad did not increase patch_pressure_adv_auc.", [
            "patch padding is still enabled in NoPad",
            "TraceProbe feature extraction misses patch growth",
            "workload does not create enough patch pressure",
            "patch classes are too coarse even in NoPad",
        ]),
        ("LOCI-NoPublicRefresh", "maintenance_cause_adv_auc", "NoPublicRefresh did not increase maintenance_cause_adv_auc.", [
            "private refresh trigger is not visible",
            "workload does not create enough log/capacity pressure",
            "maintenance feature extraction is underpowered",
        ]),
    ]
    for scheme, metric, title, causes in checks:
        value = idx.get((scheme, metric))
        base = idx.get(("LOCI-Full", metric))
        if value is not None and base is not None and value <= base:
            warn(lines, title, causes)

    gp_auc = idx.get(("ResponseGlobalPad", "max_cert_probe_auc"))
    gp_resp = idx.get(("ResponseGlobalPad", "response_bytes"))
    full_resp = idx.get(("LOCI-Full", "response_bytes"))
    if gp_auc is not None and full is not None and gp_auc > full + 0.08:
        warn(lines, "ResponseGlobalPad max_cert_probe_auc is higher than LOCI-Full.", [
            "response padding baseline is not padding all expected transcript fields",
            "ResponseGlobalPad scheme mapping is wrong",
        ])
    if gp_resp is not None and full_resp is not None:
        if gp_resp <= full_resp:
            warn(lines, "ResponseGlobalPad is not more expensive than LOCI-Full in response bytes.", [
                "ResponseGlobalPad scheme mapping may not be using response padding",
                "workload does not exercise fanout/object-size variation",
                "LOCI padding classes may be too conservative",
            ])

    noproto_auc = idx.get(("LOCI-NoProto", "max_cert_probe_auc"))
    noproto_store = idx.get(("LOCI-NoProto", "server_storage_bytes"))
    full_store = idx.get(("LOCI-Full", "server_storage_bytes"))
    if noproto_auc is not None and full is not None and not close(noproto_auc, full):
        warn(lines, "NoProto AUC is not close to LOCI-Full.", [
            "prototype-residual encoding may be affecting a security boundary",
            "NoProto implementation changed object/fanout leakage shape",
            "TraceProbe is sensitive to compression-side effects",
        ])
    if noproto_store is not None and full_store is not None and noproto_store <= full_store:
        warn(lines, "NoProto does not show worse storage cost than LOCI-Full.", [
            "NoProto direct bitmap representation may not be enabled",
            "storage metric does not include the relevant sealed objects",
            "dataset/query shape has too few boundary descriptors",
        ])

    exact = read_rows(args.root / "appendix/exactness/exactness_summary.csv")
    for row in exact:
        if "metric_name" in row:
            # Backward compatibility with older long-format smoke outputs.
            if row.get("metric_name") == "precision" and f(row.get("metric_value", "1")) != 1.0:
                warn(lines, "Exactness precision is not perfect.", ["benchmark correctness check failed or exactness aggregation is wrong"])
            if row.get("metric_name") == "recall" and f(row.get("metric_value", "1")) != 1.0:
                warn(lines, "Exactness recall is not perfect.", ["benchmark correctness check failed or exactness aggregation is wrong"])
            continue
        if f(row.get("precision", "1")) != 1.0:
            warn(lines, "Exactness precision is not perfect.", ["benchmark correctness check failed or exactness aggregation is wrong"])
        if f(row.get("recall", "1")) != 1.0:
            warn(lines, "Exactness recall is not perfect.", ["benchmark correctness check failed or exactness aggregation is wrong"])
        if f(row.get("false_positive_count", "0")) != 0.0:
            warn(lines, "Exactness has false positives.", ["range decode returned ids outside the plaintext answer"])
        if f(row.get("false_negative_count", "0")) != 0.0:
            warn(lines, "Exactness has false negatives.", ["range decode missed plaintext answer ids"])
        if f(row.get("exact_match_rate", "1")) != 1.0:
            warn(lines, "Exactness exact_match_rate is not perfect.", ["at least one checked query differed from plaintext"])

    large_scale_rows = [r for r in rows if r.get("group") in {"fig1", "fig2", "fig4"}]
    completed_1m = any(r.get("scheme") == "LOCI-Full" and r.get("N") == "1000000" for r in large_scale_rows)
    if large_scale_rows and not completed_1m:
        warn(lines, "N=1M LOCI-Full run is missing.", [
            "full-scale experiments have not been executed",
            "dataset has fewer than 1M usable rows",
            "runner was invoked with --N override for smoke testing",
        ])

    fig3_rows = [r for r in rows if r.get("group") == "fig3"]
    def fig3_completed(scheme: str, n: str = "200000") -> bool:
        return any(
            scheme_alias(r.get("scheme", "")) == scheme
            and r.get("N") == n
            and r.get("metric_name") == "search_latency_ms"
            for r in fig3_rows
        )

    for scheme in ["LOCI-Full", "PGM-Learned-Naive", "ResponseGlobalPad", "FixedCell-Bitmap"]:
        if fig3_rows and not fig3_completed(scheme):
            warn(lines, f"fig3 {scheme} N=200K run is missing.", [
                "compressed fig3 scale sweep did not complete",
                "runner was invoked with --N override for smoke testing",
                "case timed out unexpectedly",
            ])

    fig3_events = []
    for path in args.root.glob("*/timeouts.csv"):
        for row in read_rows(path):
            if row.get("group") == "fig3":
                fig3_events.append(row)
    treecover_events = [r for r in fig3_events if scheme_alias(r.get("scheme", "")) == "TreeCover"]
    if treecover_events:
        omitted = [r for r in treecover_events if r.get("reason") == "omitted_treecover_large_scale"]
        timed = [r for r in treecover_events if r.get("reason") == "timeout"]
        if omitted:
            max_omitted = sorted({r.get("N", "") for r in omitted})
            info(lines, f"TreeCover omitted for fig3 at configured large-scale points: {', '.join(max_omitted)}.")
        if timed:
            warn(lines, "TreeCover timed out within configured fig3 cap.", [
                "TreeCover is still too slow at or below the 25K cap",
                "reduce configs/eval_main.yaml fig3.treecover.n_values",
                "increase fig3.treecover_timeout_seconds if this point is required",
            ])
    if any(r.get("reason") == "fig3_group_timeout" for r in fig3_events):
        warn(lines, "fig3 stopped at the configured group wall-clock cap.", [
            "the 2-hour fig3 budget was exhausted before all cases completed",
            "reduce configs/eval_main.yaml fig3 scale/selectivity ops",
            "reduce fig3 scale n_values if a full curve is required within the cap",
        ])

    status_events = []
    for path in args.root.glob("*/skipped_cases.csv"):
        status_events.extend(read_rows(path))
    timeouts = [r for r in status_events if r.get("status") == "timeout"]
    failed = [r for r in status_events if r.get("status") == "failed"]
    skipped = [r for r in status_events if r.get("status") == "skipped"]
    if timeouts:
        warn(lines, "Timeout cases were recorded.", [case_label(r) for r in timeouts[:12]])
    if failed:
        warn(lines, "Failed cases were recorded.", [case_label(r) for r in failed[:12]])
    if skipped:
        info(lines, "Skipped cases were recorded: " + "; ".join(case_label(r) for r in skipped[:12]))

    fig5_rows = [r for r in rows if r.get("group") == "fig5"]
    if fig5_rows:
        datasets = sorted({r.get("dataset", "") for r in fig5_rows if r.get("metric_name") == "search_latency_ms"})
        for scheme in ["LOCI-Full", "PGM-Learned-Naive", "ResponseGlobalPad", "FixedCell-Bitmap"]:
            for ds in datasets:
                if not any(scheme_alias(r.get("scheme", "")) == scheme and r.get("dataset") == ds and r.get("metric_name") == "search_latency_ms" for r in fig5_rows):
                    warn(lines, f"fig5 {scheme} missing on {ds}.", [
                        "real-dataset robustness core case timed out or failed",
                        "inspect fig5_real_datasets/skipped_cases.csv",
                    ])

    fig6_rows = [r for r in rows if r.get("group") == "fig6"]
    if fig6_rows:
        for scheme in ["LOCI-Full", "LOCI-NoProto", "LOCI-NoPad", "LOCI-NoCert", "ResponseGlobalPad"]:
            if not any(scheme_alias(r.get("scheme", "")) == scheme and r.get("metric_name") == "search_latency_ms" for r in fig6_rows):
                warn(lines, f"fig6 {scheme} tradeoff run is missing.", [
                    "security-cost tradeoff core case timed out or failed",
                    "inspect fig6_tradeoff/skipped_cases.csv",
                ])

    for group in ["fig5", "fig6"]:
        auc_values = [
            f(r.get("mean", r.get("metric_value", "")), float("nan"))
            for r in rows
            if r.get("group") == group and r.get("metric_name", "").endswith("auc")
        ]
        auc_values = [v for v in auc_values if v == v]
        if len(auc_values) >= 3 and max(auc_values) - min(auc_values) < 0.01:
            warn(lines, f"{group} AUC values are degenerate.", [
                "attack_eval may have too few positive/negative examples",
                "TraceProbe features may be constant for this sampled workload",
                "inspect attack_eval CSVs before using this panel in the paper",
            ])

    for path in args.root.glob("*/boundary_cell_summary.csv"):
        for row in read_rows(path):
            if f(row.get("max_boundary_cells", "0")) > 2.0:
                warn(lines, "boundary_cells exceeds 2 for an ordinary interval query.", [
                    f"trace={row.get('trace')}",
                    "query decomposition may be wrong",
                    "cell intersection semantics may be over-counting boundary cells",
                ])

    out = args.root / "validation_warnings.md"
    if not lines:
        lines = ["No validation warnings were triggered.", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
