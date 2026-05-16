# Artifact Results Manifest

## Directories

- `configs/`: copied evaluation configs used by artifact profiles.
- `scripts/`: rerun, normalization, summary, and validation scripts.
- `raw/paper_full/`: canonical copied source CSVs for paper-full figures.
- `raw/quick/`: canonical copied source CSVs for quick profile figures.
- `normalized/`: provenance-rich normalized metric tables.
- `summaries/`: paper-facing summary CSVs.
- `manifests/`: source maps, metric definitions, run manifest, checksums, validation report.
- `docs/`: claim mapping, metric policy, dataset documentation, runtime notes, anonymization checklist, server rerun guide.

## Profiles

- `paper_full`: paper-scale profile with seeds `0,1,2`.
- `quick`: small profile with seed `0`, intended for pipeline and trend validation only.

## Figure Groups

| Paper figure | Code group | Role |
|---|---|---|
| `fig6_mechanism` | `fig_mechanism` | diagnostic, not the main security claim |
| `fig7_attack_auc` | `fig2_component_ablation` | main certified-probe attack AUC |
| `fig8_absolute_cost` | `fig2_component_ablation` | canonical synthetic absolute cost |
| `fig9_scale_select` | `fig3_scalability_selectivity` | scale and selectivity cost |
| `fig10_workload` | `fig4_dynamic_refresh` | dynamic workload security robustness |
| `fig11_real_trace` | `fig5_real_datasets` | real-trace security and cost |
| `fig12_budget` | `fig6_tradeoff` | certified-budget sensitivity |
| `table2_summary` | `derived` | derived from Fig.7 and Fig.8 only |

## Normalized Schema

`normalized/master_long.csv` uses:

```text
paper_fig, benchmark_group, profile, source_csv, source_archive_or_run_id,
source_row_id, config_file, config_hash, git_commit_if_available, host, os,
cpu, seed, dataset, workload, scheme, variant, N, ops, query_ratio,
update_ratio, budget, selectivity, timeout_s, metric_name, metric_value,
metric_unit, metric_source, evaluator, auc_mode, is_paper_metric, notes
```

Every summary row includes `source_csv` and `source_row_id` for provenance.
