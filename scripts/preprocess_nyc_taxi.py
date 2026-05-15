#!/usr/bin/env python3
"""Convert NYC TLC yellow taxi parquet files into LOCI benchmark CSV.

Output schema:
id,update_time,range_value,raw_value,PULocationID,DOLocationID,trip_distance,fare_amount

`range_value` is an order-preserving dense-rank compression of `fare_amount`
into [0, universe).  `raw_value` preserves the original fare amount.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


FIELDS = [
    "tpep_pickup_datetime",
    "PULocationID",
    "DOLocationID",
    "trip_distance",
    "fare_amount",
]


def find_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("yellow_tripdata_*.parquet")))
        elif path.is_file():
            files.append(path)
    return files


def read_inputs(files: list[Path], limit: int | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    remaining = limit
    for file in files:
        df = pd.read_parquet(file, columns=FIELDS, engine="pyarrow")
        if remaining is not None:
            df = df.head(remaining)
            remaining -= len(df)
        frames.append(df)
        if remaining is not None and remaining <= 0:
            break
    if not frames:
        raise SystemExit("no parquet input files found")
    return pd.concat(frames, ignore_index=True)


def clean(df: pd.DataFrame, max_fare: float, max_distance: float) -> pd.DataFrame:
    df = df.rename(columns={"tpep_pickup_datetime": "update_time"})
    df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
    for col in ["fare_amount", "trip_distance"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["PULocationID", "DOLocationID"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")

    mask = (
        df["update_time"].notna()
        & np.isfinite(df["fare_amount"])
        & np.isfinite(df["trip_distance"])
        & (df["fare_amount"] >= 0.0)
        & (df["fare_amount"] <= max_fare)
        & (df["trip_distance"] >= 0.0)
        & (df["trip_distance"] <= max_distance)
    )
    df = df.loc[mask, ["update_time", "fare_amount", "PULocationID", "DOLocationID", "trip_distance"]].copy()
    df = df.sort_values("update_time", kind="mergesort").reset_index(drop=True)
    return df


def add_rank_compression(df: pd.DataFrame, universe: int) -> pd.DataFrame:
    if df.empty:
        raise SystemExit("no valid rows after cleaning")
    unique = np.sort(df["fare_amount"].unique())
    ranks = np.searchsorted(unique, df["fare_amount"].to_numpy(), side="left")
    if len(unique) == 1:
        compressed = np.zeros(len(df), dtype=np.uint32)
    else:
        compressed = np.floor(ranks * ((universe - 1) / float(len(unique) - 1))).astype(np.uint32)
    out = pd.DataFrame(
        {
            "id": np.arange(len(df), dtype=np.int64),
            "update_time": df["update_time"].dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "range_value": compressed,
            "raw_value": df["fare_amount"].astype(float),
            "PULocationID": df["PULocationID"].astype("int64"),
            "DOLocationID": df["DOLocationID"].astype("int64"),
            "trip_distance": df["trip_distance"].astype(float),
            "fare_amount": df["fare_amount"].astype(float),
        }
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*", type=Path, default=[Path("data/raw/nyc_taxi"), Path("data")])
    parser.add_argument("--out", type=Path, default=Path("data/processed/nyc_taxi_yellow.csv"))
    parser.add_argument("--universe", type=int, default=1 << 20)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-fare", type=float, default=1000.0)
    parser.add_argument("--max-distance", type=float, default=500.0)
    args = parser.parse_args()

    if args.universe <= 0:
        raise SystemExit("--universe must be positive")
    files = find_inputs(args.inputs)
    if not files:
        raise SystemExit("no yellow_tripdata_*.parquet files found")
    df = read_inputs(files, args.limit)
    df = clean(df, args.max_fare, args.max_distance)
    out = add_rank_compression(df, args.universe)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"wrote {args.out} rows={len(out)} files={len(files)} universe={args.universe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
