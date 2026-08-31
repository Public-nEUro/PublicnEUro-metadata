# Metadata scripts

The scripts support two distinct workflows: deriving dataset records from the
DataCatalogue and preserving human review while rebuilding aggregate outputs.

## Data ownership

Three layers are deliberately kept separate:

| Layer | Location | Role |
|---|---|---|
| Catalogue source | `DataCatalogue/metadata/.../*.json` | DOI, lifecycle status, retrieval, creators and other source metadata. |
| Human curation | `curation/PN*.json` | Minimal merge patches for reviewed `duc` and `ducProvenance` fields. |
| Complete records | `datasets/PN*.json` | Reproducible combination of catalogue generation and human curation. |

`curation/manifest.json` records the SHA-256 of each complete dataset file at
its last generation or successful capture. This lets generation stop before it
could overwrite an edit that has not yet been captured.

## Generate or synchronize dataset records

A full generation derives every record again from DataCatalogue, reapplies all
saved `curation/PN*.json` patches, and then writes `datasets/PN*.json`:

```bash
python scripts/generate.py --catalogue ../DataCatalogue
```

Incremental generation follows each stored `source.path`, reuses unchanged
records, discovers new datasets and versions, regenerates changed catalogue
sources, and reapplies saved curation:

```bash
python scripts/generate.py --catalogue ../DataCatalogue --incremental
```

Use full generation after changing the generated representation or DUA-to-DUC
mapping logic. Saved manual curation is preserved and applied to the new
representation. If a representation change makes a patch incompatible with the
schema, validation fails so the reviewed patch can be migrated explicitly.

## Review and rebuild aggregate outputs

After reviewing `duc` or `ducProvenance` in `datasets/PN*.json`, rebuild the
README table, `exports/repository-summary.json`, OpenAIRE CERIF export, and
re3data export:

```bash
python scripts/rebuild.py --catalogue ../DataCatalogue
```

Before rebuilding aggregate outputs, `rebuild.py` compares the reviewed records
with a clean catalogue derivation and automatically saves minimal differences
under `curation/`. It never writes to `datasets/`. Only `duc` and
`ducProvenance` are curatable here; corrections to status, retrieval, DOI,
source, version, creators or keywords must be made in DataCatalogue.

The catalogue source hashes must still match. This prevents a catalogue update
from being mistaken for human curation. Versions marked `human-reviewed` are
labelled as reviewed rather than inferred in the generated README table.

The JSON summary is a stable website-facing contract. It contains numeric
dataset and version totals, access counts, participant counts, count coverage,
and documented size in TB to two decimal places. It is generated from the same
statistics as the README summary and is refreshed by both full/incremental
generation and `rebuild.py`.

| JSON field | Meaning |
|---|---|
| `schemaVersion` | Version of this small export contract. |
| `datasets`, `versions` | Repository dataset and published-version totals. |
| `access` | Latest-version counts classified as `open`, `restricted`, or `unclassified`. |
| `participants` | Total, healthy, and inferred patient counts plus the number of datasets reporting both required counts. |
| `documentedSize` | Sum in decimal TB, rounded to two places, plus the number of datasets reporting a size. |

Website clients can fetch the current main-branch export from
`https://raw.githubusercontent.com/Public-nEUro/PublicnEUro-metadata/main/exports/repository-summary.json`.

The capture step can also be run without rebuilding aggregate exports:

```bash
python scripts/capture_overrides.py --catalogue ../DataCatalogue
```

Generation refuses to overwrite files changed since the last generation or
capture. Normally, run `rebuild.py` to preserve them. To intentionally discard
such edits instead:

```bash
python scripts/generate.py \
  --catalogue ../DataCatalogue \
  --discard-manual-changes
```

For a repository checkout in another location:

```bash
python scripts/rebuild.py \
  --catalogue /path/to/DataCatalogue \
  --output /path/to/PublicnEUro-metadata
```

## Validate reviewed records

```bash
python scripts/validate.py
```

Validation checks schema 1.3, URI/date formats, standard DUC fields, and
condition structure. Install development requirements first when needed:

```bash
python -m pip install -r requirements-dev.txt
```

## Run tests

```bash
python -m unittest discover -s tests
```

## Complete data-flow examples

### First generation and review

```bash
# 1. Derive all complete records from scratch.
python scripts/generate.py --catalogue ../DataCatalogue

# 2. Review a generated DUC and mark its provenance human-reviewed.
$EDITOR datasets/PN000005.json

# 3. Capture the review and rebuild README/XML.
python scripts/rebuild.py --catalogue ../DataCatalogue

# 4. Verify everything.
python scripts/validate.py
python -m unittest discover -s tests
```

Step 3 writes only the differences from the catalogue-derived DUC to
`curation/PN000005.json` and records the reviewed dataset hash in the manifest.

### Add new or changed catalogue datasets

```bash
# Existing reviewed DUCs remain applied; new datasets are discovered.
python scripts/generate.py --catalogue ../DataCatalogue --incremental

# Review a new or refreshed record.
$EDITOR datasets/PN000025.json

# Capture that review and refresh aggregate outputs.
python scripts/rebuild.py --catalogue ../DataCatalogue
```

### Change the generated representation

After modifying `generate.py`, its mapping rules, or the dataset schema:

```bash
# Re-derive every dataset using the new representation. Existing curation
# patches are reapplied before the complete records are written.
python scripts/generate.py --catalogue ../DataCatalogue

python scripts/validate.py
python -m unittest discover -s tests
```

Untouched generated fields adopt the new representation. Manually reviewed
DUC fields remain. If the new schema conflicts with an old reviewed value,
validation exposes that record rather than silently deleting its curation.

## Recommended review sequence

1. Run incremental generation to incorporate catalogue changes.
2. Review and edit the relevant `datasets/PN*.json` files.
3. Set `ducProvenance.mappingStatus` to `human-reviewed` where appropriate.
4. Run `scripts/rebuild.py` to capture curation and update README/XML.
5. Run tests and validation, then commit the reviewed records and rebuilt files.
