# Artifact Evaluation Guide

## Artifact Claims

This artifact supports the LOCI paper evaluation claims: naive learned layouts leak certified-probe signals; certification, padding, and public refresh close those channels; LOCI remains close to the certified leakage baseline across synthetic, dynamic, real-trace, and budget settings; and Table 2 is derived from Fig.7 and Fig.8 rather than being an independent benchmark.

## Hardware and Software Requirements

- Ubuntu 22.04 recommended
- `g++ >= 10` or `clang++ >= 12`
- `make` or `cmake`
- Python >= 3.9
- Python packages in `requirements.txt`
- `libssl-dev` if running the real crypto backend

## Quick Start

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake python3 python3-pip libssl-dev tmux htop
python3 -m pip install -r requirements.txt
make clean
make BUILD=release
bash artifact_results_sp/scripts/run_quick.sh
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

Quick is a small profile for pipeline and trend validation only. It should not replace paper-full numbers.
Artifact rerun scripts use canonical configs from `artifact_results_sp/configs/`.

## Full Reproduction

```bash
bash artifact_results_sp/scripts/run_full.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile paper_full
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile paper_full
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

The checked-in `paper_full` summaries may come from archived 3-seed full outputs normalized into `artifact_results_sp/`. `run_full.sh` can recompute the full profile from scratch.
During normalization, `artifact_results_sp/raw/<profile>/` is cleared and regenerated from the selected run source before summaries and manifests are written.

Optional residual certified-view post-processing can be enabled with `RUN_RESIDUAL_LCERT=1`. It runs after `fig2_component_ablation` and writes `artifact_out/<profile>/lcert_residual/residual_lcert_raw.csv` before normalization copies it to `artifact_results_sp/raw/<profile>/residual_lcert_probe/`.

## Expected Runtime

- Quick profile: minutes to tens of minutes.
- Full profile: potentially many hours on a server.
- Fig.7/Fig.8 canonical 1M/10k is the highest-priority full run.
- Fig.10 workload robustness can be expensive.

## Expected Qualitative Results

- Fig.7: naive learned layouts show high certified-probe AUC; LOCI-Full, GlobalPad, and Sim-L_cert should be close to 0.50.
- Fig.8: LOCI response is much smaller than GlobalPad under the canonical synthetic setting.
- Fig.9: latency and response size grow smoothly with scale/selectivity.
- Fig.10: LOCI-Full remains near certified baseline across dynamic workloads.
- Fig.11: LOCI-Full remains near certified-probe random baseline on processed real traces.
- Fig.12: budget changes efficiency points but should not change LOCI-Full's certified leakage boundary.

## Directory Map

`artifact_results_sp/raw/` contains copied source CSVs regenerated per profile, `normalized/` contains `master_long.csv`, `summaries/` contains paper-facing CSVs, `manifests/` contains source maps and validation output, and `docs/` contains policy and reproduction notes.

## Metric Definitions

Paper AUC metrics come only from `attack_eval.py`. `max_cert_probe_auc` is the max of `layout_shape_adv_auc`, `patch_pressure_adv_auc`, and `maintenance_cause_adv_auc`. Diagnostic region/hotspot AUCs are preserved for transparency but excluded from `max_cert_probe_auc`. Cost metrics come from benchmark CSVs.

Residual certified-view probes quantify leakage admitted by Lcert. They are not included in `max_cert_probe_auc` and do not represent violations of LOCI's certified transcript discipline. The expected comparison is LOCI restricted to Lcert features versus Sim-Lcert under the same feature restriction. Adjacency/order-like relations implied by repeated certified range covers are reported as certified cover leakage.

## Known Limitations

This is a research prototype, not a production encrypted-search system. Raw original datasets are not redistributed; processed traces are included under `data/processed/`. `artifact_out/` is temporary generated output and is not part of the open artifact release.
