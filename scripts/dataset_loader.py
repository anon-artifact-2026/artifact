#!/usr/bin/env python3
"""Unified ordered dataset loader and real-data workload helpers for LOCI."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class OrderedDataset:
    name: str
    attribute: str
    path: str
    rid: np.ndarray
    value: np.ndarray
    time: np.ndarray
    meta: dict


def _meta_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def _read_meta(path: Path) -> dict:
    meta_path = _meta_path(path)
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    stem = path.stem
    if "_" in stem:
        name, attribute = stem.split("_", 1)
    else:
        name, attribute = stem, "value"
    return {"dataset": name, "attribute": attribute, "schema": ["rid", "value", "time"]}


def load_ordered_dataset(path: str | Path, n: int | None = None, sort_by: str = "time") -> OrderedDataset:
    """Load a processed LOCI dataset CSV.

    Args:
        path: CSV path with columns rid,value,time.
        n: Optional row cap after sorting.
        sort_by: "time", "value", or "none". The default keeps dynamic order.
    """
    path = Path(path)
    meta = _read_meta(path)
    df = pd.read_csv(path, usecols=["rid", "value", "time"])
    for col in ["rid", "value", "time"]:
        df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")
    if sort_by == "time":
        df = df.sort_values("time", kind="mergesort")
    elif sort_by == "value":
        df = df.sort_values(["value", "rid"], kind="mergesort")
    elif sort_by in {"none", None}:
        pass
    else:
        raise ValueError(f"unknown sort_by={sort_by!r}")
    if n is not None:
        df = df.head(int(n))
    df = df.reset_index(drop=True)
    return OrderedDataset(
        name=str(meta.get("dataset", path.parent.name)),
        attribute=str(meta.get("attribute", path.stem)),
        path=str(path),
        rid=df["rid"].to_numpy(dtype=np.int64),
        value=df["value"].to_numpy(dtype=np.int64),
        time=df["time"].to_numpy(dtype=np.int64),
        meta=meta,
    )


def build_initial_db(ds: OrderedDataset, n: int, init_ratio: float = 0.8):
    """Split the first n time-ordered records into initial DB and held-out adds."""
    n = min(int(n), len(ds.rid))
    if not (0.0 < init_ratio <= 1.0):
        raise ValueError("init_ratio must be in (0, 1]")
    init_n = int(n * init_ratio)
    initial_db = [(int(ds.rid[i]), int(ds.value[i])) for i in range(init_n)]
    heldout_adds = [(int(ds.rid[i]), int(ds.value[i]), int(ds.time[i])) for i in range(init_n, n)]
    return initial_db, heldout_adds


def _default_workload_dir(ds: OrderedDataset) -> Path:
    return Path("data") / "workloads" / ds.name


def _remove_active(active_ids: list[int], active_pos: dict[int, int], rid: int) -> None:
    pos = active_pos.pop(rid)
    last = active_ids.pop()
    if pos < len(active_ids):
        active_ids[pos] = last
        active_pos[last] = pos


def make_update_stream(
    ds: OrderedDataset,
    n: int,
    init_ratio: float,
    ops: int,
    del_ratio: float,
    seed: int,
    out_path: str | Path | None = None,
):
    """Generate add/delete operations from real temporal order.

    Adds consume held-out records in time order. Deletes sample from the current
    active set and never delete a non-active rid.
    """
    rng = np.random.default_rng(seed)
    initial_db, heldout_adds = build_initial_db(ds, n, init_ratio)
    active_ids = [rid for rid, _ in initial_db]
    active_values = {rid: value for rid, value in initial_db}
    active_pos = {rid: i for i, rid in enumerate(active_ids)}
    add_cursor = 0
    if initial_db:
        last_time = int(ds.time[len(initial_db) - 1])
    elif len(ds.time):
        last_time = int(ds.time[0]) - 1
    else:
        last_time = 0
    rows: list[dict[str, int | str]] = []

    for _ in range(int(ops)):
        can_add = add_cursor < len(heldout_adds)
        can_del = bool(active_ids)
        choose_del = can_del and (not can_add or float(rng.random()) < del_ratio)
        if choose_del:
            idx = int(rng.integers(0, len(active_ids)))
            rid = active_ids[idx]
            value = active_values.pop(rid)
            _remove_active(active_ids, active_pos, rid)
            last_time += 1
            rows.append({"op": "del", "rid": int(rid), "value": int(value), "time": int(last_time)})
        elif can_add:
            rid, value, ts = heldout_adds[add_cursor]
            add_cursor += 1
            if rid in active_values:
                continue
            active_pos[rid] = len(active_ids)
            active_ids.append(rid)
            active_values[rid] = value
            last_time = max(last_time + 1, int(ts))
            rows.append({"op": "add", "rid": int(rid), "value": int(value), "time": int(last_time)})
        else:
            break

    if out_path is None:
        out_path = _default_workload_dir(ds) / f"{ds.name}_{ds.attribute}_N{n}_updates.csv"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["op", "rid", "value", "time"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def make_range_queries(
    ds: OrderedDataset,
    n: int,
    q: int,
    width_fracs: Iterable[float],
    seed: int,
    out_path: str | Path | None = None,
):
    """Generate empirical-domain range queries."""
    rng = np.random.default_rng(seed)
    values = ds.value[: min(int(n), len(ds.value))]
    if len(values) == 0:
        raise ValueError("dataset has no values")
    value_min = int(values.min())
    value_max = int(values.max())
    span = value_max - value_min + 1
    unique = np.unique(values)
    width_fracs = [float(w) for w in width_fracs]
    if not width_fracs:
        raise ValueError("width_fracs must not be empty")

    rows: list[dict[str, int | float]] = []
    low_domain = len(unique) <= max(1024, int(q) * 4)
    for qid in range(int(q)):
        frac = width_fracs[qid % len(width_fracs)]
        frac = min(max(frac, 0.0), 1.0)
        if low_domain:
            width_count = max(1, int(round(len(unique) * frac)))
            width_count = min(width_count, len(unique))
            start_hi = max(0, len(unique) - width_count)
            start = int(rng.integers(0, start_hi + 1)) if start_hi else 0
            L = int(unique[start])
            R = int(unique[start + width_count - 1])
        else:
            width = max(1, int(math_floor(span * frac)))
            width = min(width, span)
            max_L = value_max - width + 1
            L = int(rng.integers(value_min, max_L + 1)) if max_L >= value_min else value_min
            R = int(L + width - 1)
        rows.append({"qid": qid, "L": L, "R": R, "width_frac": frac})

    if out_path is None:
        out_path = _default_workload_dir(ds) / f"{ds.name}_{ds.attribute}_N{n}_queries.csv"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["qid", "L", "R", "width_frac"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def math_floor(x: float) -> int:
    return int(np.floor(x))


def load_registry(path: str | Path = "configs/datasets.yaml") -> dict:
    """Load dataset registry if PyYAML is available; otherwise use a small parser."""
    path = Path(path)
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        datasets: dict[str, dict[str, str | bool]] = {}
        current: str | None = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("  ") and line.endswith(":") and not line.startswith("    "):
                current = line.strip()[:-1]
                datasets[current] = {}
            elif current and line.startswith("    ") and ":" in line:
                key, value = line.strip().split(":", 1)
                value = value.strip()
                datasets[current][key] = True if value == "true" else False if value == "false" else value
        return {"datasets": datasets}
