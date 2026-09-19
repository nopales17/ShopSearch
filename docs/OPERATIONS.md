# Operations

Operator guide for the selected local runtime: one Waitress process behind Caddy,
SQLite in WAL mode and a local content-addressed media tree (ADR-0004). Everything
here is provider-neutral. No hostname, credential, certificate or bucket is committed,
and nothing in this repository has been deployed publicly.

## Topology

```
internet -> Caddy (TLS, exact hostname) -> 127.0.0.1:8000 (Waitress) -> SQLite + media
```

`apps/web/wsgi.py` resolves every request's `Host` header through the store registry. A
hostname that is not registered, or that resolves to a store outside
`SHOPSEARCH_STORES`, gets a 404 that carries no store data. There is no default store,
no wildcard host and no first-match fallback. `/health` is answered before hostname
resolution.

## Runtime configuration

Production startup reads only these variables and fails closed when a required one is
missing or invalid; it never falls back to the pitch demo or to repository defaults.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SHOPSEARCH_DATABASE` | yes | absolute path of the SQLite database file |
| `SHOPSEARCH_MEDIA_ROOT` | yes | absolute path of the content-addressed media root |
| `SHOPSEARCH_STORES` | yes | comma-separated store IDs this process serves |
| `SHOPSEARCH_BIND_HOST` | no | bind address, default `127.0.0.1` (loopback behind Caddy) |
| `SHOPSEARCH_PORT` | no | bind port, default `8000` |
| `SHOPSEARCH_LOG_LEVEL` | no | standard logging level name, default `INFO` |
| `SHOPSEARCH_BACKUP_ROOT` | for backup | snapshot destination used by the backup command |
| `SHOPSEARCH_DEVELOPMENT_HOSTS` | no | explicit local host-to-store map, development only |

`deploy/shopsearch.env.example` lists the same names with placeholders. There is no
secret in this list: the application has no Flask client-side session, so no
`SECRET_KEY` exists to invent. Merchant passwords are provisioned interactively
(`docs/CREDENTIALS.md`) and the only cookie values are opaque random tokens whose
hashes live in the database.

Errors are explicit, for example:

```
configuration error: SHOPSEARCH_STORES is required: list the store IDs this process
serves, comma separated; there is no default store
```

## Directories, ownership and permissions

| Path | Purpose | Ownership |
| --- | --- | --- |
| `/opt/shopsearch` | checked-out application and `.venv` | `root:root`, read-only to the service |
| `/etc/shopsearch/shopsearch.env` | environment file | `root:shopsearch` `0640` |
| `/var/lib/shopsearch/shopsearch.sqlite3` | catalog, media metadata, embeddings, telemetry, merchants | `shopsearch:shopsearch` `0640` |
| `/var/lib/shopsearch/media/<store_id>/...` | content-addressed image bytes | `shopsearch:shopsearch` `0755` dirs / `0644` files |
| `/mnt/shopsearch-backup` | backup snapshot destination | independent failure domain |
| journal (`journalctl -u shopsearch`) | operational logs | host policy |

The service unit runs as an unprivileged `shopsearch` account with `ProtectSystem=strict`
and only `/var/lib/shopsearch` and `/var/log/shopsearch` writable.

## Install (generic Linux, systemd + Caddy)

```sh
# 1. Application and virtualenv
install -d /opt/shopsearch /etc/shopsearch /var/lib/shopsearch
git clone <repository> /opt/shopsearch && cd /opt/shopsearch
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-pitch.txt
.venv/bin/python -m backend.adapters.clip          # pinned model weights

# 2. Configuration
install -m 0640 deploy/shopsearch.env.example /etc/shopsearch/shopsearch.env
$EDITOR /etc/shopsearch/shopsearch.env            # replace every placeholder
chown -R shopsearch:shopsearch /var/lib/shopsearch

# 3. Service and proxy
install -m 0644 deploy/systemd/shopsearch.service /etc/systemd/system/
install -m 0644 deploy/systemd/shopsearch-backup.service /etc/systemd/system/
install -m 0644 deploy/systemd/shopsearch-backup.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now shopsearch.service
systemctl enable --now shopsearch-backup.timer
SHOPSEARCH_DOMAIN=store.example.com SHOPSEARCH_ACME_EMAIL=ops@example.com \
  caddy run --config deploy/Caddyfile
```

Store records and catalogs are founder-provisioned; this repository ships no automated
provisioning of a customer store. The Form & Field pitch demo is provisioned only by
the explicit demo command below.

## Commands

| Command | Purpose |
| --- | --- |
| `make serve PYTHON=.venv/bin/python` | production WSGI process from `SHOPSEARCH_*` configuration |
| `make demo PYTHON=.venv/bin/python` | explicit interactive local Form & Field demo (seeds/imports the pitch data into its own runtime root) |
| `make demo-reset PYTHON=.venv/bin/python` | delete only the dedicated demo runtime root and rebuild the pristine baseline |
| `make backup PYTHON=.venv/bin/python` | consistent snapshot + media synchronisation + verification |
| `make restore PYTHON=.venv/bin/python` | restore a snapshot onto a clean destination |
| `.venv/bin/python -m backend.search.indexer --store-id <id>` | process `pending`/`failed` items |
| `.venv/bin/python -m backend.auth.cli --store-id <id> ...` | founder provisioning of merchant accounts |
| `make report PYTHON=.venv/bin/python` | read-only local funnel report |
| `make check PYTHON=.venv/bin/python` | compile, lint, format, mypy and the full test suite |

## Health

`GET /health` performs a trivial read through the catalog repository and checks that the
configured media root is a usable directory through the media adapter. Healthy → `200`
with body `ok`; database failure → `503 database unavailable`; media failure →
`503 media unavailable`. The body is generic on purpose: no path, SQL error, store
datum or secret is returned, and health probes write no telemetry.

```
curl -sS -i https://store.example.com/health
```

## Interactive local demo runtime (`make demo` / `make demo-reset`)

The interactive Form & Field demo is the one deliberately disposable runtime. Its
database, media and process record live in an ignored, dedicated root that is never
shared with the production or generic local paths:

```
data/local/form-and-field-demo/
├── shopsearch.sqlite3     demo store record, committed catalog, uploads, telemetry
├── media/                 content-addressed demo derivatives
└── demo.pid               recorded while a demo process owns this runtime
```

`make demo PYTHON=.venv/bin/python` starts the demo from that root. If it does not exist
it is created, Form & Field is seeded, the committed 90-item catalog and its 90 embeddings
are imported, and the local `demo`/`demo` credential is provisioned through the normal
merchant-auth machinery. If it does exist, local uploads and edits are preserved and only
the credential is re-established, which revokes earlier demo sessions. Startup prints the
storefront URL, the merchant sign-in URL and the credential.

`make demo-reset PYTHON=.venv/bin/python` stops nothing, but refuses to run while the
recorded demo process is alive. It then deletes only `data/local/form-and-field-demo/`,
rebuilds the pristine 90-item / 90-ready-embedding baseline plus the credential, verifies
the counts and the credential, prints them, and exits without starting the server. It
never touches `data/local/shopsearch.sqlite3`, `data/local/media/`, model weights,
committed files, another store or any configured production path. It is not a production
catalog deletion path: production catalogs append item events and never hard-delete. A
stale `demo.pid` left by a crashed demo is treated as stopped, and the command refuses any
directory whose name is not `form-and-field-demo`.

## Operational logging

The service writes one JSON object per line through the standard library logging stack
(`shopsearch.operational`), separately from behavioral telemetry:

```json
{"duration_ms": 3.1, "event": "request", "level": "INFO", "method": "GET",
 "path": "/api/search", "status": 200, "store_id": "live-store", "timestamp": "..."}
```

Logged: startup with the resolved configuration, shutdown, migration/startup failure,
request method + path + status + duration + resolved store, health failures,
backup/restore outcome and outcome of the indexer CLI. Never logged: passwords, raw
session cookies, CSRF tokens, request bodies, uploaded bytes, full header dumps, or
query strings (so the log cannot become a second behavioral telemetry stream).
Telemetry stays in the store-scoped `telemetry_events` table.

## Backup

`python -m backend.ops.runtime_backup` writes one snapshot directory:

```
$SHOPSEARCH_BACKUP_ROOT/
  database.sqlite3     # transaction-consistent image via SQLite's online backup API
  media/               # mirrored content-addressed tree (<store_id>/<sha256>/<variant>)
```

It never `cp`s a live WAL database. After copying, it re-reads the snapshot read-only
and fails if any `images` row in that snapshot does not resolve to backed-up bytes.
Retention/pruning is intentionally not implemented here; that is a separate operational
policy decision, and a destination on the application host alone does not survive host
loss.

## Restore

```sh
SHOPSEARCH_DATABASE=/srv/restore/shopsearch.sqlite3 \
SHOPSEARCH_MEDIA_ROOT=/srv/restore/media \
SHOPSEARCH_STORES=live-store \
  .venv/bin/python -m backend.ops.runtime_restore \
    --backup-root /mnt/shopsearch-backup
```

Restores refuse a destination database that exists, or a non-empty destination media
root, unless `--allow-existing` is passed explicitly for a known-dead target. After
copying, the restored database is re-read read-only and every image row must resolve to
restored bytes, or the command fails.

### Executed local restore drill (2026-09-18)

Run on this workstation against the synthetic two-store isolation fixture (see
`tests/acceptance/test_backup_restore.py` for the automated form). Representative state
was created by provisioning the fixture, then starting the production entry point
`python -m apps.web.wsgi` with `SHOPSEARCH_*` variables pointing at it and browsing /
searching both hostnames.

```sh
# 1. Representative state: two stores, their catalogs/media/embeddings, telemetry
python -m backend.adapters.clip        # once, for the pinned model weights
<fixture provisioning>                 # tests/support/isolation_fixture.provision_isolation_stores

# 2. Original runtime: serve both hostnames and record traffic
SHOPSEARCH_DATABASE=/srv/drill/data/shopsearch.sqlite3 \
SHOPSEARCH_MEDIA_ROOT=/srv/drill/data/media \
SHOPSEARCH_STORES=isolation-alpha,isolation-beta \
  .venv/bin/python -m apps.web.wsgi            # browse + search each hostname

# 3. Back up while that database is live in WAL mode
SHOPSEARCH_DATABASE=/srv/drill/data/shopsearch.sqlite3 \
SHOPSEARCH_MEDIA_ROOT=/srv/drill/data/media \
SHOPSEARCH_STORES=isolation-alpha,isolation-beta \
SHOPSEARCH_BACKUP_ROOT=/srv/drill/backup \
  .venv/bin/python -m backend.ops.runtime_backup

# 4. More traffic on the original, then close the original process

# 5. Restore into a fresh clean directory and start solely from it
SHOPSEARCH_DATABASE=/srv/drill/restored/shopsearch.sqlite3 \
SHOPSEARCH_MEDIA_ROOT=/srv/drill/restored/media \
SHOPSEARCH_STORES=isolation-alpha,isolation-beta \
  .venv/bin/python -m backend.ops.runtime_restore --backup-root /srv/drill/backup
SHOPSEARCH_DATABASE=/srv/drill/restored/shopsearch.sqlite3 \
SHOPSEARCH_MEDIA_ROOT=/srv/drill/restored/media \
SHOPSEARCH_STORES=isolation-alpha,isolation-beta \
  .venv/bin/python -m apps.web.wsgi            # browse + search each hostname again
```

Observed result, from the recorded run:

| Step | Observed |
| --- | --- |
| original runtime | both hostnames 200 on `/catalog`, search returned 3 items with `coverage published=3 ready=3 excluded_unindexed=0`, detail 200, media 200 |
| original counts | each served store: 3 items, 3 images, 0 item-events, 7 telemetry rows (the unprovisioned fixture store: 0) |
| live journal mode | `wal` — a live WAL database, so a file copy would not be a snapshot |
| backup | `backup ok: 3 stores, 6 image rows, 6 media files written`; snapshot contained exactly `database.sqlite3` + `media/` |
| snapshot journal mode | `delete` (single self-contained file, no WAL sidecar) |
| more traffic, then close | original telemetry grew to 14 rows each, so the snapshot is provably an earlier point in time |
| restore into clean dir | `restore ok: 3 stores, 6 image rows` |
| restored state | identical to the snapshot: 3 items / 3 images / 0 item-events / 7 telemetry rows each |
| restored runtime | started solely from the restored database and media root: `/catalog` 200, search count 3, detail 200, media 200 for both hostnames |
| restore over non-empty destination | refused: `restore failed ... already exists; restore onto a clean destination or pass --allow-existing to overwrite it deliberately` (exit 1) |
| restore with a missing mirrored blob | refused by the same verification step (`tests/acceptance/test_backup_restore.py`) |

Restart persistence is proven separately by
`tests/acceptance/test_backup_restore.py::RestartPersistenceTest`: publish an item,
browse, stop every repository/server handle, reopen the same paths and confirm the
item, its media, its item event and the persisted telemetry are all still there.

## Indexing

Publication never waits for indexing; a pending item is browsable immediately. Run the
existing single-purpose indexer as an operator step (no daemon, no queue):

```sh
.venv/bin/python -m backend.search.indexer --store-id live-store
.venv/bin/python -m backend.search.indexer --store-id live-store --reset-failed
```

## ADR-0004 migration and revisit triggers

The selected implementations are substitution points behind adapters, not permanent
architecture:

- **SQLite → PostgreSQL** when more than one application host needs the same data, a
  write pattern exceeds one writer's comfort, or backup/restore windows stop fitting
  the catalogue; the repository layer is the only place that speaks SQL.
- **Local media → object storage** when the media tree stops fitting the volume, when
  two hosts must serve the same bytes, or when off-host delivery needs a CDN; the
  `ImageStore` adapter is the only place that composes media paths.
- **One process → multiple hosts** when a single Waitress process is not enough for
  availability or latency; that requires SQLite to move first, session affinity or a
  shared session store, and a shared media backend.
- Revisit the reverse proxy/TLS choice if the host platform provides managed
  termination, and the logging destination if the host has no journal.

## Not done externally

Implemented and locally verified in this repository: the runtime, configuration
boundary, deployment templates, health endpoint, operational logging, backup/restore
commands, nightly timer definition, the local restore drill and the restart test.

Not done, and not claimed: hosting provider chosen or provisioned; production VM
created; DNS or domain configured; TLS certificate actually issued; independent
off-host backup destination configured; Customer Zero publication permission; verified
business/store content; commercial terms; public telemetry retention, access and notice
decision; public launch. Caddy and systemd were not available on the development
machine, so their configuration syntax was reviewed by hand but not validated by
`caddy validate` or `systemd-analyze verify`.
