import json
import tempfile
import unittest
from pathlib import Path

from scripts.curation import (
    apply_curation,
    apply_merge_patch,
    capture_curation,
    merge_patch_diff,
    uncaptured_changes,
    write_manifest,
)


def dataset(status="active", conditions=None, mapping_status="machine-generated-unreviewed"):
    return {
        "schemaVersion": "1.3",
        "datasetId": "PN000001",
        "name": "Example",
        "versions": [{
            "version": "V1",
            "source": {"path": "metadata/example.json", "sha256": "0" * 64},
            "status": status,
            "duc": {
                "profileVersion": "1.0",
                "conditions": conditions or [{"rule": "Permitted"}],
            },
            "ducProvenance": {"mappingStatus": mapping_status},
        }],
    }


class CurationTests(unittest.TestCase):
    def test_merge_patch_preserves_only_differences_and_reapplies_them(self):
        baseline = {"a": 1, "nested": {"keep": 2, "change": 3}, "items": [1]}
        reviewed = {"a": 1, "nested": {"keep": 2, "change": 4}, "items": [1, 2]}
        patch = merge_patch_diff(baseline, reviewed)
        self.assertEqual(patch, {"nested": {"change": 4}, "items": [1, 2]})
        self.assertEqual(apply_merge_patch(baseline, patch), reviewed)

    def test_capture_and_apply_human_review(self):
        baseline = dataset()
        reviewed = dataset(
            conditions=[{"rule": "Permitted"}, {"rule": "Forbidden"}],
            mapping_status="human-reviewed",
        )
        with tempfile.TemporaryDirectory() as directory:
            curation_dir = Path(directory)
            count = capture_curation([baseline], [reviewed], curation_dir)
            self.assertEqual(count, 1)
            saved = json.loads((curation_dir / "PN000001.json").read_text())
            patch = saved["versions"]["V1"]
            self.assertEqual(
                patch["duc"]["conditions"],
                [{"rule": "Permitted"}, {"rule": "Forbidden"}],
            )
            self.assertEqual(
                patch["ducProvenance"], {"mappingStatus": "human-reviewed"}
            )

            regenerated = dataset(status="archived")
            merged = apply_curation([regenerated], curation_dir)[0]
            version = merged["versions"][0]
            self.assertEqual(version["status"], "archived")
            self.assertEqual(version["duc"], reviewed["versions"][0]["duc"])
            self.assertEqual(
                version["ducProvenance"]["mappingStatus"], "human-reviewed"
            )

    def test_non_curation_edits_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "outside duc, ducProvenance"):
                capture_curation(
                    [dataset(status="active")],
                    [dataset(status="retired")],
                    Path(directory),
                )

    def test_manifest_detects_and_then_accepts_captured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_dir = root / "datasets"
            dataset_dir.mkdir()
            record = dataset_dir / "PN000001.json"
            record.write_text("original\n", encoding="utf-8")
            manifest = root / "curation" / "manifest.json"
            write_manifest(dataset_dir, manifest)
            self.assertEqual(uncaptured_changes(dataset_dir, manifest), [])
            record.write_text("reviewed\n", encoding="utf-8")
            self.assertEqual(
                uncaptured_changes(dataset_dir, manifest), ["PN000001.json"]
            )
            write_manifest(dataset_dir, manifest)
            self.assertEqual(uncaptured_changes(dataset_dir, manifest), [])


if __name__ == "__main__":
    unittest.main()
