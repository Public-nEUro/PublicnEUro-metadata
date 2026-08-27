# DUA-to-DUC mapping

`dua_to_duc.json` is the versioned, auditable rule set used to infer Digital
Use Conditions from the Data User Agreement fields in DataCatalogue records.

## How mapping works

Each rule contains:

- `id`: stable mapping-rule identifier;
- `patterns`: case-insensitive regular expressions searched in the DUA
  `Restrictions` and `Terms` sections;
- `conditionTerm`: an atomic condition label;
- `rule`: one of `Permitted`, `Obligatory`, `Forbidden`, or `No Requirement`;
- `scope`: `Whole of asset` or `Part of asset`;
- optional `conditionParameter`: a qualification that does not fit in the
  atomic condition term.

The generator emits at most one condition for each mapping rule. The standard
DUC profile is stored in `duc`; PublicnEUro-specific evidence is stored in the
sibling `ducProvenance` object. It does not publish the DUA text. Instead,
`ducProvenance.sourceAgreement.sha256` fingerprints the text used for
generation and its URL links to the authoritative catalogue record.

## Permission model

All generated profiles use:

```json
"permissionMode": "All unstated conditions are Permitted"
```

Consequently, the mapper adds only meaningful explicit permissions,
obligations, and prohibitions. Missing text does not generate `No Requirement`.
Ethics approval is not inferred from general legal-compliance language and is
only to be added if a dataset agreement explicitly makes it a reuse condition.

## Review workflow

Generated profiles start as `machine-generated-unreviewed`. A reviewer should:

1. compare every condition with the authoritative DUA;
2. confirm that no material clause is missing or incorrectly mapped;
3. add vocabulary URIs where appropriate;
4. change the status to `human-reviewed` and record that review through the
   normal Git history.

When a DUA changes, its SHA-256 fingerprint changes and regeneration produces a
visible diff. Updating a mapping rule requires incrementing `mappingVersion`
and adding or updating tests.
