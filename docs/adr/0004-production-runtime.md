# ADR-0004: Production runtime and persistence for the store-scoped platform

## Status
Accepted 2026-09-18 by founder decision during the platform transition review.

Extends ADR-0001 (one deployable boundary) and ADR-0003 (local precomputed CLIP
retrieval). Supersedes ADR-0002's runtime and storage constraints **for production
callers only**; ADR-0002 remains an accurate record of the Issue #1 fixture slice until
that slice is retired (see `docs/SLICES.md`, S10).

## Context
The pitch demo runs a loopback standard-library HTTP server over an immutable,
hash-validated JSON catalog, a single whole-catalog CLIP index file and an append-only
JSONL event log with a process-local writer lock.

The platform transition requires a mutable catalog, merchant image upload, merchant
authentication, durable image storage, multiple founder-provisioned stores and public
hosting. ADR-0002 already names the trigger: "Public deployment needs a production HTTP
adapter and persistent storage configuration; that can retain the same internal modules
and one deployment boundary." That caller now exists.

Three properties of the current runtime are disqualifying for that caller, not merely
inconvenient: the standard-library server is documented as not hardened for public
hosting; the JSONL writer revalidates by rescanning the whole log on every append; and
the retrieval index binds to a whole-catalog hash and a positional item list, which a
mutable catalog invalidates on every change.

## Decision

### One deployable boundary
Unchanged. One repository, one process, explicit internal modules, typed contracts,
external providers behind adapters.

### Selected initial implementations
These are **selected initial deployment implementations behind adapters, not product
architecture**. Each is expected to be replaceable without changing domain modules,
contracts or public behavior.

| Concern | Initial implementation | Adapter/boundary it sits behind |
|---|---|---|
| HTTP | WSGI application (Flask) served by Waitress | `apps/web` adapter; domain modules stay HTTP-independent |
| TLS/ingress | Caddy reverse proxy, automatic ACME | deployment configuration only; no application dependency |
| Relational storage | SQLite in WAL mode, one file | repository protocols in `backend/*`; see portability rules |
| Image bytes | content-addressed local filesystem store | `ImageStore` protocol + `media_url()` indirection |
| Embedding vectors | per-item rows (BLOB) + in-process cosine | vector-source protocol; ranking code unchanged |
| Telemetry | same validated event contract, SQLite-backed | `TelemetrySink` protocol; `report.summarize()` unchanged |

Waitress is chosen over a forking server so the CLIP model is loaded once per process
rather than once per worker. Caddy terminates TLS for one or more store hostnames.

### Retrieval is not redesigned
`backend/search/price.py` semantics, cosine ranking over stored image vectors, the
bounded semantic candidate set for price sorts and deterministic constraint enforcement
are unchanged. Only the vector source and the store scope change. Expensive model work
stays at indexing time; customer search reads stored vectors.

The whole-catalog index fingerprint is replaced by a per-item binding: an embedding row
is valid only while its `(model_id, model_revision, image_sha256)` match the item's
current image. Staleness remains detectable; catalog mutation no longer invalidates the
entire index. Catalog authority does not depend on this index; see ADR-0005.

### Portability rules (binding on implementers)
The point of these rules is that migration to PostgreSQL and object storage stays a
configuration and adapter change rather than a rewrite.

- All SQL lives in repository modules. No SQL and no `sqlite3` import outside the
  persistence layer (`backend/platform/`, repository modules). Raw connections are never
  passed to web, view, search-ranking or tooling code.
- Prefer standard SQL. No `INSERT OR REPLACE`, no `rowid`/implicit-identity semantics, no
  cross-table triggers, no SQLite-only functions in repository queries. Where an upsert is
  needed, write it explicitly and keep it in one place.
- Identifiers are application-generated opaque strings (UUID4 text), never autoincrement
  integers.
- Timestamps are stored as ISO-8601 text with an explicit UTC offset. Money is stored as
  decimal text and parsed with `Decimal`; floats are never used for price.
- Embedding vectors are stored as an opaque BLOB plus explicit `dim`, `model_id` and
  `model_revision`. No vector-index extension is assumed; pgvector or similar would be a
  later optimization, not a contract change.
- Image bytes are addressed by `(store_id, sha256, variant)` and referenced through
  `media_url()`. No code composes filesystem paths for media outside the image store.
- Schema changes are versioned, forward-only SQL migration files applied by a runner that
  records applied versions; migrations are re-runnable without duplicating rows.

### Operational requirements for public hosting
Configuration and secrets from the environment; nightly database backup plus media
synchronisation to a second location; a documented and executed restore drill; structured
operational logging kept distinct from customer telemetry; a health endpoint covering
database and media reachability; upload byte caps; login rate limiting.

## Consequences
Positive: mutable catalogs, uploads, authentication and multiple stores become possible
without service decomposition; attribution lookups become indexed instead of linear;
backup is a file copy; the demo keeps working throughout the transition.

Negative: runtime dependencies are added (Flask, Waitress; Pillow was already pinned) and
the pinned PyTorch/Transformers CLIP runtime becomes a production dependency, which sets a
real hosting floor of roughly 2-4 GB RAM and a persistent volume. Single-file SQLite means
one writer host. The portability rules cost some convenience.

## Revisit when
Any of the following is observed rather than anticipated: sustained write contention or
lock timeouts under real traffic; a need for more than one application host or process;
database size or backup window becoming operationally painful; media volume exceeding the
host disk or needing CDN delivery; a reporting or analytics caller that SQLite cannot
serve. At that point migrate the relevant adapter (PostgreSQL, object storage) and record
the decision; do not pre-build for it now.
