#!/usr/bin/env python3
"""Validate processed LOCI real-dataset CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from dataset_loader import load_registry


def resolve_path(path_text: str, root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute() or path.exists():
        return path
    candidate = root / path
    if candidate.exists():
        return candidate
    return path


def check_one(name: str, path: Path, requested_n: int) -> bool:
    ok = True
    if not path.exists():
        print(f"WARNING: {name} missing: {path}")
        return False
    meta_path = path.with_suffix(".meta.json")
    if not meta_path.exists():
        print(f"ERROR: {name} missing metadata: {meta_path}")
        return False
    try:
        df = pd.read_csv(path, usecols=["rid", "value", "time"])
    except Exception as exc:
        print(f"ERROR: {name} cannot be read as rid,value,time CSV: {exc}")
        return False

    missing = [c for c in ["rid", "value", "time"] if c not in df.columns]
    if missing:
        print(f"ERROR: {name} missing columns: {missing}")
        return False

    for col in ["rid", "value", "time"]:
        try:
            df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")
        except Exception as exc:
            print(f"ERROR: {name}.{col} is not int64-compatible: {exc}")
            ok = False

    rows = len(df)
    if rows < requested_n:
        print(f"WARNING: {name} has only {rows} rows; max usable N is {rows}.")
    if rows == 0:
        print(f"ERROR: {name} is empty")
        return False

    rid = df["rid"].to_numpy(dtype=np.int64)
    expected = np.arange(rows, dtype=np.int64)
    if not np.array_equal(rid, expected):
        print(f"ERROR: {name} rid is not unique and consecutive from 0")
        ok = False
    if not df["time"].is_monotonic_increasing:
        print(f"ERROR: {name} is not sorted by time")
        ok = False

    value_min = int(df["value"].min())
    value_max = int(df["value"].max())
    time_min = int(df["time"].min())
    time_max = int(df["time"].max())
    if value_min > value_max or time_min > time_max:
        print(f"ERROR: {name} has invalid ranges")
        ok = False

    print(
        f"{name}: rows={rows} value=[{value_min},{value_max}] "
        f"time=[{time_min},{time_max}] path={path}"
    )
    print(df.head(5).to_string(index=False))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check LOCI processed datasets.")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--n", type=int, default=1_000_000)
    parser.add_argument("--registry", type=Path, default=Path("configs/datasets.yaml"))
    args = parser.parse_args()

    registry = load_registry(args.registry)
    datasets = registry.get("datasets", {})
    if not datasets:
        raise SystemExit(f"no datasets found in registry: {args.registry}")

    all_ok = True
    for name, entry in datasets.items():
        path_text = entry.get("path")
        if not path_text:
            print(f"WARNING: {name} has no path in registry")
            all_ok = False
            continue
        all_ok = check_one(name, resolve_path(str(path_text), args.root), args.n) and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
