# LOCI Artifact Results SP

`paper_full` is the paper main-result profile. `quick` is the fast validation profile.

The checked-in `paper_full` results may come from archived full runs normalized into this directory. `artifact_results_sp/scripts/run_full.sh` can recompute the full profile from scratch. The `quick` profile does not reproduce paper absolute numbers; it only validates the pipeline and qualitative trends.

Artifact rerun scripts use the canonical configs under `artifact_results_sp/configs/`. During normalization, `raw/<profile>/` is cleared and regenerated from the selected run source before manifests are written.

Validation command:

```bash
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

## Layout

```text
artifact_results_sp/
  configs/       canonical artifact experiment configs
  scripts/       rerun, normalize, summarize, and validate scripts
  raw/           copied source CSVs by profile and paper figure
  normalized/    master_long.csv and master_wide_optional.csv
  summaries/     paper-facing summary CSVs
  manifests/     figure map, metric definitions, source hashes, validation report
  docs/          artifact claims, metric policy, datasets, rerun guides
```

## Profiles

- `paper_full`: seeds `0,1,2`, paper-scale settings.
- `quick`: seed `0`, small `N` and `ops`, pipeline/trend verification only.

## Paper Figure Mapping and Scale

| Paper figure | Benchmark group | Dataset/scale | Ops | Seeds | Metric source |
|---|---|---:|---:|---|---|
| Fig.6 mechanism | `fig_mechanism` | synthetic 200k; NYC/Gowalla/GeoLife 200k each | 2k | 0,1,2 | mechanism CSV |
| Fig.7 attack AUC | `fig2_component_ablation` | synthetic skew-hotspot-drift mix 1,000,000 | 10k | 0,1,2 | `attack_eval.py` only |
| Fig.8 absolute cost | `fig2_component_ablation` | same canonical synthetic 1,000,000 | 10k | 0,1,2 | `bench_wide.csv` only |
| Fig.9 scale/selectivity | `fig3_scalability_selectivity` | scale 10k/25k/50k/100k/200k; selectivity at 100k | 1k | 0,1,2 | `bench_wide.csv` only |
| Fig.10 workload robustness | `fig4_dynamic_refresh` | synthetic workloads, 500,000 | 5k | 0,1,2 | `attack_eval.py` only |
| Fig.11 real trace | `fig5_real_datasets` | NYC/Gowalla/GeoLife 200k each | 2k | 0,1,2 | `attack_eval.py` + `bench_wide.csv` |
| Fig.12 budget sensitivity | `fig6_tradeoff` | synthetic hotspot 100,000, budgets 32/64/128/256 | 1k | 0,1,2 | `attack_eval.py` + `bench_wide.csv` |

`table1` is a dataset profile and is not an independent experiment. `table2_summary.csv` is derived from Fig.7 attack metrics and Fig.8 cost metrics; it is not an independent benchmark group.

## Commands

Run quick:

```bash
bash artifact_results_sp/scripts/run_quick.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile quick
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile quick
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

Run full:

```bash
bash artifact_results_sp/scripts/run_full.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile paper_full
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile paper_full
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

## Metric Rules

- Certified-probe AUC metrics come only from `attack_eval.py`.
- `max_cert_probe_auc` is derived only from `layout_shape_adv_auc`, `patch_pressure_adv_auc`, and `maintenance_cause_adv_auc`.
- Diagnostic region/hotspot AUCs are preserved as `diagnostic_region_auc` and `diagnostic_hotspot_auc` with `is_paper_metric=false`.
- Fig.8 absolute cost reads only `fig2_component_ablation/bench_wide.csv`.

## Residual Certified-View Probe

`residual_lcert_probe` is an optional post-processing analysis over the
canonical `fig2_component_ablation` run. It is not an eighth benchmark group
and is excluded from `max_cert_probe_auc`, Fig.7 certified-probe AUC, and
`table2_summary.csv`.

Enable it during a rerun:

```bash
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_quick.sh
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_full.sh
```

Or run it after an existing full run:

```bash
python3 scripts/lcert_residual_eval.py \
  --run-root artifact_out/eval_full_sp \
  --group fig2_component_ablation \
  --out artifact_out/eval_full_sp/lcert_residual/residual_lcert_raw.csv \
  --profile paper_full \
  --seeds 0,1,2 \
  --strict-lcert
```

Normalization copies the raw CSV to
`raw/<profile>/residual_lcert_probe/residual_lcert_raw.csv`, and summary
generation writes `summaries/residual_lcert_probe_summary.csv`. The expected
comparison is LOCI restricted to Lcert-only features versus Sim-Lcert under the
same feature restriction. Adjacency or order-like signal from repeated range
covers is treated as certified cover leakage.
