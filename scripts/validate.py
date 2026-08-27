#!/usr/bin/env python3
"""Validate generated PublicnEUro dataset records."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
DUC_KEYS = {
    "conditions", "profileId", "profileVersion", "profileName", "ducVersion",
    "creationDate", "lastUpdated", "assets", "permissionMode", "language",
}
CONDITION_KEYS = {"conditionTerm", "conditionParameter", "rule", "scope"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def main() -> None:
    schema = load(ROOT / "schema" / "dataset.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    failures = []
    files = sorted((ROOT / "datasets").glob("PN*.json"))
    for path in files:
        record = load(path)
        for error in validator.iter_errors(record):
            location = "/".join(str(value) for value in error.absolute_path)
            failures.append(f"{path.name}:{location}: {error.message}")
        for version in record.get("versions", []):
            extra = set(version.get("duc", {})) - DUC_KEYS
            if extra:
                failures.append(f"{path.name}: non-standard DUC fields: {sorted(extra)}")
            for index, condition in enumerate(version.get("duc", {}).get("conditions", [])):
                extra = set(condition) - CONDITION_KEYS
                if extra:
                    failures.append(
                        f"{path.name}: condition {index} has non-standard fields: {sorted(extra)}"
                    )
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated {len(files)} dataset records")


if __name__ == "__main__":
    main()
