cmake_minimum_required(VERSION 3.12)
project(loci_refactored LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(OpenSSL REQUIRED)

add_library(loci
    src/rank_guide.cpp
    src/lbc.cpp
    src/loci.cpp
    src/tree_range.cpp
    src/cell_baseline.cpp
)
target_include_directories(loci PUBLIC include third_party/PGM-index-master/include)
target_link_libraries(loci PUBLIC OpenSSL::Crypto)
target_compile_options(loci PRIVATE -Wall -Wextra -O2)

add_executable(bench_loci bench/bench_loci.cpp)
target_link_libraries(bench_loci PRIVATE loci)
target_compile_options(bench_loci PRIVATE -Wall -Wextra -O2)
