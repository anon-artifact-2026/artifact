# Artifact Claims

| Claim | Figure | Summary | Raw | Metric | Source |
|---|---|---|---|---|---|
| Naive learned layouts expose high certified-probe AUC. | Fig.7 | `summaries/fig7_attack_auc_summary.csv` | `raw/paper_full/fig7_attack_auc/` | `max_cert_probe_auc` | `attack_eval.py` only |
| LOCI closes certified-probe channels under the component ablation. | Fig.7 | `summaries/fig7_attack_auc_summary.csv` | `raw/paper_full/fig7_attack_auc/` | `layout_shape_adv_auc`, `patch_pressure_adv_auc`, `maintenance_cause_adv_auc` | `attack_eval.py` only |
| LOCI uses smaller responses than GlobalPad under the canonical synthetic setting. | Fig.8 | `summaries/fig8_absolute_cost_summary.csv` | `raw/paper_full/fig8_absolute_cost/` | `response_mib` | `bench_wide.csv` only |
| LOCI cost scales smoothly with data size and selectivity. | Fig.9 | `summaries/fig9_scale_selectivity_summary.csv` | `raw/paper_full/fig9_scale_select/` | `search_latency_ms`, `response_mib` | `bench_wide.csv` only |
| LOCI remains robust under dynamic workloads. | Fig.10 | `summaries/fig10_workload_robustness_summary.csv` | `raw/paper_full/fig10_workload/` | `max_cert_probe_auc` | `attack_eval.py` only |
| LOCI remains near the certified baseline on real traces. | Fig.11 | `summaries/fig11_real_trace_summary.csv` | `raw/paper_full/fig11_real_trace/` | `max_cert_probe_auc`, `response_mib` | `attack_eval.py` + `bench_wide.csv` |
| Certified budgets change efficiency points but not the LOCI-Full leakage boundary. | Fig.12 | `summaries/fig12_budget_sensitivity_summary.csv` | `raw/paper_full/fig12_budget/` | `max_cert_probe_auc`, `response_mib`, `server_storage_mib` | `attack_eval.py` + `bench_wide.csv` |
| Residual certified-view probes quantify leakage admitted by Lcert itself. | Appendix/residual probe | `summaries/residual_lcert_probe_summary.csv` | `raw/paper_full/residual_lcert_probe/` | `density_lcert_adv_auc`, `hotspot_lcert_adv_auc`, `adjacency_lcert_adv_auc` | `lcert_residual_eval.py` post-processing only |

`table2_summary.csv` is derived from Fig.7 and Fig.8 only. It is not an independent benchmark group.

The residual Lcert probe is not an eighth benchmark group and is not included
in `max_cert_probe_auc`, Fig.7 certified-probe AUC, or `table2_summary.csv`.
It compares LOCI restricted to certified-view features with Sim-Lcert under the
same feature restriction. Non-random density, hotspot, or adjacency AUC is
reported as declared certified-view leakage, not as a violation of LOCI's
certified transcript discipline.
