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

The hostname is a deployment choice. `datacatalog.publicneuro.eu/oai` is used
in these examples because the catalogue already has a dynamic server. If the
server or reverse proxy controlling `publicneuro.eu` can route `/oai` to the
Python process, set `OAI_BASE_URL=https://publicneuro.eu/oai` instead and use
that as the registration URL. The static GitHub Pages site itself cannot
execute Python or proxy OAI requests.

Run the service on a server with a public HTTPS reverse proxy, and keep its
checkout of this metadata repository synchronized with GitHub.

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
bound to localhost. The service must remain reachable without a login.

### Keep records current

Commit generated and reviewed `datasets/PN*.json` records to the metadata
repository's `main` branch. Configure the server's existing GitHub deployment
hook to pull this repository too, or use a periodic sync under the same
non-root account that owns the checkout. For example, this crontab entry
checks for changes every five minutes:

```cron
*/5 * * * * /usr/bin/git -C /srv/publicneuro-metadata pull --ff-only origin main >> /var/log/publicneuro-oai-sync.log 2>&1
```

Choose a writable log location for that account. Monitor failed pulls; keep
the server checkout free of local edits so `--ff-only` succeeds. The service
reads the dataset JSON files on every request. Once the pull completes, new
datasets and edits are served without restarting Gunicorn, subject to
OpenAIRE's own harvesting schedule. A push to `DataCatalogue` alone does not
change these records: run the metadata repository's generation or incremental
update workflow, review, and commit its resulting JSON files first.

## Validate before registering

```sh
python3 -m unittest oai.test_app
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=Identify'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListMetadataFormats'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListRecords&metadataPrefix=oai_datacite&set=openaire_data'
curl -fsS 'https://datacatalog.publicneuro.eu/oai?verb=ListIdentifiers&metadataPrefix=oai_datacite&from=2026-01-01'
```

Only after those URLs work publicly, enter the deployed URL as the **base
URL** (without `?verb=...`) in OpenAIRE. For a root-domain deployment, replace
`https://datacatalog.publicneuro.eu/oai` throughout with
`https://publicneuro.eu/oai`. A GitHub `blob`/`raw` URL cannot be a base URL.

OAI datestamps use the later of the source record's `lastUpdated` and its Git
commit date. This ensures manually curated changes are available to incremental
harvesters after the checkout is pulled. The DataCite `publicationYear` is
currently derived from `lastUpdated`; confirm that this is the citation year
intended for each version before registering. Any future metadata record
without a DOI is rejected because DataCite kernel 3 requires a DOI identifier.

OpenAIRE guidance: [OAI-PMH data archive profile](https://guidelines.openaire.eu/en/latest/data/use_of_oai_pmh.html).
