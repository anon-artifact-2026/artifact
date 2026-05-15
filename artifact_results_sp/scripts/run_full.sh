#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"
CFG="artifact_results_sp/configs/eval_full_sp.yaml"
RUN_ROOT="artifact_out/eval_full_sp"
LOG_DIR="artifact_results_sp/manifests"
LOG_FILE="$LOG_DIR/run_full_commands.txt"

mkdir -p "$LOG_DIR" artifact_results_sp/raw/paper_full
: > "$LOG_FILE"

log() {
  printf '[%s] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG_FILE"
}

run_cmd() {
  log "+ $*"
  "$@"
}

log "Starting paper_full run. RUN_ROOT=$RUN_ROOT is a temporary generated-output directory; normalize_results.py copies canonical raw CSVs into artifact_results_sp/raw/paper_full."
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig2 --seeds 0,1,2
if [[ "${RUN_RESIDUAL_LCERT:-0}" == "1" ]]; then
  run_cmd "$PYTHON_BIN" scripts/lcert_residual_eval.py --run-root "$RUN_ROOT" --group fig2_component_ablation --out "$RUN_ROOT/lcert_residual/residual_lcert_raw.csv" --profile paper_full --seeds 0,1,2 --strict-lcert
fi
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig3 --seeds 0,1,2
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig4 --seeds 0,1,2
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig5 --seeds 0,1,2
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig6 --seeds 0,1,2
run_cmd "$PYTHON_BIN" scripts/run_loci_eval.py --config "$CFG" --out "$RUN_ROOT" --group fig_mechanism --seeds 0,1,2
run_cmd "$PYTHON_BIN" scripts/aggregate_loci_eval.py --out "$RUN_ROOT" --skip-legacy-table2

run_cmd "$PYTHON_BIN" artifact_results_sp/scripts/normalize_results.py --profile paper_full --artifact-root artifact_results_sp --paper-root "$RUN_ROOT" --paper-config "$CFG"
run_cmd "$PYTHON_BIN" artifact_results_sp/scripts/make_paper_summaries.py --profile paper_full --artifact-root artifact_results_sp
run_cmd "$PYTHON_BIN" artifact_results_sp/scripts/validate_artifact_results.py --profile paper_full --artifact-root artifact_results_sp
log "paper_full run completed."
