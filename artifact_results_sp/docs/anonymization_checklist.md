# Anonymization Checklist

Status after cleanup:

- No local Windows absolute path should appear in committed documentation, configs, manifests, or artifact scripts.
- No local username should appear in committed documentation, configs, manifests, or artifact scripts.
- No school name is required by the artifact.
- No email address is required by the artifact.
- Upstream third-party license/source files may contain their original maintainer contact lines; these are not LOCI author identifiers.
- No `.git` history is required for artifact use.
- Raw original datasets are not redistributed.
- Processed traces are retained under `data/processed/` as artifact inputs.
- Generated build outputs and temporary benchmark outputs are ignored or removed from the release tree.

The validation and grep checks should be rerun before packaging a public release.
