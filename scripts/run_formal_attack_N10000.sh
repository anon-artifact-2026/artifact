#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

OUT=artifact_out/formal/core_attack
rm -rf "$OUT"
mkdir -p "$OUT/traces" "$OUT/logs" "$OUT/figure_groups"

COMMON="--N 10000 --ops 3000 --U 1048576 --B 256 --theta 32 --dist skew --workload hotspot --crypto mock --csv $OUT/results.csv --trace-dir $OUT/traces"

./bench_loci --scheme pgm --variant naive $COMMON | tee "$OUT/logs/pgm_naive.log"
./bench_loci --scheme pgm --variant globalpad $COMMON | tee "$OUT/logs/pgm_globalpad.log"
./bench_loci --scheme fixedcell --variant bitmap $COMMON | tee "$OUT/logs/fixedcell_bitmap.log"

./bench_loci --scheme loci --variant full $COMMON | tee "$OUT/logs/loci_full.log"
./bench_loci --scheme loci --variant nocert $COMMON | tee "$OUT/logs/loci_nocert.log"
./bench_loci --scheme loci --variant nopad $COMMON | tee "$OUT/logs/loci_nopad.log"
./bench_loci --scheme loci --variant nopublicrefresh $COMMON | tee "$OUT/logs/loci_nopublicrefresh.log"

python3 scripts/attack_eval.py "$OUT/traces" --csv "$OUT/attack_eval.csv"
python3 scripts/plot_figures.py "$OUT/results.csv" --out-dir "$OUT/figure_groups"

echo "Done: $OUT"
