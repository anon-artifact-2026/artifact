# Alibaba Cloud Ubuntu Rerun Guide

## 1. Upload Project

```bash
tar -czf loci_refactored_release.tar.gz loci_refactored/
scp loci_refactored_release.tar.gz user@server:/data/
```

## 2. Unpack

```bash
cd /data
tar -xzf loci_refactored_release.tar.gz
cd loci_refactored
```

## 3. Install Dependencies

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake python3 python3-pip libssl-dev tmux htop
python3 -m pip install -r requirements.txt
```

Artifact rerun scripts use canonical configs under `artifact_results_sp/configs/`.

## 4. Build

```bash
make clean
make BUILD=release
```

## 5. Verify Data

```bash
sha256sum -c data/sha256_manifest.txt
```

## 6. Run Quick

```bash
bash artifact_results_sp/scripts/run_quick.sh
python3 artifact_results_sp/scripts/normalize_results.py --profile quick
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile quick
python3 artifact_results_sp/scripts/validate_artifact_results.py
```

## 7. Run Full in tmux

```bash
tmux new -s loci_full
bash artifact_results_sp/scripts/run_full.sh 2>&1 | tee artifact_results_sp/full_run.log
```

## 8. After Full Run

```bash
python3 artifact_results_sp/scripts/normalize_results.py --profile paper_full
python3 artifact_results_sp/scripts/make_paper_summaries.py --profile paper_full
python3 artifact_results_sp/scripts/validate_artifact_results.py | tee artifact_results_sp/manifests/validation_report.txt
```

## 9. Package Results

```bash
tar -czf artifact_results_sp_after_full.tar.gz artifact_results_sp/
```

## Notes

- Full run is expected to take much longer than quick.
- Quick results should not replace paper_full numbers.
- If full run is interrupted, keep logs and rerun missing groups if scripts support it.
- `artifact_out/` is a temporary generated-output directory. Canonical result CSVs are copied into `artifact_results_sp/raw/` during normalization.
- Normalization clears and regenerates `artifact_results_sp/raw/<profile>/` from the selected run source so stale raw CSVs are not reused.
- `artifact_results_sp/summaries/table2_summary.csv` is derived from Fig.7 attack metrics and Fig.8 cost metrics; it is not an independent benchmark output.
