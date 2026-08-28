import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.generate import update_readme
from scripts.rebuild import reviewed_records


class RebuildTests(unittest.TestCase):
    def test_reviewed_records_are_sorted_by_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset_dir = Path(directory)
            for dataset_id in ("PN000002", "PN000001"):
                (dataset_dir / f"{dataset_id}.json").write_text(
                    json.dumps({"datasetId": dataset_id}), encoding="utf-8"
                )
            records = reviewed_records(dataset_dir)
            self.assertEqual(
                [record["datasetId"] for record in records],
                ["PN000001", "PN000002"],
            )

    def test_filename_must_match_dataset_id(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset_dir = Path(directory)
            (dataset_dir / "PN000001.json").write_text(
                json.dumps({"datasetId": "PN000002"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "filename must match"):
                reviewed_records(dataset_dir)

    def test_empty_dataset_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "No PN.* records"):
                reviewed_records(Path(directory))

    def test_readme_labels_human_reviewed_conditions(self):
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(
                "before\n<!-- DATASET_TABLE_START -->old<!-- DATASET_TABLE_END -->\nafter\n",
                encoding="utf-8",
            )
            records = [{
                "datasetId": "PN000001",
                "name": "Example",
                "versions": [{
                    "version": "V1",
                    "catalogueUrl": "https://example.org/dataset",
                    "status": "active",
                    "retrieval": {"mode": "online"},
                    "duc": {"conditions": [{}, {}]},
                    "ducProvenance": {"mappingStatus": "human-reviewed"},
                }],
            }]
            stats = {
                "datasets": 1,
                "versions": 1,
                "open": 1,
                "restricted": 0,
                "unclassified": 0,
                "participants": 0,
                "healthy": 0,
                "patients": 0,
                "sizeGB": Decimal("0"),
                "sizeDatasets": 0,
            }
            update_readme(readme, records, stats)
            self.assertIn("2 reviewed conditions", readme.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
