import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.generate import (
    derive_record,
    duc_for,
    incremental_catalogue_records,
    normalized_doi_url,
    repository_summary,
    repository_statistics,
    retrieval_for,
    source_statistics,
)


class GenerateTests(unittest.TestCase):
    def test_source_reference_is_included(self):
        record = derive_record(
            {
                "dataset_id": "PN000001 Example",
                "dataset_version": "V1",
                "name": "Example",
            },
            {
                "path": "metadata/PN000001 Example/V1/abc/0123456789abcdef0123456789abc.json",
                "sha256": "0" * 64,
            },
        )
        self.assertEqual(record["source"]["sha256"], "0" * 64)

    def test_missing_status_is_active(self):
        record = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
        })
        self.assertEqual(record["status"], "active")
        self.assertNotIn("statusSource", record)
        self.assertEqual(record["retrieval"]["mode"], "online")

    def test_explicit_status_is_preserved(self):
        record = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "status": "withdrawn",
            "download_url": "https://example.org/download",
            "access_request_contact": "person@example.org",
        })
        self.assertNotIn("statusSource", record)
        self.assertEqual(record["retrieval"], {"mode": "unavailable"})

    def test_repository_source_statistics(self):
        values = source_statistics({
            "license": {"name": "Data User Agreement"},
            "description": "Example dataset (total size: 12.50 GB)",
            "additional_display": [{
                "name": "Participants",
                "content": {
                    "total_number": ["30"],
                    "number_of_healthy": ["18"],
                },
            }],
        })
        self.assertEqual(values["access"], "restricted")
        self.assertEqual(values["total"], 30)
        self.assertEqual(values["healthy"], 18)
        self.assertEqual(values["sizeGB"], Decimal("12.50"))

    def test_actual_licence_is_open_and_missing_values_are_not_invented(self):
        values = source_statistics({"license": {"name": "CC BY 4.0"}})
        self.assertEqual(values["access"], "open")
        self.assertIsNone(values["total"])
        self.assertIsNone(values["healthy"])
        self.assertIsNone(values["sizeGB"])

    def test_repository_statistics_use_latest_version_only(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue = Path(directory)
            sources = []
            for version, total in (("V1", 10), ("V2", 20)):
                path = Path("metadata") / "PN000001 Example" / version / "abc" / f"{version}.json"
                target = catalogue / path
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps({
                    "license": {"name": "Data User Agreement"},
                    "description": f"Example (total size: {total} GB)",
                    "additional_display": [{
                        "name": "Participants",
                        "content": {
                            "total_number": [str(total)],
                            "number_of_healthy": [str(total - 2)],
                        },
                    }],
                }), encoding="utf-8")
                sources.append({"version": version, "source": {"path": path.as_posix()}})

            stats = repository_statistics([{
                "datasetId": "PN000001",
                "versions": sources,
            }], catalogue)
            self.assertEqual(stats["datasets"], 1)
            self.assertEqual(stats["versions"], 2)
            self.assertEqual(stats["restricted"], 1)
            self.assertEqual(stats["participants"], 20)
            self.assertEqual(stats["healthy"], 18)
            self.assertEqual(stats["patients"], 2)
            self.assertEqual(stats["sizeGB"], Decimal("20"))

    def test_repository_summary_is_small_numeric_and_website_facing(self):
        summary = repository_summary({
            "datasets": 2,
            "versions": 3,
            "open": 1,
            "restricted": 0,
            "unclassified": 1,
            "participants": 42,
            "healthy": 30,
            "patients": 12,
            "participantDatasets": 1,
            "sizeGB": Decimal("1234.567"),
            "sizeDatasets": 1,
        })
        self.assertEqual(summary, {
            "schemaVersion": "1.0",
            "datasets": 2,
            "versions": 3,
            "access": {"open": 1, "restricted": 0, "unclassified": 1},
            "participants": {
                "total": 42,
                "healthy": 30,
                "patients": 12,
                "datasetsWithCounts": 1,
            },
            "documentedSize": {
                "terabytes": 1.23,
                "datasetsWithSize": 1,
            },
        })

    def test_retrieval_contact(self):
        result = retrieval_for("retired", {
            "access_request_contact": "controller@example.org"
        })
        self.assertEqual(result, {
            "mode": "external",
            "contact": "controller@example.org"
        })

    def test_structured_lifecycle_details_are_exported(self):
        withdrawn = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "status": "withdrawn",
            "status_note": "Withdrawn at the controller's request",
        })
        self.assertEqual(
            withdrawn["statusNote"], "Withdrawn at the controller's request"
        )
        self.assertNotIn("description", withdrawn)

        superseded = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "status": "superseded",
            "replacement": "10.1234/current",
        })
        self.assertEqual(
            superseded["replacement"], "https://doi.org/10.1234/current"
        )

    def test_doi_variants_are_normalized(self):
        self.assertEqual(
            normalized_doi_url("10.70883/EXAMPLE"),
            "https://doi.org/10.70883/EXAMPLE",
        )
        self.assertEqual(
            normalized_doi_url("https:/doi.org/10.70883/EXAMPLE"),
            "https://doi.org/10.70883/EXAMPLE",
        )

    def test_dua_is_mapped_without_copying_text(self):
        source = {
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "license": {"name": "Data User Agreement"},
            "additional_display": [{
                "name": "DUA terms",
                "content": {
                    "Restrictions": ["Users outside the EU must sign standard contractual clauses"],
                    "Terms": [
                        "I will not attempt to re-identify participants. "
                        "I will not redistribute these data."
                    ],
                },
            }],
        }
        profile, provenance = duc_for(source, "https://example.org/dataset")
        labels = {item["conditionTerm"]["label"] for item in profile["conditions"]}
        self.assertEqual(profile["permissionMode"], "All unstated conditions are Permitted")
        self.assertEqual(provenance["mappingStatus"], "machine-generated-unreviewed")
        self.assertIn("Regulatory jurisdiction", labels)
        self.assertIn("Re-identification", labels)
        self.assertIn("Data redistribution", labels)
        self.assertNotIn("Ethics approval", labels)
        serialized = str(profile)
        self.assertNotIn("I will not attempt", serialized)
        self.assertRegex(provenance["sourceAgreement"]["sha256"], r"^[a-f0-9]{64}$")

    def test_cc_by_maps_to_attribution(self):
        profile, provenance = duc_for(
            {
                "dataset_id": "PN000001 Example",
                "dataset_version": "V1",
                "name": "Example",
                "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
            },
            "https://example.org/dataset",
        )
        self.assertEqual(profile["conditions"][0]["conditionTerm"]["label"], "Attribution")
        self.assertEqual(profile["conditions"][0]["rule"], "Obligatory")

    def test_compact_cc_by_name_maps_to_attribution(self):
        profile, provenance = duc_for(
            {
                "dataset_id": "PN000001 Example",
                "dataset_version": "V1",
                "name": "Example",
                "license": {"name": "CCBY4.0"},
                "additional_display": [{
                    "name": "DUA terms",
                    "content": {"Restrictions": ["None (CCBY)"]},
                }],
            },
            "https://example.org/dataset",
        )
        self.assertEqual(provenance["sourceAgreement"]["type"], "CCBY4.0")
        self.assertNotIn("sha256", provenance["sourceAgreement"])
        self.assertEqual(profile["conditions"][0]["conditionTerm"]["label"], "Attribution")

    def test_incremental_reuses_unchanged_source_and_refreshes_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalogue = root / "catalogue"
            output = root / "datasets"
            source_path = (
                catalogue / "metadata" / "PN000001 Example" / "V1" /
                "abc" / "0123456789abcdef0123456789abc.json"
            )
            source_path.parent.mkdir(parents=True)
            source = {
                "type": "dataset",
                "dataset_id": "PN000001 Example",
                "dataset_version": "V1",
                "name": "Example",
                "status": "active",
            }
            source_text = json.dumps(source)
            source_path.write_text(source_text, encoding="utf-8")
            super_path = catalogue / "metadata" / "super" / "abc" / "super.json"
            super_path.parent.mkdir(parents=True)
            super_path.write_text(json.dumps({
                "subdatasets": [{
                    "dataset_id": "PN000001 Example",
                    "dataset_path": "PN000001 Example",
                }]
            }), encoding="utf-8")
            output.mkdir()
            existing = {
                "schemaVersion": "1.3",
                "datasetId": "PN000001",
                "name": "Example",
                "versions": [{
                    "version": "V1",
                    "source": {
                        "path": source_path.relative_to(catalogue).as_posix(),
                        "sha256": hashlib.sha256(source_text.encode()).hexdigest(),
                    },
                    "keywords": ["preserved-marker"],
                }],
            }
            (output / "PN000001.json").write_text(json.dumps(existing), encoding="utf-8")

            records, _ = incremental_catalogue_records(catalogue, output)
            self.assertEqual(records[0]["versions"][0]["keywords"], ["preserved-marker"])

            source["status"] = "withdrawn"
            source["status_note"] = "Controller request"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            records, _ = incremental_catalogue_records(catalogue, output)
            refreshed = records[0]["versions"][0]
            self.assertEqual(refreshed["statusNote"], "Controller request")
            self.assertNotEqual(
                refreshed["source"]["sha256"],
                existing["versions"][0]["source"]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
