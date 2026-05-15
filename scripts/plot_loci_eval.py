#!/usr/bin/env python3
"""Plot LOCI evaluation figure_data.csv files."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


GROUP_DIRS = {
    "fig1": "fig1_leakage_certification",
    "fig2": "fig2_component_ablation",
    "fig3": "fig3_scalability_selectivity",
    "fig4": "fig4_dynamic_refresh",
    "fig5": "fig5_real_datasets",
    "fig6": "fig6_tradeoff",
    "fig_mechanism": "fig_mechanism_cell_load_touch_skew",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def f(row: dict[str, str], name: str, default: float = 0.0) -> float:
    try:
        return float(row.get(name, default))
    except Exception:
        return default


def finite_value(row: dict[str, str], name: str) -> bool:
    value = f(row, name, float("nan"))
    return not math.isnan(value)


def scheme_alias(name: str) -> str:
    if name in {"GlobalPad", "PGM-Learned-GlobalPad"}:
        return "ResponseGlobalPad"
    return name


def normalize_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        r = dict(row)
        r["scheme"] = scheme_alias(r.get("scheme", ""))
        out.append(r)
    return out


def select_highest_N(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return rows
    max_n = max(f(r, "N") for r in rows)
    return [r for r in rows if f(r, "N") == max_n]


def metric_map(rows: list[dict[str, str]], metric: str) -> list[dict[str, str]]:
    return [r for r in rows if r.get("metric_name") == metric]


def save(fig, out_base: Path) -> None:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_base.with_suffix(".pdf"))
    fig.savefig(out_base.with_suffix(".png"), dpi=180)


def plot_grouped_bars(plt, rows: list[dict[str, str]], out_base: Path, metrics: list[str], title: str) -> None:
    rows = select_highest_N(normalize_rows(rows))
    if not rows:
        return
    schemes = sorted({r["scheme"] for r in rows})
    fig, axes = plt.subplots(1, len(metrics), figsize=(max(5, 3.6 * len(metrics)), 3.6), squeeze=False)
    for ax, metric in zip(axes[0], metrics):
        mrows = metric_map(rows, metric)
        values = []
        labels = []
        for scheme in schemes:
            vals = [f(r, "mean") for r in mrows if r["scheme"] == scheme]
            if vals:
                labels.append(scheme)
                values.append(sum(vals) / len(vals))
        ax.bar(labels, values)
        ax.set_title(metric)
        ax.set_ylim(0.45 if metric.endswith("auc") else 0, max(1.0, max(values, default=1.0) * 1.15))
        ax.tick_params(axis="x", labelrotation=28)
    fig.suptitle(title)
    save(fig, out_base)
    plt.close(fig)


def plot_fig3(plt, rows: list[dict[str, str]], out_base: Path) -> None:
    rows = normalize_rows(rows)
    if not rows:
        return
    has_timeout = any(r.get("metric_name") == "timeout" and f(r, "mean") >= 1.0 for r in rows)
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8))
    panels = [
        ("search_latency_ms", "N", "scale", "(a) search latency", axes[0]),
        ("update_latency_ms", "N", "scale", "(b) update latency", axes[1]),
        ("response_bytes", "selectivity", "selectivity", "(c) response bytes", axes[2]),
        ("server_storage_bytes", "N", "scale", "(d) server storage", axes[3]),
    ]
    schemes = sorted({r["scheme"] for r in rows})
    for metric, xfield, axis_name, title, ax in panels:
        for scheme in schemes:
            if axis_name == "selectivity" and scheme == "TreeCover":
                continue
            pts = [
                r for r in rows
                if r["metric_name"] == metric
                and r["scheme"] == scheme
                and r.get("axis") == axis_name
                and finite_value(r, "mean")
            ]
            if not pts:
                continue
            pts.sort(key=lambda r: f(r, xfield))
            ax.plot([f(r, xfield) for r in pts], [f(r, "mean") for r in pts], marker="o", label=scheme)
        ax.set_title(title)
        ax.set_xlabel(xfield)
        if xfield == "N":
            ax.tick_params(axis="x", labelrotation=25)
    if has_timeout:
        fig.text(0.02, 0.01, "TreeCover is capped at 25K due to runtime; omitted or timed-out points are not interpolated.", fontsize=8)
    axes[3].legend(fontsize=7)
    save(fig, out_base)
    plt.close(fig)


def plot_fig4(plt, rows: list[dict[str, str]], out_base: Path) -> None:
    rows = select_highest_N(normalize_rows(rows))
    if not rows:
        return
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    panels = [
        ("patch_pressure_adv_auc", axes[0][0]),
        ("maintenance_cause_adv_auc", axes[0][1]),
        ("patch_occupancy", axes[1][0]),
        ("refresh_bytes", axes[1][1]),
    ]
    schemes = sorted({r["scheme"] for r in rows})
    workloads = sorted({r["workload"] for r in rows})
    for metric, ax in panels:
        for scheme in schemes:
            vals = []
            for workload in workloads:
                pts = [f(r, "mean") for r in rows if r["metric_name"] == metric and r["scheme"] == scheme and r["workload"] == workload]
                vals.append(sum(pts) / len(pts) if pts else 0)
            ax.plot(workloads, vals, marker="o", label=scheme)
        ax.set_title(metric)
        ax.tick_params(axis="x", labelrotation=20)
    axes[1][1].legend(fontsize=7)
    save(fig, out_base)
    plt.close(fig)


def plot_fig5(plt, rows: list[dict[str, str]], out_base: Path) -> None:
    rows = normalize_rows(rows)
    if not rows:
        return
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    panels = [
        ("search_latency_ms", "(a) Search latency", axes[0]),
        ("response_bytes", "(b) Communication", axes[1]),
        ("max_cert_probe_auc", "(c) Certified-probe AUC", axes[2]),
    ]
    schemes = sorted({r["scheme"] for r in rows if r.get("metric_name") not in {"timeout", "failed", "skipped"}})
    datasets = sorted({r["dataset"] for r in rows})
    x = list(range(len(datasets)))
    width = 0.8 / max(1, len(schemes))
    for metric, title, ax in panels:
        for i, scheme in enumerate(schemes):
            xs = [v - 0.4 + width / 2 + i * width for v in x]
            vals = []
            for ds in datasets:
                pts = [f(r, "mean") for r in rows if r["metric_name"] == metric and r["scheme"] == scheme and r["dataset"] == ds and finite_value(r, "mean")]
                vals.append(sum(pts) / len(pts) if pts else float("nan"))
            ax.bar(xs, vals, width=width, label=scheme)
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(datasets)
        ax.tick_params(axis="x", labelrotation=20)
    fig.text(0.02, 0.01, "Fig.5 uses sampled 200K records per real dataset; heavy omitted baselines are not shown.", fontsize=8)
    axes[2].legend(fontsize=7)
    save(fig, out_base)
    plt.close(fig)


def plot_fig6(plt, rows: list[dict[str, str]], out_base: Path) -> None:
    rows = normalize_rows(rows)
    if not rows:
        return
    schemes = sorted({r["scheme"] for r in rows if r.get("metric_name") not in {"timeout", "failed", "skipped"}})
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.8))
    panels = [
        ("search_latency_ms", "(a) Latency vs public budget", axes[0]),
        ("response_bytes", "(b) Communication vs budget", axes[1]),
        ("max_cert_probe_auc", "(c) TraceProbe AUC vs budget", axes[2]),
    ]
    for metric, title, ax in panels:
        for scheme in schemes:
            pts = [
                r for r in rows
                if r["metric_name"] == metric
                and r["scheme"] == scheme
                and finite_value(r, "mean")
            ]
            if not pts:
                continue
            pts.sort(key=lambda r: f(r, "budget", f(r, "theta", f(r, "N"))))
            xs = [f(r, "budget", f(r, "theta", f(r, "N"))) for r in pts]
            ys = [f(r, "mean") for r in pts]
            ax.plot(xs, ys, marker="o", label=scheme)
        ax.set_title(title)
        ax.set_xlabel("budget")
    axes[2].legend(fontsize=7)
    save(fig, out_base)
    plt.close(fig)


def plot_fig_mechanism(plt, rows: list[dict[str, str]], out_base: Path) -> None:
    rows = normalize_rows(rows)
    if not rows:
        return
    panels = [
        ("synthetic_cell_load", "(a) Synthetic cell load"),
        ("real_cell_load", "(b) Real-data cell load"),
        ("update_touch_synthetic", "(c) Synthetic update touches"),
        ("update_touch_real", "(d) Real-data update touches"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2))
    for ax, (panel, title) in zip(axes.ravel(), panels):
        prows = [r for r in rows if r.get("panel") == panel and finite_value(r, "value")]
        series = sorted({(r.get("dataset", ""), r.get("workload", ""), r.get("scheme", ""), r.get("seed", "")) for r in prows})
        for dataset, workload, scheme, seed in series:
            pts = [
                r for r in prows
                if r.get("dataset") == dataset
                and r.get("workload") == workload
                and r.get("scheme") == scheme
                and r.get("seed") == seed
            ]
            pts.sort(key=lambda r: f(r, "rank"))
            label = f"{dataset} s{seed}"
            ax.plot([f(r, "rank") for r in pts], [f(r, "value") for r in pts], linewidth=1.0, alpha=0.75, label=label)
        ax.set_title(title)
        ax.set_xlabel("rank")
        ax.set_ylabel("value")
        if any(f(r, "rank") > 10 for r in prows):
            ax.set_xscale("log")
        positive_values = [f(r, "value") for r in prows if f(r, "value") > 0]
        if positive_values and len(positive_values) == len(prows):
            ax.set_yscale("log")
        if series:
            ax.legend(fontsize=6)
    save(fig, out_base)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifact_out/eval"))
    parser.add_argument("--out", type=Path, help="alias for --root")
    args = parser.parse_args()
    if args.out is not None:
        args.root = args.out

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        raise SystemExit(f"matplotlib is required for plotting: {exc}")

    plot_grouped_bars(
        plt,
        read_rows(args.root / GROUP_DIRS["fig1"] / "figure_data.csv"),
        args.root / GROUP_DIRS["fig1"] / "fig1_leakage_certification",
        ["layout_shape_adv_auc", "patch_pressure_adv_auc", "maintenance_cause_adv_auc"],
        "Main leakage certification",
    )
    plot_grouped_bars(
        plt,
        read_rows(args.root / GROUP_DIRS["fig2"] / "figure_data.csv"),
        args.root / GROUP_DIRS["fig2"] / "fig2_component_ablation",
        ["layout_shape_adv_auc", "patch_pressure_adv_auc", "maintenance_cause_adv_auc"],
        "Component ablation",
    )
    plot_fig3(plt, read_rows(args.root / GROUP_DIRS["fig3"] / "figure_data.csv"), args.root / GROUP_DIRS["fig3"] / "fig3_scalability_selectivity")
    plot_fig4(plt, read_rows(args.root / GROUP_DIRS["fig4"] / "figure_data.csv"), args.root / GROUP_DIRS["fig4"] / "fig4_dynamic_refresh")
    plot_fig5(plt, read_rows(args.root / GROUP_DIRS["fig5"] / "figure_data.csv"), args.root / GROUP_DIRS["fig5"] / "fig5_real_datasets")
    fig6_rows = read_rows(args.root / GROUP_DIRS["fig6"] / "figure_data.csv")
    if not fig6_rows:
        fig6_rows = [r for r in read_rows(args.root / "all_summary.csv") if r.get("group") == "fig6"]
    plot_fig6(plt, fig6_rows, args.root / GROUP_DIRS["fig6"] / "fig6_tradeoff")
    plot_fig_mechanism(
        plt,
        read_rows(args.root / GROUP_DIRS["fig_mechanism"] / "figure_data.csv"),
        args.root / GROUP_DIRS["fig_mechanism"] / "fig_mechanism_cell_load_touch_skew",
    )
    print(f"plots written under {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
