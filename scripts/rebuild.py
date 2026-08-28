#!/usr/bin/env python3
"""Rebuild aggregate outputs from reviewed dataset governance records."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .curation import capture_curation, write_manifest
    from .generate import (
        catalogue_index,
        catalogue_records,
        load_json,
        repository_statistics,
        update_readme,
        write_cerif,
        write_re3data,
    )
else:  # Direct execution: python scripts/rebuild.py
    from curation import capture_curation, write_manifest
    from generate import (
        catalogue_index,
        catalogue_records,
        load_json,
        repository_statistics,
        update_readme,
        write_cerif,
        write_re3data,
    )


ROOT = Path(__file__).resolve().parents[1]


def reviewed_records(dataset_dir: Path) -> list[dict]:
    """Load, identify, and sort reviewed PN dataset records."""
    records = []
    seen = set()
    for path in sorted(dataset_dir.glob("PN*.json")):
        record = load_json(path)
        dataset_id = record.get("datasetId")
        if path.stem != dataset_id:
            raise ValueError(
                f"{path.name}: filename must match datasetId {dataset_id!r}"
            )
        if dataset_id in seen:
            raise ValueError(f"Duplicate datasetId: {dataset_id}")
        seen.add(dataset_id)
        records.append(record)
    if not records:
        raise ValueError(f"No PN*.json records found in {dataset_dir}")
    return records


def rebuild(output: Path, catalogue: Path) -> int:
    """Validate reviewed records and rebuild README and XML aggregate exports."""
    if __package__:
        from .validate import validate_records
    else:
        from validate import validate_records

    count = validate_records(output)
    records = reviewed_records(output / "datasets")
    if count != len(records):
        raise ValueError(
            f"Validated {count} records but loaded {len(records)} reviewed records"
        )

    baseline, _ = catalogue_records(catalogue)
    capture_curation(baseline, records, output / "curation")
    stats = repository_statistics(records, catalogue)
    _, super_record = catalogue_index(catalogue)
    updated = super_record.get("dateModified") or max(
        (
            version.get("lastUpdated", "")
            for dataset in records
            for version in dataset["versions"]
        ),
        default="",
    )
    write_cerif(records, output / "exports" / "openaire-cerif.xml", updated)
    repository = load_json(output / "repository.json")
    write_re3data(repository, len(records), updated, output / "exports" / "re3data.xml")
    update_readme(output / "README.md", records, stats)
    write_manifest(output / "datasets", output / "curation" / "manifest.json")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild README and XML exports from reviewed datasets/PN*.json records"
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        required=True,
        help="DataCatalogue checkout used for curation comparison and summary statistics",
    )
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()

    try:
        count = rebuild(args.output.resolve(), args.catalogue.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Rebuilt README and XML exports from {count} reviewed dataset records")


if __name__ == "__main__":
    main()
