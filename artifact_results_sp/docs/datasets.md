# Datasets

Raw original datasets are not redistributed. This artifact includes processed one-dimensional traces under `data/processed/`.

| Dataset | Processed file | Rows available | Rows used in paper full | Projection | Usage |
|---|---|---:|---:|---|---|
| NYC Taxi | `data/processed/nyc/nyc_time.csv` | 1,000,000 | 200,000 | timestamp/value projection | Fig.11 real-trace validation; Fig.6 real mechanism diagnostic |
| Gowalla | `data/processed/gowalla/gowalla_location.csv` | 1,000,000 | 200,000 | location/value projection | Fig.11 real-trace validation; Fig.6 real mechanism diagnostic |
| GeoLife | `data/processed/geolife/geolife_lat.csv` | 1,000,000 | 200,000 | latitude/value projection | Fig.11 real-trace validation; Fig.6 real mechanism diagnostic |

Additional processed projections may be present under `data/processed/` and are retained for reproducibility. Checksums for processed CSVs are in `data/sha256_manifest.txt`.
