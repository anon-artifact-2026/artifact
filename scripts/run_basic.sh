#!/usr/bin/env bash
set -euo pipefail
make
./bench_loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant full --csv results_basic.csv
./bench_loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nocert --csv results_basic.csv
./bench_loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant noproto --csv results_basic.csv
./bench_loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nopad --csv results_basic.csv
./bench_loci --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nopublicrefresh --csv results_basic.csv
./bench_loci --scheme pgm --variant naive --N 3000 --ops 500 --B 512 --theta 32 --dist skew --csv results_basic.csv
./bench_loci --scheme pgm --variant globalpad --N 3000 --ops 500 --B 512 --theta 32 --dist skew --csv results_basic.csv
./bench_loci --scheme fixedcell --variant bitmap --N 3000 --ops 500 --B 512 --theta 32 --dist skew --csv results_basic.csv
./bench_loci --scheme fbdsse --variant treecover --N 3000 --ops 500 --dist skew --csv results_basic.csv
./bench_loci --attack-suite --N 1000 --ops 300 --B 128 --theta 64 --dist skew --crypto real --csv attack_suite.csv
