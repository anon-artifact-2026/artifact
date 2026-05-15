CXX ?= g++
BUILD ?= release
COMMON_CXXFLAGS := -std=c++17 -Wall -Wextra -Iinclude -Ithird_party/PGM-index-master/include
ifeq ($(BUILD),debug)
	OPT_CXXFLAGS := -O0 -g -fno-inline
else ifeq ($(BUILD),release)
	OPT_CXXFLAGS := -O3 -DNDEBUG
else
	$(error unknown BUILD=$(BUILD); use BUILD=release or BUILD=debug)
endif
CXXFLAGS ?= $(COMMON_CXXFLAGS) $(OPT_CXXFLAGS)
LDLIBS ?= -lcrypto
OBJS = build/rank_guide.o build/lbc.o build/loci.o build/tree_range.o build/cell_baseline.o build/bench_loci.o
HEADERS = $(wildcard include/loci/*.hpp)

ifeq ($(OS),Windows_NT)
	EXEEXT := .exe
	RUN_BENCH = bench_loci.exe
	MKDIR_P = if not exist build mkdir build
	RM_RF = if exist build rmdir /S /Q build & if exist bench_loci.exe del /Q bench_loci.exe & del /Q *.csv 2>NUL
else
	EXEEXT :=
	RUN_BENCH = ./bench_loci
	MKDIR_P = mkdir -p build
	RM_RF = rm -rf build bench_loci *.csv
endif

all: bench_loci$(EXEEXT)

build:
	$(MKDIR_P)

build/rank_guide.o: src/rank_guide.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/lbc.o: src/lbc.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/loci.o: src/loci.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/tree_range.o: src/tree_range.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/cell_baseline.o: src/cell_baseline.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

build/bench_loci.o: bench/bench_loci.cpp $(HEADERS) | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

bench_loci$(EXEEXT): $(OBJS)
	$(CXX) $(OBJS) $(LDLIBS) -o $@

check: bench_loci$(EXEEXT)
	$(RUN_BENCH) --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant full
	$(RUN_BENCH) --N 4 --ops 3 --U 1 --B 4 --theta 2 --dist uniform --variant full
	$(RUN_BENCH) --N 10 --ops 10 --U 8 --B 4 --theta 2 --dist skew --variant full
	$(RUN_BENCH) --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nopad
	$(RUN_BENCH) --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nocert
	$(RUN_BENCH) --N 3000 --ops 500 --B 512 --theta 32 --dist skew --variant nopublicrefresh
	$(RUN_BENCH) --scheme pgm --variant naive --N 3000 --ops 500 --B 512 --theta 32 --dist skew
	$(RUN_BENCH) --scheme pgm --variant globalpad --N 1000 --ops 100 --B 128 --theta 16 --dist skew
	$(RUN_BENCH) --scheme fixedcell --variant bitmap --N 1000 --ops 100 --B 128 --theta 16 --dist skew
	$(RUN_BENCH) --N 128 --ops 100 --B 64 --theta 8 --dist skew --variant full --crypto real
	$(RUN_BENCH) --scheme pgm --variant naive --N 1000 --ops 300 --B 128 --theta 64 --dist skew --workload hotspot
	$(RUN_BENCH) --scheme fbdsse --N 1000 --ops 300 --dist skew --workload hotspot --crypto real
	$(RUN_BENCH) --attack-suite --N 300 --ops 120 --B 64 --theta 16 --dist skew

clean:
	$(RM_RF)
