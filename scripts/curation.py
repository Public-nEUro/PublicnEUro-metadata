"""Capture and reapply human curation of generated dataset records."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


CURATED_FIELDS = ("duc", "ducProvenance")
MANIFEST_VERSION = "1.0"
_UNCHANGED = object()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def merge_patch_diff(baseline, reviewed):
    """Return an RFC 7396-style merge patch, or _UNCHANGED."""
    if baseline == reviewed:
        return _UNCHANGED
    if not isinstance(baseline, dict) or not isinstance(reviewed, dict):
        return deepcopy(reviewed)

    patch = {}
    for key in baseline.keys() - reviewed.keys():
        patch[key] = None
    for key, value in reviewed.items():
        if key not in baseline:
            patch[key] = deepcopy(value)
            continue
        difference = merge_patch_diff(baseline[key], value)
        if difference is not _UNCHANGED:
            patch[key] = difference
    return patch if patch else _UNCHANGED


def apply_merge_patch(value, patch):
    """Apply an RFC 7396-style merge patch without mutating its inputs."""
    if not isinstance(patch, dict):
        return deepcopy(patch)
    result = deepcopy(value) if isinstance(value, dict) else {}
    for key, replacement in patch.items():
        if replacement is None:
            result.pop(key, None)
        else:
            result[key] = apply_merge_patch(result.get(key), replacement)
    return result


def record_index(records: list[dict]) -> dict[str, dict]:
    return {record["datasetId"]: record for record in records}


def version_index(record: dict) -> dict[str, dict]:
    return {version["version"]: version for version in record.get("versions", [])}


def without_curated_fields(record: dict) -> dict:
    """Return the generated portion of a record for unsupported-edit checks."""
    result = deepcopy(record)
    for version in result.get("versions", []):
        for field in CURATED_FIELDS:
            version.pop(field, None)
    return result


def curation_patch(baseline: dict, reviewed: dict) -> dict | None:
    """Extract supported manual changes for one dataset record."""
    if baseline["datasetId"] != reviewed["datasetId"]:
        raise ValueError("Cannot compare records with different datasetId values")
    if without_curated_fields(baseline) != without_curated_fields(reviewed):
        raise ValueError(
            f"{reviewed['datasetId']} contains manual changes outside "
            f"{', '.join(CURATED_FIELDS)}; correct those fields in DataCatalogue"
        )

    baseline_versions = version_index(baseline)
    reviewed_versions = version_index(reviewed)
    patches = {}
    for version_name, reviewed_version in reviewed_versions.items():
        baseline_version = baseline_versions[version_name]
        version_patch = {}
        for field in CURATED_FIELDS:
            difference = merge_patch_diff(
                baseline_version.get(field), reviewed_version.get(field)
            )
            if difference is not _UNCHANGED:
                version_patch[field] = difference
        if version_patch:
            patches[version_name] = version_patch
    if not patches:
        return None
    return {"datasetId": reviewed["datasetId"], "versions": patches}


def capture_curation(
    baseline_records: list[dict], reviewed_records: list[dict], curation_dir: Path
) -> int:
    """Write minimal curation patches after verifying catalogue provenance."""
    baseline = record_index(baseline_records)
    reviewed = record_index(reviewed_records)
    if baseline.keys() != reviewed.keys():
        missing = sorted(baseline.keys() - reviewed.keys())
        extra = sorted(reviewed.keys() - baseline.keys())
        raise ValueError(f"Dataset set differs from catalogue (missing={missing}, extra={extra})")

    curation_dir.mkdir(parents=True, exist_ok=True)
    captured = 0
    expected_files = set()
    for dataset_id in sorted(baseline):
        baseline_versions = version_index(baseline[dataset_id])
        reviewed_versions = version_index(reviewed[dataset_id])
        if baseline_versions.keys() != reviewed_versions.keys():
            raise ValueError(f"{dataset_id} version set differs from DataCatalogue")
        for version_name, baseline_version in baseline_versions.items():
            reviewed_version = reviewed_versions[version_name]
            if baseline_version.get("source") != reviewed_version.get("source"):
                raise ValueError(
                    f"{dataset_id} {version_name} catalogue source changed; "
                    "synchronize before capturing manual edits"
                )

        patch = curation_patch(baseline[dataset_id], reviewed[dataset_id])
        path = curation_dir / f"{dataset_id}.json"
        if patch:
            path.write_text(
                json.dumps(patch, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            expected_files.add(path.name)
            captured += 1
        elif path.exists():
            path.unlink()

    for path in curation_dir.glob("PN*.json"):
        if path.name not in expected_files:
            path.unlink()
    return captured


def apply_curation(records: list[dict], curation_dir: Path) -> list[dict]:
    """Apply version-keyed curation patches to freshly generated records."""
    result = deepcopy(records)
    indexed = record_index(result)
    for path in sorted(curation_dir.glob("PN*.json")):
        override = load_json(path)
        dataset_id = override.get("datasetId")
        if path.stem != dataset_id or dataset_id not in indexed:
            raise ValueError(f"Invalid or orphaned curation file: {path.name}")
        versions = version_index(indexed[dataset_id])
        for version_name, patch in (override.get("versions") or {}).items():
            if version_name not in versions:
                raise ValueError(f"{path.name}: unknown version {version_name}")
            unknown = set(patch) - set(CURATED_FIELDS)
            if unknown:
                raise ValueError(
                    f"{path.name} {version_name}: unsupported curated fields {sorted(unknown)}"
                )
            versions[version_name].update(
                {
                    field: apply_merge_patch(versions[version_name].get(field), value)
                    for field, value in patch.items()
                }
            )
    return result


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_hashes(dataset_dir: Path) -> dict[str, str]:
    return {
        path.name: file_sha256(path)
        for path in sorted(dataset_dir.glob("PN*.json"))
    }


def write_manifest(dataset_dir: Path, manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {"manifestVersion": MANIFEST_VERSION, "files": dataset_hashes(dataset_dir)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def uncaptured_changes(dataset_dir: Path, manifest_path: Path) -> list[str]:
    """Return dataset filenames changed since generation or capture."""
    if not manifest_path.is_file():
        return []  # Backward-compatible bootstrap for repositories without a manifest.
    manifest = load_json(manifest_path)
    expected = manifest.get("files") or {}
    current = dataset_hashes(dataset_dir)
    return sorted(
        name
        for name in expected.keys() | current.keys()
        if expected.get(name) != current.get(name)
    )
