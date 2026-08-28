#!/usr/bin/env python3
"""Generate PublicnEUro governance JSON and repository XML exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote


STATUSES = {"active", "archived", "retired", "withdrawn", "superseded"}
SCHEMA_VERSION = "1.3"
RETRIEVAL_MODES = {
    "active": "online",
    "archived": "cold_archive",
    "retired": "external",
    "withdrawn": "unavailable",
    "superseded": "online",
}
CATALOGUE_BASE = "https://datacatalog.publicneuro.eu/dataset"
R3D = "http://www.re3data.org/schema/4-0"
OAI = "http://www.openarchives.org/OAI/2.0/"
CERIF = "https://www.openaire.eu/cerif-profile/1.2/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XML = "http://www.w3.org/XML/1998/namespace"
MAPPING_PATH = Path(__file__).resolve().parents[1] / "mappings" / "dua_to_duc.json"


def local_date(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10]


def iso_timestamp(value: str | None) -> str:
    if not value:
        return "1970-01-01T00:00:00Z"
    text = value.replace(" ", "T")
    if len(text) == 10:
        text += "T00:00:00"
    return text.rstrip("Z") + "Z"


def dataset_code(dataset_id: str) -> str:
    match = re.match(r"^(PN\d{6})\b", dataset_id)
    if not match:
        raise ValueError(f"Unsupported dataset identifier: {dataset_id}")
    return match.group(1)


def retrieval_for(status: str, source: dict) -> dict:
    result = {"mode": RETRIEVAL_MODES[status]}
    if status == "withdrawn":
        return result

    if status in {"archived", "retired"}:
        url = source.get("access_request_url")
        contact = source.get("access_request_contact")
    else:
        url = source.get("download_url") or source.get("access_request_url")
        contact = source.get("access_request_contact")

    if url:
        result["url"] = url
    if contact:
        result["contact"] = contact
    return result


def dua_sections(source: dict) -> dict[str, list[str]]:
    sections = {"restrictions": [], "terms": []}
    for panel in source.get("additional_display") or []:
        if panel.get("name", "").strip().lower() != "dua terms":
            continue
        content = panel.get("content") or {}
        for source_key, target_key in (("Restrictions", "restrictions"), ("Terms", "terms")):
            values = content.get(source_key) or []
            if isinstance(values, str):
                values = [values]
            sections[target_key].extend(value.strip() for value in values if value.strip())
    return sections


def duc_for(source: dict, catalogue_url: str) -> tuple[dict, dict]:
    license_data = source.get("license") or {}
    name = license_data.get("name", "")
    sections = dua_sections(source)
    normalized_license = re.sub(r"[^a-z0-9]", "", name.lower())
    is_cc_by = normalized_license.startswith("ccby")
    has_dua = not is_cc_by and bool(
        sections["restrictions"] or sections["terms"] or "user agreement" in name.lower()
    )
    mapping = load_json(MAPPING_PATH)
    duc = {
        "profileVersion": "0.1.0",
        "profileName": f"{dataset_code(source['dataset_id'])} {source['dataset_version']} Digital Use Conditions",
        "ducVersion": "1.1.0",
        "permissionMode": mapping["permissionMode"],
        "language": "eng",
        "assets": [{
            "assetName": source.get("name", source["dataset_id"]),
            "assetURI": catalogue_url,
        }],
        "conditions": [],
    }
    if source.get("dateCreated"):
        duc["creationDate"] = local_date(source["dateCreated"])
    if source.get("dateModified"):
        duc["lastUpdated"] = local_date(source["dateModified"])
    if source.get("doi"):
        duc["assets"][0]["assetReferences"] = [normalized_doi_url(source["doi"])]

    provenance = {
        "mappingVersion": mapping["mappingVersion"],
        "mappingStatus": "machine-generated-unreviewed",
        "sourceAgreement": {
            "type": "Data User Agreement" if has_dua else (name or "Unspecified"),
            "url": catalogue_url,
            "authoritative": True,
        },
        "conditionEvidence": [],
    }

    if has_dua:
        joined = "\n".join(
            f"{key}: {value}" for key, values in sections.items() for value in values
        )
        provenance["sourceAgreement"]["sha256"] = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        lowered = {key: "\n".join(values).lower() for key, values in sections.items()}
        for rule in mapping["rules"]:
            matched_sections = sorted(
                key for key, text in lowered.items()
                if any(re.search(pattern, text, flags=re.I | re.S) for pattern in rule["patterns"])
            )
            if not matched_sections:
                continue
            condition = {
                "conditionTerm": rule["conditionTerm"],
                "rule": rule["rule"],
                "scope": rule["scope"],
            }
            if rule.get("conditionParameter"):
                condition["conditionParameter"] = rule["conditionParameter"]
            duc["conditions"].append(condition)
            provenance["conditionEvidence"].append({
                "conditionIndex": len(duc["conditions"]) - 1,
                "mappingRule": rule["id"],
                "sourceSections": matched_sections,
                "confidence": "deterministic-pattern",
            })
    elif is_cc_by:
        duc["conditions"].append({
            "conditionTerm": {"label": "Attribution"},
            "rule": "Obligatory",
            "scope": "Whole of asset",
        })
        provenance["conditionEvidence"].append({
            "conditionIndex": 0,
            "mappingRule": "PN-DUC-CCBY-001",
            "sourceSections": ["license"],
            "confidence": "deterministic-license",
        })
        if license_data.get("url"):
            provenance["sourceAgreement"]["url"] = normalized_url(license_data["url"])
        else:
            provenance["sourceAgreement"]["url"] = "https://creativecommons.org/licenses/by/4.0/"

    if not duc["conditions"]:
        duc["conditions"].append({
            "conditionTerm": {"label": "General research use"},
            "rule": "Permitted",
            "scope": "Whole of asset",
        })
        provenance["conditionEvidence"].append({
            "conditionIndex": 0,
            "mappingRule": "PN-DUC-DEFAULT-001",
            "sourceSections": ["license"],
            "confidence": "deterministic-license",
        })
    return duc, provenance


def absolute_access_url(value: str) -> str:
    if value.startswith("/"):
        return "https://datacatalog.publicneuro.eu" + value
    return value


def normalized_doi_url(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?:/doi\.org/", "https://doi.org/", value, flags=re.I)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "https://doi.org/", value, flags=re.I)
    if value.lower().startswith("10."):
        value = "https://doi.org/" + value
    return value


def normalized_url(value: str) -> str:
    value = value.strip()
    return re.sub(r"^https:/([^/])", r"https://\1", value)


def source_reference(path: Path, catalogue: Path) -> dict:
    return {
        "path": path.relative_to(catalogue).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def derive_record(source: dict, source_ref: dict | None = None) -> dict:
    status = source.get("status", "active")
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r} in {source.get('dataset_id')}")

    code = dataset_code(source["dataset_id"])
    version = source["dataset_version"]
    catalogue_url = f"{CATALOGUE_BASE}/{quote(source['dataset_id'])}/{version}"
    duc, duc_provenance = duc_for(source, catalogue_url)
    record = {
        "version": version,
        "catalogueUrl": catalogue_url,
        "status": status,
        "retrieval": retrieval_for(status, source),
        "duc": duc,
        "ducProvenance": duc_provenance,
    }
    if source_ref:
        record["source"] = source_ref
    if source.get("status_note"):
        record["statusNote"] = source["status_note"].strip()
    if source.get("replacement"):
        record["replacement"] = normalized_doi_url(source["replacement"])
    if record["retrieval"].get("url"):
        record["retrieval"]["url"] = absolute_access_url(record["retrieval"]["url"])
    for key, target in (("doi", "doi"), ("dateModified", "lastUpdated")):
        if source.get(key):
            record[target] = (
                local_date(source[key]) if key == "dateModified"
                else normalized_doi_url(source[key])
            )
    if source.get("authors"):
        record["creators"] = [
            {k: a[k].strip() for k in ("givenName", "familyName") if a.get(k)}
            for a in source["authors"]
        ]
    if source.get("keywords"):
        record["keywords"] = source["keywords"]
    return record


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def root_dataset(version_dir: Path, expected_code: str) -> tuple[dict, Path]:
    candidates = []
    for path in version_dir.glob("*/*.json"):
        value = load_json(path)
        if value.get("type") == "dataset" and value.get("dataset_id", "").startswith(expected_code):
            candidates.append((value, path))
    exact = [item for item in candidates if dataset_code(item[0]["dataset_id"]) == expected_code]
    if len(exact) != 1:
        raise RuntimeError(f"Expected one root dataset in {version_dir}, found {len(exact)}")
    return exact[0]


def catalogue_index(catalogue: Path) -> tuple[list[dict], dict]:
    super_files = list((catalogue / "metadata" / "super").rglob("*.json"))
    if len(super_files) != 1:
        raise RuntimeError("Could not identify the catalogue super dataset")
    super_record = load_json(super_files[0])
    return super_record["subdatasets"], super_record


def catalogue_records(catalogue: Path) -> tuple[list[dict], dict]:
    items, super_record = catalogue_index(catalogue)
    records = []
    for item in items:
        code = dataset_code(item["dataset_id"])
        dataset_dir = catalogue / "metadata" / item["dataset_path"]
        versions = sorted(dataset_dir.glob("V*"), key=lambda p: int(p.name[1:]))
        version_sources = [root_dataset(path, code) for path in versions]
        version_records = [value for value, _ in version_sources]
        records.append({
            "schemaVersion": SCHEMA_VERSION,
            "datasetId": code,
            "name": version_records[-1].get("name", item["dataset_id"]),
            "versions": [
                derive_record(value, source_reference(path, catalogue))
                for value, path in version_sources
            ],
        })
    records.sort(key=lambda value: value["datasetId"])
    return records, super_record


def existing_records(output: Path) -> dict[str, dict]:
    return {
        record["datasetId"]: record
        for path in sorted(output.glob("PN*.json"))
        for record in [load_json(path)]
    }


def first_value(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def integer_value(value) -> int | None:
    value = first_value(value)
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def source_statistics(source: dict) -> dict:
    """Extract access, participant, and documented-size facts from one version."""
    license_name = str((source.get("license") or {}).get("name") or "").strip()
    if license_name.casefold() == "data user agreement":
        access = "restricted"
    elif license_name:
        access = "open"
    else:
        access = "unclassified"

    total = healthy = None
    for panel in source.get("additional_display") or []:
        if str(panel.get("name", "")).strip().casefold() != "participants":
            continue
        content = panel.get("content") or {}
        total = integer_value(content.get("total_number"))
        healthy = integer_value(content.get("number_of_healthy"))
        break

    description = source.get("description")
    description = "\n".join(description) if isinstance(description, list) else str(description or "")
    match = re.search(
        r"\(\s*total size:\s*([0-9]+(?:[.,][0-9]+)?)\s*GB\s*\)",
        description,
        flags=re.I,
    )
    size_gb = Decimal(match.group(1).replace(",", ".")) if match else None
    return {"access": access, "total": total, "healthy": healthy, "sizeGB": size_gb}


def repository_statistics(records: list[dict], catalogue: Path) -> dict:
    """Aggregate latest-version figures without double-counting versioned datasets."""
    stats = {
        "datasets": len(records),
        "versions": sum(len(dataset["versions"]) for dataset in records),
        "open": 0,
        "restricted": 0,
        "unclassified": 0,
        "participants": 0,
        "healthy": 0,
        "patients": 0,
        "participantDatasets": 0,
        "sizeGB": Decimal("0"),
        "sizeDatasets": 0,
    }
    for dataset in records:
        latest = dataset["versions"][-1]
        source = load_json(catalogue / latest["source"]["path"])
        values = source_statistics(source)
        stats[values["access"]] += 1
        if values["total"] is not None and values["healthy"] is not None:
            if values["healthy"] > values["total"]:
                raise ValueError(
                    f"Healthy participant count exceeds total in {dataset['datasetId']}"
                )
            stats["participants"] += values["total"]
            stats["healthy"] += values["healthy"]
            stats["patients"] += values["total"] - values["healthy"]
            stats["participantDatasets"] += 1
        if values["sizeGB"] is not None:
            stats["sizeGB"] += values["sizeGB"]
            stats["sizeDatasets"] += 1
    return stats


def incremental_catalogue_records(catalogue: Path, output: Path) -> tuple[list[dict], dict]:
    """Refresh records whose stored catalogue source changed; discover new versions."""
    items, super_record = catalogue_index(catalogue)
    existing = existing_records(output)
    records = []
    for item in items:
        code = dataset_code(item["dataset_id"])
        dataset_dir = catalogue / "metadata" / item["dataset_path"]
        version_dirs = sorted(dataset_dir.glob("V*"), key=lambda p: int(p.name[1:]))
        old_dataset = existing.get(code, {})
        old_versions = {value["version"]: value for value in old_dataset.get("versions", [])}
        versions = []
        source_names = []
        for version_dir in version_dirs:
            old = old_versions.get(version_dir.name)
            stored_source = old.get("source") if old else None
            source_path = catalogue / stored_source["path"] if stored_source else None
            if source_path and source_path.is_file():
                current_ref = source_reference(source_path, catalogue)
                if current_ref["sha256"] == stored_source.get("sha256"):
                    versions.append(old)
                    source_names.append(None)
                    continue
                source = load_json(source_path)
            else:
                source, source_path = root_dataset(version_dir, code)
                current_ref = source_reference(source_path, catalogue)
            versions.append(derive_record(source, current_ref))
            source_names.append(source.get("name"))
        latest_name = source_names[-1] if source_names and source_names[-1] else old_dataset.get("name")
        records.append({
            "schemaVersion": SCHEMA_VERSION,
            "datasetId": code,
            "name": latest_name or item["dataset_id"],
            "versions": versions,
        })
    records.sort(key=lambda value: value["datasetId"])
    return records, super_record


def write_json_records(records: list[dict], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for old in output.glob("PN*.json"):
        old.unlink()
    for record in records:
        public = {k: v for k, v in record.items() if not k.startswith("_")}
        (output / f"{record['datasetId']}.json").write_text(
            json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def doi_value(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)


def add(parent: ET.Element, namespace: str, name: str, text: str | None = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, f"{{{namespace}}}{name}", attrs)
    if text is not None:
        element.text = str(text)
    return element


def write_cerif(records: list[dict], output: Path, response_date: str) -> None:
    ET.register_namespace("", OAI)
    ET.register_namespace("xsi", XSI)
    root = ET.Element(f"{{{OAI}}}OAI-PMH", {
        f"{{{XSI}}}schemaLocation": (
            f"{OAI} http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd "
            f"{CERIF} https://www.openaire.eu/schema/cris/current/openaire-cerif-profile.xsd"
        )
    })
    add(root, OAI, "responseDate", iso_timestamp(response_date))
    request = add(root, OAI, "request", "https://datacatalog.publicneuro.eu/openaire", metadataPrefix="cerif_openaire", verb="ListRecords", set="openaire_cris_datasets")
    listing = add(root, OAI, "ListRecords")
    for dataset in records:
        for version in dataset["versions"]:
            key = f"{dataset['datasetId']}-{version['version']}"
            record = add(listing, OAI, "record")
            header = add(record, OAI, "header")
            add(header, OAI, "identifier", f"oai:datacatalog.publicneuro.eu:Products/{key}")
            add(header, OAI, "datestamp", iso_timestamp(version.get("lastUpdated")))
            add(header, OAI, "setSpec", "openaire_cris_datasets")
            metadata = add(record, OAI, "metadata")
            product = ET.SubElement(metadata, f"{{{CERIF}}}Product", {"id": f"Products/{key}"})
            add(product, "https://www.openaire.eu/cerif-profile/vocab/COAR_Product_Types", "Type", "http://purl.org/coar/resource_type/c_ddb1")
            add(product, CERIF, "Name", dataset["name"], **{f"{{{XML}}}lang": "en"})
            add(product, CERIF, "VersionInfo", version["version"], **{f"{{{XML}}}lang": "en"})
            doi = doi_value(version.get("doi"))
            if doi:
                add(product, CERIF, "DOI", doi)
            add(product, CERIF, "URL", version["catalogueUrl"])
            if version.get("creators"):
                creators = add(product, CERIF, "Creators")
                for index, creator in enumerate(version["creators"], 1):
                    wrapper = add(creators, CERIF, "Creator")
                    person = add(wrapper, CERIF, "Person", id=f"Persons/{key}-{index}")
                    name = add(person, CERIF, "PersonName")
                    add(name, CERIF, "FamilyNames", creator.get("familyName", ""))
                    if creator.get("givenName"):
                        add(name, CERIF, "FirstNames", creator["givenName"])
            agreement_type = version["ducProvenance"]["sourceAgreement"]["type"]
            if re.sub(r"[^a-z0-9]", "", agreement_type.lower()).startswith("ccby"):
                add(product, CERIF, "License", "https://spdx.org/licenses/CC-BY-4.0", scheme="https://spdx.org/licenses")
            for keyword in version.get("keywords", []):
                add(product, CERIF, "Keyword", keyword, **{f"{{{XML}}}lang": "en"})
            access = "c_14cb" if version["status"] == "withdrawn" else "c_16ec"
            add(product, "http://purl.org/coar/access_right", "Access", f"http://purl.org/coar/access_right/{access}")
            if version.get("lastUpdated"):
                dates = add(product, CERIF, "Dates")
                add(dates, CERIF, "Updated", startDate=version["lastUpdated"])
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def write_re3data(repository: dict, dataset_count: int, last_update: str, output: Path) -> None:
    ET.register_namespace("r3d", R3D)
    ET.register_namespace("xsi", XSI)
    root = ET.Element(f"{{{R3D}}}re3data", {
        f"{{{XSI}}}schemaLocation": f"{R3D} https://schema.re3data.org/4-0/re3dataV4-0.xsd"
    })
    repo = add(root, R3D, "repository")
    identifiers = add(repo, R3D, "identifiers")
    add(identifiers, R3D, "re3data", "pending-registration")
    add(identifiers, R3D, "doi", "not-assigned")
    add(repo, R3D, "repositoryName", repository["name"], language="eng")
    add(repo, R3D, "repositoryUrl", repository["url"])
    add(repo, R3D, "description", repository["description"], language="eng")
    add(repo, R3D, "type", repository["repositoryType"])
    add(repo, R3D, "size", f"{dataset_count} datasets")
    add(repo, R3D, "repositoryLanguage", repository["repositoryLanguage"])
    subject = add(repo, R3D, "subject", subjectScheme=repository["subject"]["scheme"])
    add(subject, R3D, "subjectId", repository["subject"]["id"])
    add(subject, R3D, "subjectName", repository["subject"]["name"])
    add(repo, R3D, "providerType", repository["providerType"])
    institution = add(repo, R3D, "institution")
    add(institution, R3D, "institutionName", repository["institution"]["name"], language="eng")
    add(institution, R3D, "institutionCountry", repository["institution"]["country"])
    add(institution, R3D, "responsibilityType", repository["institution"]["responsibility"])
    add(institution, R3D, "institutionType", repository["institution"]["type"])
    add(institution, R3D, "institutionUrl", repository["institution"]["url"])
    database = add(repo, R3D, "databaseAccess")
    add(database, R3D, "databaseAccessType", "open")
    database_license = add(repo, R3D, "databaseLicense")
    add(database_license, R3D, "databaseLicenseName", repository["metadataLicense"]["name"])
    add(database_license, R3D, "databaseLicenseUrl", repository["metadataLicense"]["url"])
    data_access = add(repo, R3D, "dataAccess")
    add(data_access, R3D, "dataAccessType", "restricted")
    add(data_access, R3D, "dataAccessRestriction", "registration")
    data_license = add(repo, R3D, "dataLicense")
    add(data_license, R3D, "dataLicenseName", "Dataset-specific licence or Data User Agreement")
    add(data_license, R3D, "dataLicenseUrl", repository["catalogueUrl"])
    upload = add(repo, R3D, "dataUpload")
    add(upload, R3D, "dataUploadType", "restricted")
    add(upload, R3D, "dataUploadRestriction", "registration")
    add(repo, R3D, "versioning", "yes")
    add(repo, R3D, "remarks", "Identifiers are placeholders until PublicnEUro is registered in re3data.")
    add(repo, R3D, "entryDate", repository["entryDate"])
    add(repo, R3D, "lastUpdate", local_date(last_update) or repository["entryDate"])
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def update_readme(readme: Path, records: list[dict], stats: dict) -> None:
    rows = [
        "| Dataset | Version | Status | Retrieval | DUC | DOI | Updated |",
        "|---|---:|---|---|---|---|---|",
    ]
    for dataset in records:
        for version in dataset["versions"]:
            doi = version.get("doi", "")
            doi_cell = f"[{doi_value(doi)}]({doi})" if doi else "—"
            condition_count = len(version["duc"]["conditions"])
            condition_label = "condition" if condition_count == 1 else "conditions"
            rows.append(
                f"| [{dataset['datasetId']}]({version['catalogueUrl']}) {dataset['name']} "
                f"| {version['version']} | {version['status']} | {version['retrieval']['mode']} "
                f"| {condition_count} inferred {condition_label} | {doi_cell} | {version.get('lastUpdated', '—')} |"
            )
    access = f"{stats['open']} open access / {stats['restricted']} restricted"
    if stats["unclassified"]:
        access += f" / {stats['unclassified']} unclassified"
    size_gb = stats["sizeGB"]
    summary = (
        f"\n**{stats['datasets']} datasets / {stats['versions']} versions**\n\n"
        f"- **Access:** {access}\n"
        f"- **Participants:** {stats['participants']:,} total "
        f"({stats['healthy']:,} healthy / {stats['patients']:,} patients)\n"
        f"- **Documented size:** {size_gb:,.2f} GB "
        f"(≈{size_gb / Decimal('1000'):,.2f} TB; "
        f"reported for {stats['sizeDatasets']}/{stats['datasets']} datasets)\n\n"
        "Figures use the latest version of each dataset. Access is restricted when the "
        "catalogue licence is `Data User Agreement`; participant counts come from the "
        "`Participants` panel; patients are inferred as total minus healthy participants. "
        "Counts are dataset-level and may include the same individuals in related datasets.\n\n"
        + "\n".join(rows)
        + "\n"
    )
    text = readme.read_text(encoding="utf-8")
    pattern = r"(?s)(<!-- DATASET_TABLE_START -->).*?(<!-- DATASET_TABLE_END -->)"
    replacement = rf"\1{summary}\2"
    readme.write_text(re.sub(pattern, replacement, text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="reuse unchanged records by following their stored catalogue source paths",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    catalogue = args.catalogue.resolve()
    if args.incremental:
        records, super_record = incremental_catalogue_records(
            catalogue, output / "datasets"
        )
    else:
        records, super_record = catalogue_records(catalogue)
    stats = repository_statistics(records, catalogue)
    write_json_records(records, output / "datasets")
    updated = super_record.get("dateModified") or max(
        (v.get("lastUpdated", "") for d in records for v in d["versions"]), default=""
    )
    write_cerif(records, output / "exports" / "openaire-cerif.xml", updated)
    repository = load_json(output / "repository.json")
    write_re3data(repository, len(records), updated, output / "exports" / "re3data.xml")
    update_readme(output / "README.md", records, stats)


if __name__ == "__main__":
    main()
