#!/usr/bin/env python3
"""Save reviewed dataset fields as durable curation patches."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .curation import capture_curation, write_manifest
    from .generate import catalogue_records
    from .rebuild import reviewed_records
    from .validate import validate_records
else:
    from curation import capture_curation, write_manifest
    from generate import catalogue_records
    from rebuild import reviewed_records
    from validate import validate_records


ROOT = Path(__file__).resolve().parents[1]


def capture(output: Path, catalogue: Path) -> int:
    validate_records(output)
    reviewed = reviewed_records(output / "datasets")
    baseline, _ = catalogue_records(catalogue)
    count = capture_curation(baseline, reviewed, output / "curation")
    write_manifest(output / "datasets", output / "curation" / "manifest.json")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture reviewed DUC fields before regenerating dataset records"
    )
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        count = capture(args.output.resolve(), args.catalogue.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Saved curation patches for {count} dataset records and updated manifest")


if __name__ == "__main__":
    main()
