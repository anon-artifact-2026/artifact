param(
    [int]$N = 10000,
    [int]$Ops = 1000,
    [int]$B = 512,
    [int]$Theta = 32,
    [string]$Dist = "skew",
    [string]$Workload = "hotspot",
    [string]$Crypto = "mock",
    [string]$OutDir = "artifact_out"
)

$ErrorActionPreference = "Stop"

mingw32-make

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$results = Join-Path $OutDir "results.csv"
$traceDir = Join-Path $OutDir "traces"
$attackCsv = Join-Path $OutDir "attack_eval.csv"
$figureDir = Join-Path $OutDir "figure_groups"

if (Test-Path $results) { Remove-Item -Force -LiteralPath $results }
if (Test-Path $traceDir) { Remove-Item -Recurse -Force -LiteralPath $traceDir }
if (Test-Path $attackCsv) { Remove-Item -Force -LiteralPath $attackCsv }
if (Test-Path $figureDir) { Remove-Item -Recurse -Force -LiteralPath $figureDir }

$cases = @(
    @("--scheme", "loci", "--variant", "full"),
    @("--scheme", "loci", "--variant", "nocert"),
    @("--scheme", "loci", "--variant", "nopad"),
    @("--scheme", "loci", "--variant", "noproto"),
    @("--scheme", "loci", "--variant", "nopublicrefresh"),
    @("--scheme", "pgm", "--variant", "naive"),
    @("--scheme", "pgm", "--variant", "globalpad"),
    @("--scheme", "fixedcell", "--variant", "bitmap"),
    @("--scheme", "fbdsse", "--variant", "treecover")
)

foreach ($case in $cases) {
    .\bench_loci.exe @case --N $N --ops $Ops --B $B --theta $Theta --dist $Dist --workload $Workload --crypto $Crypto --csv $results --trace-dir $traceDir
}

python scripts\attack_eval.py $traceDir --csv $attackCsv
python scripts\plot_figures.py $results --out-dir $figureDir --metric avg_query_ms

Write-Host "Wrote $results"
Write-Host "Wrote $traceDir"
Write-Host "Wrote $attackCsv"
Write-Host "Wrote $figureDir"
