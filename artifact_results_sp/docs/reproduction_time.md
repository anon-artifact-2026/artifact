# Reproduction Time

Expected runtime depends on CPU, storage, compiler flags, and whether real or mock crypto is selected.

- Quick profile: minutes to tens of minutes.
- Full profile: potentially many hours on a server.
- Fig.7/Fig.8 canonical 1M/10k is the most important full run.
- Fig.10 workload robustness can be expensive because it spans multiple workloads and schemes.
- The residual Lcert probe is post-processing over the existing Fig.7/Fig.8
  `fig2_component_ablation` traces and `bench_wide.csv`. It does not call
  `bench_loci` and should be much cheaper than a benchmark rerun.

Do not treat quick absolute numbers as paper numbers. Quick results are for pipeline and trend validation only.

Optional residual certified-view probe:

```bash
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_quick.sh
RUN_RESIDUAL_LCERT=1 bash artifact_results_sp/scripts/run_full.sh
```

For an already completed full run, run the post-processing step directly:

```bash
python3 scripts/lcert_residual_eval.py \
  --run-root artifact_out/eval_full_sp \
  --group fig2_component_ablation \
  --out artifact_out/eval_full_sp/lcert_residual/residual_lcert_raw.csv \
  --profile paper_full \
  --seeds 0,1,2 \
  --strict-lcert
```
