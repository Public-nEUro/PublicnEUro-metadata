"""PublicnEUro OAI-PMH 2.0 provider for the dataset metadata repository.

Serve ``app`` as WSGI at the URL configured in ``OAI_BASE_URL``. The service
reads the reviewed, versioned ``datasets/PN*.json`` files directly; no access
to participant-level data or catalogue credentials is needed.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET


ROOT = Path(os.environ.get("OAI_METADATA_ROOT", Path(__file__).resolve().parents[1]))
BASE_URL = os.environ.get("OAI_BASE_URL", "https://datacatalog.publicneuro.eu/oai")
ADMIN_EMAIL = os.environ.get("OAI_ADMIN_EMAIL", "publicneuro@nru.dk")
OAI = "http://www.openarchives.org/OAI/2.0/"
DC = "http://purl.org/dc/elements/1.1/"
OAI_DC = "http://www.openarchives.org/OAI/2.0/oai_dc/"
DATACITE = "http://datacite.org/schema/kernel-3"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SET = "openaire_data"
PREFIXES = {
    "oai_dc": ("http://www.openarchives.org/OAI/2.0/oai_dc.xsd", OAI_DC),
    "oai_datacite": ("http://schema.datacite.org/meta/kernel-3/metadata.xsd", DATACITE),
}
VERBS = {
    "Identify": set(),
    "ListMetadataFormats": {"identifier"},
    "ListSets": set(),
    "GetRecord": {"identifier", "metadataPrefix"},
    "ListIdentifiers": {"from", "until", "set", "metadataPrefix"},
    "ListRecords": {"from", "until", "set", "metadataPrefix"},
}

ET.register_namespace("", OAI)
ET.register_namespace("xsi", XSI)
ET.register_namespace("oai_dc", OAI_DC)
ET.register_namespace("dc", DC)


def element(parent, namespace, name, value=None, **attributes):
    node = ET.SubElement(parent, f"{{{namespace}}}{name}", attributes)
    if value is not None:
        node.text = str(value)
    return node


def records():
    items = []
    for path in sorted((ROOT / "datasets").glob("PN*.json")):
        dataset = json.loads(path.read_text(encoding="utf-8"))
        if any(not version.get("doi") for version in dataset["versions"]):
            raise ValueError(f"OAI DataCite export requires a DOI for each version: {path}")
        # OAI datestamps describe changes to the *exported record*. A fresh
        # checkout's filesystem mtime is unrelated to the record's revision.
        committed = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(path.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, check=False,
        ) if (ROOT / ".git").exists() else None
        revision_date = committed.stdout.strip() if committed and committed.returncode == 0 else ""
        for version in dataset["versions"]:
            # A changed repository record must be offered on an incremental
            # harvest, even when its catalogue's lastUpdated is unchanged.
            datestamp = max(version.get("lastUpdated", "1970-01-01"),
                            revision_date or datetime.fromtimestamp(
                                path.stat().st_mtime, timezone.utc).date().isoformat())
            items.append({"dataset": dataset, "version": version,
                          "identifier": f"oai:publicneuro.eu:{dataset['datasetId']}-{version['version']}",
                          "datestamp": datestamp})
    return sorted(items, key=lambda item: item["identifier"])


def add_header(parent, item):
    header = element(parent, OAI, "header")
    element(header, OAI, "identifier", item["identifier"])
    element(header, OAI, "datestamp", item["datestamp"])
    element(header, OAI, "setSpec", SET)
    return header


def access_right(version):
    if version.get("status") == "withdrawn":
        return "closedAccess"
    agreement = version.get("ducProvenance", {}).get("sourceAgreement", {})
    return "restrictedAccess" if agreement.get("type") == "Data User Agreement" else "openAccess"


def datacite(parent, item):
    dataset, version = item["dataset"], item["version"]
    doi = version.get("doi", "").removeprefix("https://doi.org/")
    resource = element(parent, DATACITE, "resource")
    resource.set(f"{{{XSI}}}schemaLocation",
                 f"{DATACITE} http://schema.datacite.org/meta/kernel-3/metadata.xsd")
    element(resource, DATACITE, "identifier", doi, identifierType="DOI")
    creators = element(resource, DATACITE, "creators")
    for creator in version.get("creators", []):
        node = element(creators, DATACITE, "creator")
        full_name = ", ".join(filter(None, (creator.get("familyName"), creator.get("givenName"))))
        element(node, DATACITE, "creatorName", full_name)
    titles = element(resource, DATACITE, "titles")
    element(titles, DATACITE, "title", dataset["name"])
    element(resource, DATACITE, "publisher", "PublicnEUro")
    element(resource, DATACITE, "publicationYear", version.get("lastUpdated", item["datestamp"])[:4])
    subjects = version.get("keywords", [])
    if subjects:
        container = element(resource, DATACITE, "subjects")
        for subject in subjects:
            element(container, DATACITE, "subject", subject)
    dates = element(resource, DATACITE, "dates")
    element(dates, DATACITE, "date", version.get("lastUpdated", item["datestamp"]), dateType="Updated")
    element(resource, DATACITE, "resourceType", "Dataset", resourceTypeGeneral="Dataset")
    alternates = element(resource, DATACITE, "alternateIdentifiers")
    element(alternates, DATACITE, "alternateIdentifier", version["catalogueUrl"],
            alternateIdentifierType="URL")
    replacement = version.get("replacement", "")
    if replacement:
        related = element(resource, DATACITE, "relatedIdentifiers")
        element(related, DATACITE, "relatedIdentifier", replacement.removeprefix("https://doi.org/"),
                relatedIdentifierType="DOI", relationType="IsPreviousVersionOf")
    element(resource, DATACITE, "version", version["version"])
    rights = element(resource, DATACITE, "rightsList")
    kind = access_right(version)
    element(rights, DATACITE, "rights", rightsURI=f"info:eu-repo/semantics/{kind}")
    agreement = version.get("ducProvenance", {}).get("sourceAgreement", {})
    if agreement.get("url"):
        element(rights, DATACITE, "rights", agreement.get("type", "Access conditions"),
                rightsURI=agreement["url"])


def dublin_core(parent, item):
    dataset, version = item["dataset"], item["version"]
    node = element(parent, OAI_DC, "dc")
    node.set(f"{{{XSI}}}schemaLocation", f"{OAI_DC} http://www.openarchives.org/OAI/2.0/oai_dc.xsd")
    element(node, DC, "title", dataset["name"])
    for creator in version.get("creators", []):
        element(node, DC, "creator", ", ".join(filter(None,
                (creator.get("familyName"), creator.get("givenName")))))
    for subject in version.get("keywords", []):
        element(node, DC, "subject", subject)
    element(node, DC, "publisher", "PublicnEUro")
    element(node, DC, "type", "Dataset")
    element(node, DC, "date", version.get("lastUpdated", item["datestamp"]))
    element(node, DC, "identifier", version["catalogueUrl"])
    if version.get("doi"):
        element(node, DC, "identifier", version["doi"])
    element(node, DC, "rights", f"info:eu-repo/semantics/{access_right(version)}")
    return node


def add_record(parent, item, prefix):
    record = element(parent, OAI, "record")
    add_header(record, item)
    metadata = element(record, OAI, "metadata")
    (datacite if prefix == "oai_datacite" else dublin_core)(metadata, item)


def validate(verb, args, items):
    if verb not in VERBS:
        return "badVerb", "Unknown or missing OAI-PMH verb"
    permitted = VERBS[verb] | {"verb"}
    if any(key not in permitted or len(values) != 1 for key, values in args.items()):
        return "badArgument", "Unknown or repeated request parameter"
    if verb == "GetRecord" and not {"identifier", "metadataPrefix"} <= args.keys():
        return "badArgument", "GetRecord requires identifier and metadataPrefix"
    if verb in ("ListIdentifiers", "ListRecords") and "metadataPrefix" not in args:
        return "badArgument", "metadataPrefix is required"
    if "metadataPrefix" in args and args["metadataPrefix"][0] not in PREFIXES:
        return "cannotDisseminateFormat", "Unsupported metadataPrefix"
    if "identifier" in args and args["identifier"][0] not in {item["identifier"] for item in items}:
        return "idDoesNotExist", "Unknown identifier"
    if "set" in args and args["set"][0] != SET:
        return "noRecordsMatch", "Unknown set"
    for name in ("from", "until"):
        if name in args:
            try:
                if date.fromisoformat(args[name][0]).isoformat() != args[name][0]:
                    raise ValueError
            except ValueError:
                return "badArgument", f"{name} must be YYYY-MM-DD"
    if "from" in args and "until" in args and args["from"][0] > args["until"][0]:
        return "badArgument", "from is later than until"
    return None


def response(params, items):
    verb = params.get("verb", [""])[0]
    root = ET.Element(f"{{{OAI}}}OAI-PMH", {
        f"{{{XSI}}}schemaLocation": f"{OAI} http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd"})
    element(root, OAI, "responseDate", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    request_attrs = {key: values[0] for key, values in params.items()
                     if len(values) == 1 and key in (VERBS.get(verb, set()) | {"verb"})}
    element(root, OAI, "request", BASE_URL, **request_attrs)
    error = validate(verb, params, items)
    if error:
        element(root, OAI, "error", error[1], code=error[0])
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if verb == "Identify":
        node = element(root, OAI, verb)
        for name, value in (("repositoryName", "PublicnEUro"), ("baseURL", BASE_URL),
                            ("protocolVersion", "2.0"), ("adminEmail", ADMIN_EMAIL),
                            ("earliestDatestamp", min((x["datestamp"] for x in items), default="1970-01-01")),
                            ("deletedRecord", "no"), ("granularity", "YYYY-MM-DD")):
            element(node, OAI, name, value)
    elif verb == "ListSets":
        node = element(element(root, OAI, verb), OAI, "set")
        element(node, OAI, "setSpec", SET)
        element(node, OAI, "setName", "OpenAIRE datasets")
    elif verb == "ListMetadataFormats":
        node = element(root, OAI, verb)
        for prefix, (schema, namespace) in PREFIXES.items():
            metadata_format = element(node, OAI, "metadataFormat")
            element(metadata_format, OAI, "metadataPrefix", prefix)
            element(metadata_format, OAI, "schema", schema)
            element(metadata_format, OAI, "metadataNamespace", namespace)
    elif verb == "GetRecord":
        node = element(root, OAI, verb)
        item = next(x for x in items if x["identifier"] == params["identifier"][0])
        add_record(node, item, params["metadataPrefix"][0])
    else:
        matching = [x for x in items if
                    ("from" not in params or x["datestamp"] >= params["from"][0]) and
                    ("until" not in params or x["datestamp"] <= params["until"][0])]
        if not matching:
            element(root, OAI, "error", "No matching records", code="noRecordsMatch")
        else:
            node = element(root, OAI, verb)
            for item in matching:
                if verb == "ListIdentifiers":
                    add_header(node, item)
                else:
                    add_record(node, item, params["metadataPrefix"][0])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def app(environ, start_response):
    """WSGI entry point. Configure HTTPS and the public base URL at the proxy."""
    if environ.get("REQUEST_METHOD") not in ("GET", "POST"):
        start_response("405 Method Not Allowed", [("Allow", "GET, POST"), ("Content-Type", "text/plain")])
        return [b"Use GET or POST"]
    if environ.get("REQUEST_METHOD") == "POST":
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if length > 4096:
            start_response("413 Content Too Large", [("Content-Type", "text/plain")])
            return [b"Request too large"]
        query = environ["wsgi.input"].read(length).decode("utf-8")
    else:
        query = environ.get("QUERY_STRING", "")
    params = parse_qs(query, keep_blank_values=True)
    xml = response(params, records())
    start_response("200 OK", [("Content-Type", "text/xml; charset=utf-8"),
                              ("Content-Length", str(len(xml)))])
    return [xml]
