#!/usr/bin/env bash
set -euo pipefail

N="${N:-10000}"
OPS="${OPS:-1000}"
B="${B:-512}"
THETA="${THETA:-32}"
DIST="${DIST:-skew}"
WORKLOAD="${WORKLOAD:-hotspot}"
CRYPTO="${CRYPTO:-mock}"
OUT_DIR="${OUT_DIR:-artifact_out}"

make

mkdir -p "$OUT_DIR"
RESULTS="$OUT_DIR/results.csv"
TRACE_DIR="$OUT_DIR/traces"
ATTACK_CSV="$OUT_DIR/attack_eval.csv"
FIGURE_DIR="$OUT_DIR/figure_groups"

rm -f "$RESULTS" "$ATTACK_CSV"
rm -rf "$TRACE_DIR" "$FIGURE_DIR"

cases=(
  "loci full"
  "loci nocert"
  "loci nopad"
  "loci noproto"
  "loci nopublicrefresh"
  "pgm naive"
  "pgm globalpad"
  "fixedcell bitmap"
  "fbdsse treecover"
)

for entry in "${cases[@]}"; do
  read -r scheme variant <<< "$entry"
  ./bench_loci --scheme "$scheme" --variant "$variant" \
    --N "$N" --ops "$OPS" --B "$B" --theta "$THETA" \
    --dist "$DIST" --workload "$WORKLOAD" --crypto "$CRYPTO" \
    --csv "$RESULTS" --trace-dir "$TRACE_DIR"
done

python3 scripts/attack_eval.py "$TRACE_DIR" --csv "$ATTACK_CSV"
python3 scripts/plot_figures.py "$RESULTS" --out-dir "$FIGURE_DIR" --metric avg_query_ms

echo "Wrote $RESULTS"
echo "Wrote $TRACE_DIR"
echo "Wrote $ATTACK_CSV"
echo "Wrote $FIGURE_DIR"
