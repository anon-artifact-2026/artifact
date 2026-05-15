$ErrorActionPreference = "Stop"

mingw32-make

.\bench_loci.exe --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant full
.\bench_loci.exe --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nocert
.\bench_loci.exe --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nopad
.\bench_loci.exe --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant noproto
.\bench_loci.exe --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot --variant nopublicrefresh
.\bench_loci.exe --scheme pgm --variant naive --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
.\bench_loci.exe --scheme pgm --variant globalpad --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
.\bench_loci.exe --scheme fixedcell --variant bitmap --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot
.\bench_loci.exe --scheme fbdsse --variant treecover --N 200 --ops 60 --B 64 --theta 8 --dist skew --workload hotspot

python scripts\run_config.py configs\synthetic_smoke.yaml --skip-build --clean
python scripts\run_formal_suite.py --config configs\formal_smoke.yaml --skip-build
