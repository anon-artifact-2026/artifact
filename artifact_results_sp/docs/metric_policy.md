# Metric Policy

Paper AUC metrics are sourced only from `attack_eval.py`. Cost metrics are sourced only from benchmark CSVs such as `bench_wide.csv`.

## Certified-Probe AUC Metrics

- `layout_shape_auc`: raw AUC for the layout-shape probe, sourced from `attack_eval.py` `layout_class_auc` or legacy `shape_auc`.
- `patch_pressure_auc`: raw AUC for the patch-pressure probe, sourced from `attack_eval.py` `log_growth_auc` or `patch_pressure_auc`.
- `maintenance_cause_auc`: raw AUC for the maintenance-cause probe, sourced from `attack_eval.py` `maintenance_auc` or `maintenance_cause_auc`.
- `layout_shape_adv_auc = max(layout_shape_auc, 1 - layout_shape_auc)`.
- `patch_pressure_adv_auc = max(patch_pressure_auc, 1 - patch_pressure_auc)`.
- `maintenance_cause_adv_auc = max(maintenance_cause_auc, 1 - maintenance_cause_auc)`.
- `max_cert_probe_auc = max(layout_shape_adv_auc, patch_pressure_adv_auc, maintenance_cause_adv_auc)`.

`max_cert_probe_auc` must not use `eval_region_auc`, `region_auc`, `hotspot_auc`, or other diagnostic AUCs.

## Diagnostic AUC Metrics

- `diagnostic_region_auc`: preserved dense-region diagnostic AUC from `attack_eval.py`.
- `diagnostic_hotspot_auc`: preserved hotspot diagnostic AUC from `attack_eval.py`.

Diagnostic AUC metrics are preserved for transparency but are not aggregated into `max_cert_probe_auc` and are marked `is_paper_metric=false`.

## Cost Metrics

- `response_mib`: per-search response bytes converted to MiB.
- `server_storage_mib`: server-side storage bytes converted to MiB.
- `search_latency_ms`: average benchmark search latency.
- `patch_update_latency_ms`: benchmark update/patch update latency.
- `maintenance_latency_ms`: maintenance portion of the update path when available.
- `refresh_count`: public refresh event count.
- `forced_rollover_count`: forced public rollover or log refresh count when available.

Fig.8 absolute cost has no AUC metrics and reads only the canonical `fig2_component_ablation/bench_wide.csv` source copied into `raw/paper_full/fig8_absolute_cost/`.

`artifact_results_sp/summaries/table2_summary.csv` is the only paper Table 2 output. It is derived from Fig.7 attack metrics and Fig.8 cost metrics, and is not an independent benchmark group.

## Residual Certified-View Probes

`residual_lcert_probe` is an auxiliary post-processing analysis. It is sourced from `scripts/lcert_residual_eval.py`, not from `attack_eval.py`, and all residual metrics are marked `is_paper_metric=false`.

Residual metrics:

- `density_lcert_auc`, `density_lcert_adv_auc`
- `hotspot_lcert_auc`, `hotspot_lcert_adv_auc`
- `adjacency_lcert_auc`, `adjacency_lcert_adv_auc`

These metrics quantify leakage admitted by the declared certified view. They are excluded from `max_cert_probe_auc`, Fig.7 certified-probe AUC summaries, and `table2_summary.csv`.

Allowed strict-Lcert features include certified-cell cover patterns, cover/co-cover counts, query fanout class, public object/update/patch/maintenance/replacement classes, public time/epoch/refresh groups, and public class multisets. Forbidden features include byte lengths beyond public class, raw patch growth, private occupancy/state, exact load, descriptor/boundary counts, learned model-error markers, plaintext order/value, query endpoints, and labels as features.

We do not claim to hide all order-like relations implied by repeated range covers. Such relations are part of certified cover leakage.
