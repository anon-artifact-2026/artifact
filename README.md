# LOCI Artifact Repository

## Project Overview

LOCI is a C++17 research prototype for leakage-certified learned layouts for encrypted range search. The repository contains the LOCI/LBC implementation, baseline layouts, TraceProbe evaluator, benchmark drivers, experiment configurations, processed real-trace inputs, and curated artifact results.

The canonical paper-result layer is `artifact_results_sp/`. It organizes paper results by seven paper figures and separates raw source CSVs, normalized metric rows, summary CSVs, metric definitions, and validation manifests.

## Repository Layout

```text
loci_refactored/
  include/                 C++ headers
  src/                     LOCI/LBC and baseline implementations
  bench/                   benchmark driver source
  scripts/                 experiment, aggregation, plotting, and TraceProbe scripts
  configs/                 paper-full, quick, scheme, and dataset configs
  third_party/             vendored dependencies and their licenses
  data/processed/          processed one-dimensional real traces
  artifact_results_sp/     canonical normalized artifact result layer
```

`table1` is a dataset profile, not an independent experiment. `table2_summary.csv` is derived from Fig.7 AUC metrics and Fig.8 cost metrics, not an independent benchmark group.

Artifact rerun scripts use the canonical configs under `artifact_results_sp/configs/`. Root `configs/` files are retained for general development and compatibility.

## Requirements

- Ubuntu 22.04 recommended
- C++17 compiler: `g++ >= 10` or `clang++ >= 12`
- CMake or Make
- Python >= 3.9
- Python packages from `requirements.txt`
- OpenSSL development package if the real crypto backend is enabled

## Build

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake python3 python3-pip libssl-dev
python3 -m pip install -r requirements.txt
make clean
make BUILD=release
```

## Quick Reproduction

Quick validates pipeline and qualitative trends only. It does not reproduce paper absolute numbers.

```bash
bash artifact_results_sp/scripts/run_quick.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile quick
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile quick
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

## Full Paper Reproduction

The full profile is much slower and is intended for a Linux server.

```bash
bash artifact_results_sp/scripts/run_full.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile paper_full
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile paper_full
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

## Paper Experiment Mapping

- Fig.6 mechanism diagnostic -> `fig_mechanism`
- Fig.7 TraceProbe AUC -> `fig2_component_ablation` / `attack_eval.py`
- Fig.8 absolute cost -> `fig2_component_ablation` / `bench_wide.csv` only
- Fig.9 scale/selectivity -> `fig3_scalability_selectivity`
- Fig.10 workload robustness -> `fig4_dynamic_refresh`
- Fig.11 real-trace validation -> `fig5_real_datasets`
- Fig.12 budget sensitivity -> `fig6_tradeoff`
- `table1` dataset profile -> not an independent experiment
- `table2_summary` -> derived summary, not an independent experiment

## Metric Policy

- Paper AUC metrics only come from `attack_eval.py`.
- `max_cert_probe_auc` is derived only from `layout_shape_adv_auc`, `patch_pressure_adv_auc`, and `maintenance_cause_adv_auc`.
- Diagnostic AUC metrics are retained only as diagnostic metrics and are not included in `max_cert_probe_auc`.
- Fig.8 has no AUC metrics and reads only `fig2_component_ablation/bench_wide.csv`.
- Normalization regenerates `artifact_results_sp/raw/<profile>/` from the selected run source before writing normalized tables, preventing stale raw CSVs from being reused.

## Residual Certified-View Probe

`scripts/lcert_residual_eval.py` is an optional post-processing analysis over existing Fig.7/Fig.8 `fig2_component_ablation` traces. It quantifies residual leakage admitted by `Lcert` itself under strict certified-view features only. It does not call `bench_loci`, does not change the seven main paper result groups, and its metrics are excluded from `max_cert_probe_auc`, Fig.7 certified-probe AUC, and `table2_summary.csv`.

Standalone full-output post-processing:

```bash
python3 scripts/lcert_residual_eval.py \
  --run-root artifact_out/eval_full_sp \
  --group fig2_component_ablation \
  --out artifact_out/eval_full_sp/lcert_residual/residual_lcert_raw.csv \
  --profile paper_full \
  --seeds 0,1,2 \
  --strict-lcert
```

To include it during a rerun:

```bash
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_quick.sh
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_full.sh
```

Residual certified-view probes. To separate certification failures from leakage intentionally admitted by Lcert, we evaluate an adversary restricted to certified-view features only: certified-cell cover patterns, fanout classes, public object/update classes, public patch classes, and public maintenance classes. The adversary is not given byte-level object lengths beyond class, raw patch growth, private occupancy, raw loads, descriptor counts, model-error markers, or private maintenance causes. These probes measure residual leakage of the certified view itself, not violations of the LOCI transcript discipline. LOCI matches Sim-Lcert under the same feature restriction, indicating that the remaining signal is declared certified leakage rather than uncertified learned-layout state.

We do not claim to hide all order-like relations implied by repeated range covers. Such relations are part of certified cover leakage.

## Data

Raw original datasets are not redistributed. Processed traces are included under `data/processed/`; checksums are in `data/sha256_manifest.txt`.

Fig.11 real-trace validation and Fig.6 real mechanism diagnostic require processed traces. The paper experiments use the first 200,000 rows of each processed real trace unless otherwise specified.

## Server Rerun

For Alibaba Cloud Ubuntu reruns, follow `artifact_results_sp/docs/server_rerun_guide.md`.
