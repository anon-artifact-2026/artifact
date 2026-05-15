#!/usr/bin/env python3
"""Plot the absolute-cost heatmap from table2_summary.csv."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


METRICS = [
    ("Search (ms)", "search_latency_ms", 1.0),
    ("Patch update (ms)", "patch_update_latency_ms", 1.0),
    ("Response (MiB)", "response_kb", 1.0 / 1024.0),
    ("Storage (MiB)", "server_storage_mb", 1.0),
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def f(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifact_out/eval"))
    parser.add_argument("--out", type=Path, help="output image path")
    args = parser.parse_args()

    table = args.root / "table2_summary" / "table2_summary.csv"
    rows = read_rows(table)
    labels = [r.get("heatmap_label") or r.get("scheme", "") for r in rows]
    values = [[f(r.get(field, "")) * scale for _, field, scale in METRICS] for r in rows]

    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        raise SystemExit(f"matplotlib and numpy are required for the heatmap: {exc}")

    arr = np.array(values, dtype=float)
    fig, ax = plt.subplots(figsize=(7.2, max(3.6, 0.46 * len(labels) + 1.5)))
    finite = arr[np.isfinite(arr)]
    vmax = float(np.nanmax(arr)) if finite.size else 1.0
    image = ax.imshow(arr, aspect="auto", cmap="viridis", vmin=0.0, vmax=vmax if vmax > 0 else 1.0)
    ax.set_xticks(range(len(METRICS)))
    ax.set_xticklabels([label for label, _, _ in METRICS])
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)

    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            value = arr[i, j]
            if not math.isfinite(value):
                text = ""
            elif value >= 100:
                text = f"{value:.0f}"
            elif value >= 1:
                text = f"{value:.2f}"
            else:
                text = f"{value:.3f}"
            ax.text(j, i, text, ha="center", va="center", color="white", fontsize=8)

    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    out = args.out or (args.root / "table2_summary" / "table2_absolute_cost_heatmap.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
