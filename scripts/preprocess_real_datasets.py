#!/usr/bin/env python3
"""Preprocess LOCI real datasets into a common ordered-key CSV schema.

The output schema is always:

    rid,value,time

where rid is a dense 0-based record id, value is the ordered attribute used by
range search, and time is the Unix timestamp used to preserve dynamic order.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import timezone
from pathlib import Path
from typing import Iterable


def require_dependencies():
    try:
        import numpy as np  # noqa: F401
        import pandas as pd  # noqa: F401
        import pyarrow  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised by missing envs
        raise SystemExit(
            "Missing preprocessing dependency. Install with:\n"
            "  pip install pandas numpy pyarrow\n"
            f"Original error: {exc}"
        )


def import_pd_np():
    require_dependencies()
    import numpy as np
    import pandas as pd

    return pd, np


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        print(f"copy raw directory: {src} -> {dst}")
        shutil.copytree(src, dst)
    elif src.is_file():
        print(f"copy raw file: {src} -> {dst}")
        shutil.copy2(src, dst)


def ensure_dirs(root: Path) -> None:
    for base in ["raw", "processed", "workloads"]:
        for dataset in ["nyc", "gowalla", "geolife"]:
            (root / base / dataset).mkdir(parents=True, exist_ok=True)


def organize_raw(root: Path, datasets: Iterable[str]) -> None:
    """Conservatively copy root-level raw files into data/raw/* when missing."""
    ensure_dirs(root)
    selected = set(datasets)

    if "nyc" in selected:
        nyc_raw = root / "raw" / "nyc"
        for name in ["yellow_tripdata_2025-01.parquet", "yellow_tripdata_2025-02.parquet"]:
            src = root / name
            if src.exists():
                copy_if_missing(src, nyc_raw / name)
        for src in sorted(root.glob("yellow_tripdata_*.parquet")):
            copy_if_missing(src, nyc_raw / src.name)

    if "gowalla" in selected:
        gowalla_raw = root / "raw" / "gowalla"
        for name in ["Gowalla_totalCheckins.txt", "loc-gowalla_totalCheckins.txt"]:
            src = root / name
            if src.exists():
                copy_if_missing(src, gowalla_raw / name)

    if "geolife" in selected:
        geolife_raw = root / "raw" / "geolife"
        for name in ["Geolife Trajectories 1.3", "Data"]:
            src = root / name
            if src.exists():
                copy_if_missing(src, geolife_raw / name)


def to_unix_seconds(series):
    pd, _ = import_pd_np()
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    valid = dt.notna()
    out = pd.Series([pd.NA] * len(series), dtype="Int64")
    seconds = (
        dt.loc[valid]
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .astype("datetime64[s]")
        .astype("int64")
    )
    out.loc[valid] = seconds.astype("int64")
    return out


def write_processed(
    df,
    *,
    dataset: str,
    attribute: str,
    out_csv: Path,
    source_files: Iterable[Path],
    max_n: int,
    force: bool,
    extra_meta: dict | None = None,
) -> None:
    pd, np = import_pd_np()
    if out_csv.exists() and not force:
        print(f"skip existing {out_csv}")
        return

    if df.empty:
        warn(f"{dataset}_{attribute} produced no rows")
        return

    work = df.loc[:, ["value", "time"]].copy()
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work["time"] = pd.to_numeric(work["time"], errors="coerce")
    work = work.dropna(subset=["value", "time"])
    if work.empty:
        warn(f"{dataset}_{attribute} produced no rows after numeric filtering")
        return

    work["value"] = np.rint(work["value"].astype("float64")).astype("int64")
    work["time"] = np.rint(work["time"].astype("float64")).astype("int64")
    work = work.sort_values("time", kind="mergesort").head(max_n).reset_index(drop=True)
    work.insert(0, "rid", np.arange(len(work), dtype=np.int64))
    work = work.astype({"rid": "int64", "value": "int64", "time": "int64"})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    work.to_csv(out_csv, index=False)

    meta = {
        "dataset": dataset,
        "attribute": attribute,
        "source_files": [str(Path(p)) for p in source_files],
        "rows": int(len(work)),
        "value_min": int(work["value"].min()),
        "value_max": int(work["value"].max()),
        "time_min": int(work["time"].min()),
        "time_max": int(work["time"].max()),
        "schema": ["rid", "value", "time"],
        "sorted_by": "time",
        "max_n": int(max_n),
    }
    if extra_meta:
        meta.update(extra_meta)
    out_csv.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(
        f"wrote {out_csv} rows={len(work)} "
        f"value=[{meta['value_min']},{meta['value_max']}] "
        f"time=[{meta['time_min']},{meta['time_max']}]"
    )


def process_nyc(root: Path, max_n: int, force: bool) -> None:
    pd, _ = import_pd_np()
    import pyarrow.parquet as pq

    raw_dir = root / "raw" / "nyc"
    files = sorted(raw_dir.glob("yellow_tripdata_2025-*.parquet"))
    if not files:
        warn("NYC parquet files are missing under data/raw/nyc")
        return

    needed = ["tpep_pickup_datetime", "trip_distance", "total_amount", "PULocationID", "DOLocationID"]
    frames = []
    used_columns: set[str] = set()
    for path in files:
        try:
            schema_cols = pq.ParquetFile(path).schema_arrow.names
            cols = [c for c in needed if c in schema_cols]
            if "tpep_pickup_datetime" not in cols:
                warn(f"{path} lacks tpep_pickup_datetime; skipping")
                continue
            frame = pd.read_parquet(path, engine="pyarrow", columns=cols)
            frames.append(frame)
            used_columns.update(cols)
        except Exception as exc:
            warn(f"could not read NYC parquet {path}: {exc}")
    if not frames:
        warn("NYC produced no readable parquet frames")
        return

    df = pd.concat(frames, ignore_index=True)
    pickup = to_unix_seconds(df["tpep_pickup_datetime"])
    base_valid = pickup.notna() & (pickup >= 0)
    dist = pd.to_numeric(df["trip_distance"], errors="coerce") if "trip_distance" in df.columns else None
    fare = pd.to_numeric(df["total_amount"], errors="coerce") if "total_amount" in df.columns else None
    pu = pd.to_numeric(df["PULocationID"], errors="coerce") if "PULocationID" in df.columns else None
    if dist is not None:
        base_valid &= dist.notna() & (dist >= 0)
    if fare is not None:
        base_valid &= fare.notna() & (fare >= 0)
    if pu is not None:
        base_valid &= pu.notna()

    out_dir = root / "processed" / "nyc"
    common_meta = {"raw_columns": sorted(used_columns)}

    time_df = pd.DataFrame({"value": pickup, "time": pickup})
    time_df = time_df[base_valid]
    write_processed(
        time_df,
        dataset="nyc",
        attribute="time",
        out_csv=out_dir / "nyc_time.csv",
        source_files=files,
        max_n=max_n,
        force=force,
        extra_meta=common_meta,
    )

    if dist is not None:
        dist_df = pd.DataFrame({"value": dist * 1000.0, "time": pickup})
        dist_df = dist_df[base_valid]
        write_processed(
            dist_df,
            dataset="nyc",
            attribute="distance",
            out_csv=out_dir / "nyc_distance.csv",
            source_files=files,
            max_n=max_n,
            force=force,
            extra_meta={**common_meta, "value_scale": "round(trip_distance * 1000)"},
        )
    else:
        warn("NYC trip_distance column is missing")

    if fare is not None:
        fare_df = pd.DataFrame({"value": fare * 100.0, "time": pickup})
        fare_df = fare_df[base_valid]
        write_processed(
            fare_df,
            dataset="nyc",
            attribute="fare",
            out_csv=out_dir / "nyc_fare.csv",
            source_files=files,
            max_n=max_n,
            force=force,
            extra_meta={**common_meta, "value_scale": "round(total_amount * 100)"},
        )
    else:
        warn("NYC total_amount column is missing")

    if pu is not None:
        pu_df = pd.DataFrame({"value": pu, "time": pickup})
        pu_df = pu_df[base_valid]
        write_processed(
            pu_df,
            dataset="nyc",
            attribute="pu_zone",
            out_csv=out_dir / "nyc_pu_zone.csv",
            source_files=files,
            max_n=max_n,
            force=force,
            extra_meta=common_meta,
        )
    else:
        warn("NYC PULocationID column is missing")


def process_gowalla(root: Path, max_n: int, force: bool) -> None:
    pd, _ = import_pd_np()
    raw_dir = root / "raw" / "gowalla"
    candidates = [raw_dir / "Gowalla_totalCheckins.txt", raw_dir / "loc-gowalla_totalCheckins.txt"]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        warn("Gowalla check-in file is missing under data/raw/gowalla")
        return

    chunks = []
    names = ["user_id", "checkin_time", "latitude", "longitude", "location_id"]
    try:
        for chunk in pd.read_csv(
            path,
            sep="\t",
            names=names,
            usecols=names,
            chunksize=250_000,
            dtype={"user_id": "string", "location_id": "string"},
        ):
            chunk = chunk.reset_index(drop=True)
            ts = to_unix_seconds(chunk["checkin_time"])
            lat = pd.to_numeric(chunk["latitude"], errors="coerce")
            lon = pd.to_numeric(chunk["longitude"], errors="coerce")
            loc = pd.to_numeric(chunk["location_id"], errors="coerce")
            valid = ts.notna() & (ts >= 0) & lat.between(-90, 90) & lon.between(-180, 180) & loc.notna()
            if valid.any():
                chunks.append(
                    pd.DataFrame(
                        {
                            "time": ts[valid],
                            "location": loc[valid],
                            "lat": lat[valid],
                            "lon": lon[valid],
                        }
                    )
                )
    except Exception as exc:
        warn(f"could not read Gowalla file {path}: {exc}")
        return
    if not chunks:
        warn("Gowalla produced no valid rows")
        return

    df = pd.concat(chunks, ignore_index=True)
    out_dir = root / "processed" / "gowalla"
    source = [path]
    write_processed(
        pd.DataFrame({"value": df["time"], "time": df["time"]}),
        dataset="gowalla",
        attribute="time",
        out_csv=out_dir / "gowalla_time.csv",
        source_files=source,
        max_n=max_n,
        force=force,
    )
    write_processed(
        pd.DataFrame({"value": df["location"], "time": df["time"]}),
        dataset="gowalla",
        attribute="location",
        out_csv=out_dir / "gowalla_location.csv",
        source_files=source,
        max_n=max_n,
        force=force,
    )
    write_processed(
        pd.DataFrame({"value": (df["lat"] + 90.0) * 1_000_000.0, "time": df["time"]}),
        dataset="gowalla",
        attribute="lat",
        out_csv=out_dir / "gowalla_lat.csv",
        source_files=source,
        max_n=max_n,
        force=force,
        extra_meta={"value_scale": "round((latitude + 90.0) * 1000000)"},
    )
    write_processed(
        pd.DataFrame({"value": (df["lon"] + 180.0) * 1_000_000.0, "time": df["time"]}),
        dataset="gowalla",
        attribute="lon",
        out_csv=out_dir / "gowalla_lon.csv",
        source_files=source,
        max_n=max_n,
        force=force,
        extra_meta={"value_scale": "round((longitude + 180.0) * 1000000)"},
    )


def geolife_data_dir(root: Path) -> Path | None:
    candidates = [
        root / "raw" / "geolife" / "Geolife Trajectories 1.3" / "Data",
        root / "raw" / "geolife" / "Data",
    ]
    return next((p for p in candidates if p.exists()), None)


def parse_geolife_timestamp(date_s: str, time_s: str) -> int | None:
    from datetime import datetime

    try:
        dt = datetime.strptime(f"{date_s.strip()} {time_s.strip()}", "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return None


def process_geolife(root: Path, max_n: int, force: bool) -> None:
    pd, _ = import_pd_np()
    data_dir = geolife_data_dir(root)
    if data_dir is None:
        warn("GeoLife trajectory directory is missing under data/raw/geolife")
        return

    rows: list[tuple[int, float, float, float]] = []
    source_count = 0
    for path in sorted(data_dir.glob("*/Trajectory/*.plt")):
        source_count += 1
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for line_no, line in enumerate(fh):
                    if line_no < 6:
                        continue
                    parts = line.strip().split(",")
                    if len(parts) < 7:
                        continue
                    try:
                        lat = float(parts[0])
                        lon = float(parts[1])
                        alt = float(parts[3])
                    except ValueError:
                        continue
                    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                        continue
                    if not math.isfinite(alt) or alt < -2000 or alt > 200000:
                        continue
                    ts = parse_geolife_timestamp(parts[5], parts[6])
                    if ts is None or ts < 0:
                        continue
                    rows.append((ts, lat, lon, alt))
        except Exception as exc:
            warn(f"could not read GeoLife file {path}: {exc}")
    if not rows:
        warn("GeoLife produced no valid rows")
        return

    df = pd.DataFrame(rows, columns=["time", "lat", "lon", "alt"])
    out_dir = root / "processed" / "geolife"
    source_meta = {"source_file_count": source_count}
    write_processed(
        pd.DataFrame({"value": df["time"], "time": df["time"]}),
        dataset="geolife",
        attribute="time",
        out_csv=out_dir / "geolife_time.csv",
        source_files=[data_dir],
        max_n=max_n,
        force=force,
        extra_meta=source_meta,
    )
    write_processed(
        pd.DataFrame({"value": (df["lat"] + 90.0) * 1_000_000.0, "time": df["time"]}),
        dataset="geolife",
        attribute="lat",
        out_csv=out_dir / "geolife_lat.csv",
        source_files=[data_dir],
        max_n=max_n,
        force=force,
        extra_meta={**source_meta, "value_scale": "round((latitude + 90.0) * 1000000)"},
    )
    write_processed(
        pd.DataFrame({"value": (df["lon"] + 180.0) * 1_000_000.0, "time": df["time"]}),
        dataset="geolife",
        attribute="lon",
        out_csv=out_dir / "geolife_lon.csv",
        source_files=[data_dir],
        max_n=max_n,
        force=force,
        extra_meta={**source_meta, "value_scale": "round((longitude + 180.0) * 1000000)"},
    )
    write_processed(
        pd.DataFrame({"value": df["alt"] * 10.0, "time": df["time"]}),
        dataset="geolife",
        attribute="alt",
        out_csv=out_dir / "geolife_alt.csv",
        source_files=[data_dir],
        max_n=max_n,
        force=force,
        extra_meta={
            **source_meta,
            "value_scale": "round(altitude * 10)",
            "altitude_filter": "-2000 <= altitude <= 200000",
        },
    )


def parse_dataset_list(value: str) -> list[str]:
    allowed = {"nyc", "gowalla", "geolife"}
    out = [x.strip().lower() for x in value.split(",") if x.strip()]
    bad = [x for x in out if x not in allowed]
    if bad:
        raise SystemExit(f"unknown datasets: {', '.join(bad)}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Preprocess NYC, Gowalla, and GeoLife for LOCI.")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--max-n", type=int, default=1_000_000)
    parser.add_argument("--datasets", default="nyc,gowalla,geolife")
    parser.add_argument("--force", action="store_true", help="overwrite processed CSV/meta outputs")
    args = parser.parse_args()

    if args.max_n <= 0:
        raise SystemExit("--max-n must be positive")

    root = args.root
    datasets = parse_dataset_list(args.datasets)
    require_dependencies()
    organize_raw(root, datasets)

    if "nyc" in datasets:
        process_nyc(root, args.max_n, args.force)
    if "gowalla" in datasets:
        process_gowalla(root, args.max_n, args.force)
    if "geolife" in datasets:
        process_geolife(root, args.max_n, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
