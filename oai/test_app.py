"""Protocol checks using the repository's published metadata."""

import unittest
from xml.etree import ElementTree as ET

from oai.app import DATACITE, OAI, SET, access_right, records, response


NS = {"o": OAI, "d": DATACITE}


class OAITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = records()

    def request(self, **kwargs):
        return ET.fromstring(response({k: [v] for k, v in kwargs.items()}, self.items))

    def test_all_six_verbs(self):
        identifier = self.items[0]["identifier"]
        requests = (
            {"verb": "Identify"}, {"verb": "ListSets"},
            {"verb": "ListMetadataFormats"},
            {"verb": "GetRecord", "metadataPrefix": "oai_datacite", "identifier": identifier},
            {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"},
            {"verb": "ListRecords", "metadataPrefix": "oai_datacite", "set": SET},
        )
        for params in requests:
            with self.subTest(params=params):
                root = self.request(**params)
                self.assertIsNone(root.find("o:error", NS))
                self.assertIsNotNone(root.find("o:" + params["verb"], NS))

    def test_each_version_has_unique_record_and_doi(self):
        root = self.request(verb="ListRecords", metadataPrefix="oai_datacite", set=SET)
        headers = root.findall(".//o:header/o:identifier", NS)
        identifiers = [element.text for element in headers]
        self.assertEqual(len(headers), len(self.items))
        self.assertEqual(len(set(identifiers)), len(headers))
        for record in root.findall(".//o:record", NS):
            self.assertIsNotNone(record.find("o:metadata/d:resource/d:identifier", NS))

    def test_selective_harvest_uses_revision_date(self):
        most_recent = max(item["datestamp"] for item in self.items)
        root = self.request(verb="ListIdentifiers", metadataPrefix="oai_datacite",
                            **{"from": most_recent})
        result = [node.text for node in root.findall(".//o:header/o:identifier", NS)]
        expected = [item["identifier"] for item in self.items
                    if item["datestamp"] >= most_recent]
        self.assertEqual(result, expected)

    def test_access_rights_and_superseded_version(self):
        first = next(item for item in self.items if item["identifier"].endswith("PN000001-V1"))
        self.assertEqual(first["version"]["status"], "superseded")
        self.assertEqual(access_right(first["version"]), "openAccess")
        root = self.request(verb="GetRecord", identifier=first["identifier"],
                            metadataPrefix="oai_datacite")
        self.assertEqual(root.find(".//d:relatedIdentifier", NS).get("relationType"),
                         "IsPreviousVersionOf")
        self.assertEqual(root.find(".//d:rights", NS).get("rightsURI"),
                         "info:eu-repo/semantics/openAccess")
        restricted = next(item for item in self.items
                          if item["version"]["ducProvenance"]["sourceAgreement"]["type"]
                          == "Data User Agreement")
        self.assertEqual(access_right(restricted["version"]), "restrictedAccess")
        self.assertEqual(access_right({"status": "withdrawn"}), "closedAccess")

    def test_protocol_errors(self):
        for params, code in (
            ({"verb": "ListRecords"}, "badArgument"),
            ({"verb": "GetRecord", "identifier": "unknown", "metadataPrefix": "oai_dc"},
             "idDoesNotExist"),
            ({"verb": "ListRecords", "metadataPrefix": "made_up"},
             "cannotDisseminateFormat"),
            ({"verb": "ListIdentifiers", "metadataPrefix": "oai_dc",
              "from": "not-a-date"}, "badArgument"),
            ({"verb": "ListRecords", "metadataPrefix": "oai_dc",
              "set": "unknown"}, "noRecordsMatch"),
        ):
            with self.subTest(params=params):
                self.assertEqual(self.request(**params).find("o:error", NS).get("code"), code)


if __name__ == "__main__":
    unittest.main()
