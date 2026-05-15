#!/usr/bin/env python3
"""Export processed LOCI CSV datasets to a fixed-width int64 binary format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from dataset_loader import load_ordered_dataset


def export_one(path: Path, n: int | None, force: bool) -> Path:
    ds = load_ordered_dataset(path, n=n, sort_by="time")
    out = path.with_suffix(".bin")
    meta_out = path.with_suffix(".bin.meta.json")
    if out.exists() and not force:
        print(f"skip existing {out}")
        return out

    arr = np.column_stack([ds.rid, ds.value, ds.time]).astype("<i8", copy=False)
    arr.tofile(out)

    meta = dict(ds.meta)
    meta.update(
        {
            "binary_record": ["int64 rid", "int64 value", "int64 time"],
            "binary_endianness": "little",
            "binary_rows": int(len(ds.rid)),
            "source_csv": str(path),
        }
    )
    meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {out} rows={len(ds.rid)} bytes={out.stat().st_size}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Export processed CSV to LOCI int64 .bin.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--n", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    for path in args.paths:
        export_one(path, args.n, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
