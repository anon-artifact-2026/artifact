#!/usr/bin/env bash
set -euo pipefail

make

./bench_loci --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant full
./bench_loci --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nocert
./bench_loci --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nopad
./bench_loci --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant noproto
./bench_loci --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nopublicrefresh
./bench_loci --scheme pgm --variant naive --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
./bench_loci --scheme pgm --variant globalpad --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
./bench_loci --scheme fixedcell --variant bitmap --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
./bench_loci --scheme fbdsse --variant treecover --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot

python3 scripts/run_config.py configs/synthetic_smoke.yaml --skip-build --clean
python3 scripts/run_formal_suite.py --config configs/formal_smoke.yaml --skip-build
