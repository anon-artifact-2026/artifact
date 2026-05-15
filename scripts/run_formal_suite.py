#!/usr/bin/env python3
"""Run the full paper-style experiment suite from a YAML manifest.

Outputs are stable by default: each experiment writes to
`<root>/<experiment_name>`, and the target directory is deleted before the run.
Use `--no-clean` only when intentionally appending to existing results.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def bench_exe() -> str:
    exe = Path("bench_loci.exe" if os.name == "nt" else "bench_loci")
    path = Path.cwd() / exe
    if not path.exists():
        raise FileNotFoundError(f"Cannot find benchmark executable: {path}. Build first.")
    return str(path)


def run(cmd: list[str], *, dry_run: bool = False) -> None:
    print("+", " ".join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, check=True)


def run_logged(cmd: list[str], log_path: Path, *, dry_run: bool = False) -> None:
    print("+", " ".join(cmd), "| tee", str(log_path), flush=True)
    if dry_run:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        rc = proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def build(skip_build: bool, dry_run: bool) -> None:
    if skip_build:
        return
    run(["mingw32-make"] if os.name == "nt" else ["make"], dry_run=dry_run)


def preprocess_if_needed(cfg: dict, key: str, *, force: bool, dry_run: bool) -> None:
    pre = cfg.get("preprocess", {}).get(key)
    if not pre:
        return
    out = Path(pre["out"])
    if out.exists() and not force:
        return
    cmd = [
        sys.executable,
        "scripts/preprocess_nyc_taxi.py",
        *[str(x) for x in pre.get("inputs", ["data"])],
        "--out",
        str(out),
        "--universe",
        str(pre.get("universe", 1 << 20)),
    ]
    if pre.get("limit"):
        cmd += ["--limit", str(pre["limit"])]
    run(cmd, dry_run=dry_run)


def common_args(bench: dict, dataset: dict, results: Path, traces: Path) -> list[str]:
    args = [
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
    if dataset.get("type") == "csv":
        args += ["--data-csv", str(dataset["path"])]
        if dataset.get("limit"):
            args += ["--data-limit", str(dataset["limit"])]
    return args


def case_name(case: dict, suffix: str = "") -> str:
    base = f"{case['scheme']}_{case['variant']}".replace("-", "_")
    return f"{base}_{suffix}" if suffix else base


def expanded_benchmarks(exp: dict) -> list[tuple[dict, str]]:
    base = dict(exp.get("benchmark", {}))
    sweep = exp.get("sweep")
    if not sweep:
        return [(base, "")]
    param = sweep["parameter"]
    out = []
    for value in sweep["values"]:
        bench = dict(base)
        bench[param] = value
        out.append((bench, f"{param}{value}"))
    return out


def run_experiment(cfg: dict, exp: dict, root: Path, args: argparse.Namespace, exe: str) -> None:
    out_dir = root / exp["name"]
    if args.clean and out_dir.exists() and not args.dry_run:
        shutil.rmtree(out_dir)
    logs = out_dir / "logs"
    traces = out_dir / "traces"
    figures = out_dir / "figure_groups"
    results = out_dir / "results.csv"
    attack_csv = out_dir / "attack_eval.csv"
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": exp["name"],
        "description": exp.get("description", ""),
        "dataset": exp.get("dataset", {}),
        "benchmark": exp.get("benchmark", {}),
        "sweep": exp.get("sweep"),
        "cases": exp.get("cases", []),
    }
    if not args.dry_run:
        (out_dir / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    dataset = exp.get("dataset", {})
    if dataset.get("preprocess"):
        preprocess_if_needed(cfg, dataset["preprocess"], force=args.force_preprocess, dry_run=args.dry_run)
    if dataset.get("type") == "csv" and not Path(dataset["path"]).exists() and not args.dry_run:
        raise FileNotFoundError(f"Dataset CSV does not exist: {dataset['path']}")

    for bench, suffix in expanded_benchmarks(exp):
        cargs = common_args(bench, dataset, results, traces)
        for case in exp.get("cases", []):
            cmd = [exe, "--scheme", str(case["scheme"]), "--variant", str(case["variant"]), *cargs]
            run_logged(cmd, logs / f"{case_name(case, suffix)}.log", dry_run=args.dry_run)

    if exp.get("attack_eval", True):
        run([sys.executable, "scripts/attack_eval.py", str(traces), "--csv", str(attack_csv)], dry_run=args.dry_run)
    run([sys.executable, "scripts/plot_figures.py", str(results), "--out-dir", str(figures)], dry_run=args.dry_run)
    print(f"wrote {out_dir}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/formal_suite.yaml"))
    parser.add_argument("--only", help="Comma-separated experiment names to run.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--clean", dest="clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.add_argument("--force-preprocess", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    experiments = cfg.get("experiments", [])
    if args.list:
        for exp in experiments:
            print(exp["name"])
        return 0

    selected = None
    if args.only:
        selected = {x.strip() for x in args.only.split(",") if x.strip()}
    to_run = [exp for exp in experiments if selected is None or exp["name"] in selected]
    missing = selected - {exp["name"] for exp in experiments} if selected else set()
    if missing:
        raise SystemExit(f"unknown experiment(s): {', '.join(sorted(missing))}")

    build(args.skip_build, args.dry_run)
    exe = bench_exe()
    root = Path(cfg.get("root", "artifact_out/formal"))
    for exp in to_run:
        run_experiment(cfg, exp, root, args, exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
