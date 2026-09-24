# PublicnEUro OAI-PMH endpoint

This read-only WSGI service exposes the reviewed `datasets/PN*.json` records
through the six OAI-PMH 2.0 verbs. Each dataset **version** is one record. It
provides `oai_dc` and OpenAIRE's data archive format `oai_datacite` (DataCite
kernel 3.1), with all records in the `openaire_data` set. It exposes metadata
only; controlled files and agreements are never served by this endpoint.

The existing `exports/openaire-cerif.xml` is a static CRIS-format export. It
is **not** an OAI-PMH base URL and should not be entered into OpenAIRE's
registration form for a data repository.

## Run on a server

The site and metadata GitHub repositories contain static files. GitHub Pages
cannot execute this Python application. Run it on the server hosting the
catalogue (or another server with a public HTTPS reverse proxy), and arrange
for its checkout of this repository to be updated after metadata changes.

Example with Gunicorn and Nginx; adjust paths, user, port and hostname to the
actual deployment. Pin a production Gunicorn version in the server's managed
environment.

```sh
git clone https://github.com/Public-nEUro/PublicnEUro-metadata.git /srv/publicneuro-metadata
python3 -m venv /srv/publicneuro-oai-venv
/srv/publicneuro-oai-venv/bin/pip install gunicorn
cd /srv/publicneuro-metadata
OAI_METADATA_ROOT=/srv/publicneuro-metadata \
OAI_BASE_URL=https://datacatalog.publicneuro.eu/oai \
OAI_ADMIN_EMAIL=publicneuro@nru.dk \
  /srv/publicneuro-oai-venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8087 oai.app:app
```

Corresponding Nginx location in the existing HTTPS virtual host:

```nginx
location = /oai {
    proxy_pass http://127.0.0.1:8087;
    proxy_set_header Host $host;
}
```

Manage the Gunicorn command with the server's normal process manager; keep it
bound to localhost. After repository updates, run `git pull --ff-only` in the
server checkout. Record files are read for each request, so no restart is
needed after an update. The service must remain reachable without a login.
An alternative hostname is fine if `OAI_BASE_URL` exactly matches its public
HTTPS URL.

## Validate before registering

```sh
python3 -m unittest oai.test_app
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=Identify'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListMetadataFormats'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListRecords&metadataPrefix=oai_datacite&set=openaire_data'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListIdentifiers&metadataPrefix=oai_datacite&from=2026-01-01'
```

Only after those URLs work publicly, enter
`https://datacatalog.publicneuro.eu/oai` as the **base URL** (without
`?verb=...`) in OpenAIRE. A GitHub `blob`/`raw` URL cannot be a base URL.

OAI datestamps use the later of the source record's `lastUpdated` and its Git
commit date. This ensures manually curated changes are available to incremental
harvesters after the checkout is pulled. The DataCite `publicationYear` is
currently derived from `lastUpdated`; confirm that this is the citation year
intended for each version before registering. Any future metadata record
without a DOI is rejected because DataCite kernel 3 requires a DOI identifier.

OpenAIRE guidance: [OAI-PMH data archive profile](https://guidelines.openaire.eu/en/latest/data/use_of_oai_pmh.html).
