#!/usr/bin/env python3
"""Run benchmark cases from a YAML config."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def bench_exe() -> str:
    exe = "bench_loci.exe" if os.name == "nt" else "bench_loci"
    path = Path.cwd() / exe
    if path.exists():
        return str(path)
    raise FileNotFoundError(f"Cannot find benchmark executable: {path}. Run `make` first.")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    bench = cfg.get("benchmark", {})
    dataset = cfg.get("dataset", {})
    out_dir = Path(bench.get("out_dir", f"artifact_out/{cfg.get('name', args.config.stem)}"))
    results = out_dir / "results.csv"
    traces = out_dir / "traces"
    attack = out_dir / "attack_eval.csv"
    figures = out_dir / "figure_groups"

    if not args.skip_build:
        if os.name == "nt":
            run(["mingw32-make"])
        else:
            run(["make"])

    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in [results, attack]:
        if path.exists():
            path.unlink()
    for path in [traces, figures]:
        if path.exists():
            shutil.rmtree(path)

    common = [
        "--N",
        str(bench.get("N", 3000)),
        "--ops",
        str(bench.get("ops", 500)),
        "--U",
        str(bench.get("U", 1 << 20)),
        "--B",
        str(bench.get("B", 512)),
        "--theta",
        str(bench.get("theta", 32)),
        "--dist",
        str(bench.get("dist", "skew")),
        "--workload",
        str(bench.get("workload", "mixed")),
        "--crypto",
        str(bench.get("crypto", "mock")),
        "--csv",
        str(results),
        "--trace-dir",
        str(traces),
    ]
    if dataset.get("name"):
        common += ["--dataset", str(dataset["name"])]
        if dataset.get("limit"):
            common += ["--data-limit", str(dataset["limit"])]
    elif dataset.get("type") == "csv":
        common += ["--data-csv", str(dataset["path"])]
        if dataset.get("limit"):
            common += ["--data-limit", str(dataset["limit"])]

    exe = bench_exe()
    for case in cfg.get("cases", []):
        run([exe, "--scheme", str(case["scheme"]), "--variant", str(case["variant"]), *common])

    py = sys.executable
    run([py, "scripts/attack_eval.py", str(traces), "--csv", str(attack)])
    run([py, "scripts/plot_figures.py", str(results), "--out-dir", str(figures), "--metric", "avg_query_ms"])
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
