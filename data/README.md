# Data

This artifact includes processed one-dimensional traces used by the paper experiments.

Raw original datasets are not redistributed in this repository. Processed traces are stored under `data/processed/`.

Fig.11 real-trace validation and Fig.6 real mechanism diagnostic require these processed traces. The paper experiments use the first 200,000 rows of each processed real trace unless otherwise specified.

If users only want to run the quick profile, processed subsets are sufficient. The quick profile uses smaller `N` and `ops` values and reads from `data/processed/` by default.

Checksums for processed CSV files are stored in `data/sha256_manifest.txt`.
