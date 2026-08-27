import unittest

from scripts.generate import derive_record, duc_for, normalized_doi_url, retrieval_for


class GenerateTests(unittest.TestCase):
    def test_missing_status_is_active(self):
        record = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "description": "Description",
        })
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["statusSource"], "inferred-default")
        self.assertEqual(record["retrieval"]["mode"], "online")

    def test_explicit_status_is_preserved(self):
        record = derive_record({
            "dataset_id": "PN000001 Example",
            "dataset_version": "V1",
            "name": "Example",
            "description": "Description",
            "status": "withdrawn",
            "download_url": "https://example.org/download",
            "access_request_contact": "person@example.org",
        })
        self.assertEqual(record["statusSource"], "catalogue")
        self.assertEqual(record["retrieval"], {"mode": "unavailable"})

    def test_retrieval_contact(self):
        result = retrieval_for("retired", {
            "access_request_contact": "controller@example.org"
        })
        self.assertEqual(result, {
            "mode": "external",
            "contact": "controller@example.org"
        })

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


if __name__ == "__main__":
    unittest.main()
