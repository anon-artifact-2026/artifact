#!/usr/bin/env python3
"""Create paper-facing benchmark subsets from the full result CSV.

The artifact keeps all schemes in code and in raw results.  This helper writes
one CSV per paper question with only the schemes that should appear together in
the main text.  If matplotlib is installed, it can also emit simple bar plots.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


GROUPS = {
    "learned_layout_leakage": [
        "Random",
        "FixedCell-Bitmap",
        "PGM-Learned-Naive",
        "LOCI-Full",
    ],
    "padding_tradeoff": [
        "PGM-Learned-Naive",
        "PGM-Learned-GlobalPad",
        "LOCI-Full",
    ],
    "loci_components": [
        "LOCI-NoCert",
        "LOCI-NoPad",
        "LOCI-NoPublicRefresh",
        "LOCI-Full",
    ],
    "lbc_compression": [
        "LOCI-NoProto",
        "LOCI-Full",
        "PGM-Learned-GlobalPad",
    ],
    "search_performance": [
        "FBDSSE-RQ-TreeCover",
        "FixedCell-Bitmap",
        "PGM-Learned-Naive",
        "LOCI-Full",
    ],
    "update_maintenance": [
        "FBDSSE-RQ-TreeCover",
        "PGM-Learned-Naive",
        "PGM-Learned-GlobalPad",
        "LOCI-Full",
    ],
    "storage_build": [
        "FBDSSE-RQ-TreeCover",
        "PGM-Learned-Naive",
        "PGM-Learned-GlobalPad",
        "LOCI-NoProto",
        "LOCI-Full",
    ],
}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if "case" not in row or not row["case"]:
            row["case"] = fallback_case(row)
    return rows


def fallback_case(row: dict[str, str]) -> str:
    scheme = row.get("scheme", "")
    variant = row.get("variant", "")
    if scheme == "loci":
        names = {
            "full": "LOCI-Full",
            "nocert": "LOCI-NoCert",
            "nopad": "LOCI-NoPad",
            "noproto": "LOCI-NoProto",
            "nopublicrefresh": "LOCI-NoPublicRefresh",
        }
        return names.get(variant, f"LOCI-{variant}")
    if scheme == "pgm":
        return "PGM-Learned-GlobalPad" if variant == "globalpad" else "PGM-Learned-Naive"
    if scheme == "fixedcell":
        return "FixedCell-Bitmap"
    if scheme in {"fbdsse", "fbdsse-rq", "treecover"}:
        return "FBDSSE-RQ-TreeCover"
    return f"{scheme}-{variant}"


def write_subset(rows: list[dict[str, str]], out_path: Path) -> None:
    if not rows:
        return
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def maybe_plot(rows: list[dict[str, str]], out_path: Path, metric: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    if not rows or metric not in rows[0]:
        return
    labels = [r["case"] for r in rows]
    values = [float(r.get(metric) or 0) for r in rows]
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.4), 3.2))
    ax.bar(labels, values)
    ax.set_ylabel(metric)
    ax.tick_params(axis="x", labelrotation=25)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_csv", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("figures"))
    parser.add_argument("--metric", default="avg_query_ms")
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()

    rows = load_rows(args.results_csv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, cases in GROUPS.items():
        selected = [r for r in rows if r["case"] in cases]
        order = {case: i for i, case in enumerate(cases)}
        selected.sort(key=lambda r: order.get(r["case"], len(order)))
        write_subset(selected, args.out_dir / f"{name}.csv")
        if args.plots:
            maybe_plot(selected, args.out_dir / f"{name}_{args.metric}.png", args.metric)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
