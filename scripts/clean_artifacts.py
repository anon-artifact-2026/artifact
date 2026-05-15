#!/usr/bin/env python3
"""Clean generated artifact outputs.

By default this removes only known generated benchmark output directories under
artifact_out while leaving raw datasets and source files untouched.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


KNOWN_PREFIXES = (
    "formal_attack_",
    "formal_fbdsse_",
    "formal_noproto_",
    "formal_nyc_",
    "formal_",
    "synthetic_",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("artifact_out"))
    parser.add_argument("--all", action="store_true", help="Remove the entire artifact_out directory.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    cwd = Path.cwd().resolve()
    if root != cwd / "artifact_out" and cwd not in root.parents:
        raise SystemExit(f"refusing to clean outside workspace: {root}")
    if not root.exists():
        return 0

    targets = []
    if args.all:
        targets = [root]
    else:
        for path in root.iterdir():
            if path.is_dir() and (path.name == "formal" or path.name == "formal_smoke" or path.name.startswith(KNOWN_PREFIXES)):
                targets.append(path)

    for target in targets:
        print(f"remove {target}")
        if not args.dry_run:
            shutil.rmtree(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
