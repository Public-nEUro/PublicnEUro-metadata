# Metadata scripts

The scripts support two distinct workflows: deriving dataset records from the
DataCatalogue and rebuilding aggregate outputs after manual review.

## Generate or synchronize dataset records

A full generation derives every `datasets/PN*.json` record again from the
DataCatalogue:

```bash
python scripts/generate.py --catalogue ../DataCatalogue
```

Incremental generation follows each stored `source.path`, preserves unchanged
reviewed records, and regenerates records whose catalogue source has changed:

```bash
python scripts/generate.py --catalogue ../DataCatalogue --incremental
```

Use full generation after changing generator or DUA-to-DUC mapping logic. Be
aware that it replaces manual corrections in generated dataset records.

## Review and rebuild aggregate outputs

After reviewing or correcting `datasets/PN*.json`, rebuild the README table,
repository summary, OpenAIRE CERIF export, and re3data export without deriving
the dataset records again:

```bash
python scripts/rebuild.py --catalogue ../DataCatalogue
```

`rebuild.py` treats the reviewed files as authoritative and never writes to the
`datasets/` directory. It validates every record before changing aggregate
outputs. The catalogue is read only to recompute access, participant, and size
statistics, which are deliberately not duplicated in the governance records.
Versions marked `human-reviewed` are labelled as reviewed rather than inferred
in the generated README table.

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

## Recommended review sequence

1. Run incremental generation to incorporate catalogue changes.
2. Review and edit the relevant `datasets/PN*.json` files.
3. Set `ducProvenance.mappingStatus` to `human-reviewed` where appropriate.
4. Run `scripts/rebuild.py` to update README and XML aggregates.
5. Run tests and validation, then commit the reviewed records and rebuilt files.
