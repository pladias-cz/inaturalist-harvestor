# iNaturalist harvestor

Cronjob to harvest iNaturalist observations of a specific project
and store them in PostgreSQL, resolving the referenced taxa against
ChecklistBank (Catalogue of Life).

## Usage

```shell
docker build . -t harvest
docker run --env-file .env harvest
```

Or run directly from a checkout:

```shell
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt


set -a
source .env
set +a
python -m inaturalist_harvestor
```

Apply `structure.sql` to the target database once before the first run.

## Configuration

All settings come from environment variables (see `sample.env`):

| Variable             | Required | Default                               | Description                                    |
| -------------------- | -------- | ------------------------------------- | ---------------------------------------------- |
| `INAT_USERNAME`      | yes      |                                       | iNaturalist account used for the OAuth grant   |
| `INAT_PASSWORD`      | yes      |                                       | Password of that account                       |
| `INAT_CLIENT_ID`     | yes      |                                       | OAuth client ID                                |
| `INAT_CLIENT_SECRET` | yes      |                                       | OAuth client secret                            |
| `DATABASE_URL`       | yes      |                                       | PostgreSQL connection string                   |
| `IMPORT_MODE`        | no       | `daily`                               | `daily` (incremental) or `full`                 |
| `INAT_PROJECT_ID`    | no       | `183334`                              | Harvested iNaturalist project                  |
| `INAT_PER_PAGE`      | no       | `200`                                 | Page size of the observation API (v2 caps it at 200) |
| `REQUEST_DELAY`      | no       | `1`                                   | Seconds between paginated API requests         |
| `CHECKLISTBANK_REQUEST_DELAY` | no | `0.2`                          | Seconds between ChecklistBank resolution requests |
| `CHECKLISTBANK_API_URL` | no    | `https://api.checklistbank.org`      | ChecklistBank API base URL                     |
| `CHECKLISTBANK_DATASET_ID` | no | `139831`                              | ChecklistBank dataset id of iNaturalist        |
| `CHECKLISTBANK_DATASET_KEY` | no | `3LR`                                 | ChecklistBank key of the target checklist (CoL) |
| `INAT_SITE_URL`      | no       | `https://www.inaturalist.org`         | iNaturalist site URL                           |
| `INAT_API_URL`       | no       | `https://api.inaturalist.org/v2`      | iNaturalist API base URL                      |
| `USER_AGENT`         | no       | `pladias-inaturalist-importer/1.0`    | User-Agent header for outgoing requests        |
| `LOG_LEVEL`          | no       | `INFO`                                | Logging level                                  |

### Import modes

* `daily` — imports observations created since the last stored
  `created_at`, overlapped by 3 days for robustness. Falls back to
  a full import when the database is empty.
* `full` — re-synchronizes all project observations and marks
  records no longer present in the project (`in_project = false`).

After the import, every taxon in state `pending` is resolved against
ChecklistBank: the iNaturalist taxon is looked up in the iNaturalist
dataset (139831) and the related usage with status `accepted` in the
target dataset (`3LR`, Catalogue of Life) is stored in `col_id`.

## Architecture

```
inaturalist_harvestor/
├── cli.py                     composition root: wiring + logging
├── config.py                  validated settings from environment
├── models.py                  domain models (Observation, Taxon, ColResolution)
├── http.py                    HTTP client with 429 rate-limit back-off
├── clients/
│   ├── inaturalist.py         OAuth → JWT auth + paginated harvesting
│   └── checklistbank.py       ChecklistBank name-usage resolution
├── db/
│   ├── schema.py              physical table names (single source of truth)
│   ├── connection.py          connection / transaction management
│   ├── observations.py        observation repository (upsert, prune)
│   └── taxa.py                taxon repository (upsert, resolution)
└── services/
    ├── import_service.py      daily / full import orchestration
    └── taxon_resolution.py    pending-taxon resolution pipeline
```

The layers depend only inwards: `cli` → `services` → (`clients`, `db`) →
(`models`, `config`). All SQL lives in the `db` package, all external
API access in `clients`, and each service is injected with its
dependencies, so components can be replaced or tested in isolation.

## Development

```shell
python -m unittest discover -s tests -v
```
