# Repository Map

```text
shopsearch/
├── .github/workflows/ci.yml   Python 3.11/3.12 checks
├── AGENTS.md                 agent operating constraints
├── Makefile                  local run/test/check commands
├── requirements.txt          pinned Flask/Waitress production adapter
├── requirements-dev.txt      pinned lint/type tools
├── requirements-pitch.txt    optional pinned local CLIP runtime
├── README.md                 project entrypoint
├── config/
│   └── development_hosts.json explicit local host-to-store map (no wildcard)
├── docs/
│   ├── CHARTER.md            durable product thesis + boundaries
│   ├── PRODUCT.md            Customer Zero release specification + pending inputs
│   ├── HYPOTHESES.md         test register + dated white-paper source/qualifications
│   ├── STATUS.md             current working memory
│   ├── SLICES.md             platform transition slices + acceptance criteria
│   ├── ROADMAP.md            staged future work + falsification gates
│   ├── ARCHITECTURE.md       module boundaries + invariants
│   ├── CREDENTIALS.md        operator notes for merchant credential handling
│   ├── MAP.md                this file
│   ├── EVIDENCE.md           append-only experimental findings
│   ├── GITHUB_ISSUES.md      historical bootstrap definitions; future remote issue mapping
│   └── adr/                  architecture decision records
├── contracts/
│   ├── auth.py               merchant identity/session contracts
│   ├── catalog.py            item/observation/availability + listing/index/capture states
│   ├── store.py              StoreScope + store record/presentation contracts
│   ├── search.py             query/result contracts
│   ├── telemetry.py          immutable event contract, traffic classes, sink protocol
│   └── decision.py           future evidence-aware recommendation contract
├── backend/
│   ├── platform/             persistence layer: connection factory, migrations, paths
│   ├── domain/               pure domain logic
│   ├── auth/                 merchant credentials, store-scoped sessions, founder CLI
│   ├── catalog/              catalog repository/read model, demo import, merchant publication
│   ├── media/                ImageStore, bounded upload validation, EXIF-free derivatives
│   ├── stores/               store registry, hostname resolution, seed + provisioning CLI
│   ├── search/               ranking + price parser; embedding source/cache; indexer + CLI
│   ├── ingestion/            ingestion adapters
│   ├── telemetry/            store-scoped SQLite sink, JSONL import, read-only reports
│   ├── decision/             future SER-style decision logic
│   └── adapters/             local pinned CLIP encoder/model download
├── apps/
│   └── web/                  Flask/Waitress + legacy stdlib HTTP; storefront + merchant shell
├── data/
│   ├── demo/                 explicitly non-production fixture catalog + store config
│   ├── pitch/                90 CC0 photos, source catalog, selection, expansion manifest and index
│   └── stores/               founder-authored store records (demo store seed)
├── tools/                    photo preparation, expansion, image-index build and demo catalog import
├── experiments/
│   ├── search_v0/            frozen P1 + separate expanded proxy rubric, evaluators/results/protocols
│   └── vision_v0/            future disposable ingestion experiments
└── tests/
    ├── acceptance/           fixture and pitch HTTP/telemetry journeys
    ├── unit/                 validation, typed search and persistence checks
    └── README.md             test strategy and commands
```

`backend/catalog/repository.py` validates fixture records; `pitch.py` validates the
separate permitted photo dataset and provenance against the resolved store.
`backend/search/placeholder.py`
retains Issue #1 token ranking. `multimodal.py` ranks precomputed image vectors using
the local CLIP adapter; `price.py` enforces supported price phrases independently.
`backend/telemetry/jsonl_store.py` preserves correlated append-only events for the retired
Issue #1 fixture slice. `apps/web/wsgi.py` is the production HTTP adapter: it
resolves the request Host, serves the photographic demo through a Flask application
under Waitress and reuses the P1 composition. `pitch_server.py` retains that composition
and the superseded stdlib entry point; `pitch_views.py` and static pitch CSS/JS provide
the UI. `data/local/` holds ignored model weights, preparation files, logs and
content-addressed media derivatives. No dataset represents Customer Zero inventory.
ADR-0003 explains the pitch extension; ADR-0004 selects the WSGI runtime.

`backend/platform/db.py` owns SQLite connections (WAL, `foreign_keys`), the versioned
forward-only migration runner and migration bookkeeping in
`backend/platform/migrations/`. `backend/stores/` owns the store registry: the typed
store record and `StoreScope` (`contracts/store.py`), validation including the
mandatory demo disclosures (`validation.py`), founder-authored config loading
(`config.py`), SQL access (`repository.py`), hostname normalization and resolution
(`hostname.py`, `resolver.py`), idempotent seeding (`seed.py`) and the
store-provisioning CLI (`cli.py`). `data/stores/pitch-demo.json` is the committed
Form & Field store record; `config/development_hosts.json` is the explicit local
host-to-store map. `apps/web/wsgi.py` resolves each request's normalized Host to one
store, returns 404 with no store data for unregistered hosts, and dispatches to that
store's storefront application.

S3 replaces the runtime JSON catalog. `backend/catalog/validation.py` owns the shared
record validation helpers; `read_model.py` owns `LoadedCatalog`, the catalog
representation consumed by views, search and telemetry; `store_repository.py` owns
`CatalogRepository` over the store-scoped `items`, `images` and `item_events` tables
(listing state, independent `index_state`, composite foreign keys, no hard deletes);
`pitch_import.py` idempotently imports the committed demo dataset through the
store registry, rendering each image once. `backend/media/` owns the `ImageStore`
protocol, the content-addressed `LocalImageStore`, `media_url()` and EXIF-aware
derivative generation; no module outside it composes media filesystem paths, and no
served derivative carries EXIF. `backend/search/vector_source.py` supplies embeddings
by item ID while `multimodal.py` keeps cosine ranking and price semantics unchanged.
`data/local/media/` holds ignored content-addressed derivative blobs.
`tools/import_pitch_catalog.py` is the operator entry point for the demo import.

S4 moves embeddings into the store-scoped catalog. The `embeddings` table holds one
opaque little-endian float32 vector per item with explicit `dim`, `model_id`,
`model_revision` and `image_sha256`; `store_generations` holds the per-store catalog
and index counters. `backend/catalog/store_repository.py` also owns those rows, the
generation counters, the index-state transitions and the read-time validity rule (a
row counts as `ready` only while its binding matches the item's current stored image
and the expected model). `backend/search/embedding_import.py` writes the committed
demo vectors into those rows unchanged, bound to the item's stored image.
`backend/search/vector_source.py` now provides the runtime `DatabaseVectorSource`,
cached per store and keyed by both generations, while `CommittedIndexVectorSource`
survives only as the import/parity path. `backend/search/multimodal.py` routes visual
text over ready vectors and serves browse, category and price paths over every
published item, reporting published/ready/excluded coverage. `backend/search/indexer.py`
is the single-purpose indexer (bounded retries with exponential backoff, attempt cap,
recorded last error, listing state untouched) with `python -m backend.search.indexer`
as its CLI. The catalog page's coverage disclosure is rendered by `pitch.js` from the
`/api/search` response so the S1/S2 server-rendered bytes stay unchanged.

`docs/SLICES.md` owns the ordered implementation slices for the store-scoped platform
transition and their acceptance criteria; `docs/adr/0004-production-runtime.md` and
`docs/adr/0005-store-scoped-platform.md` own the runtime and boundary decisions it
implements. S1 and S2 are implemented: the photographic demo is served by the
Flask/Waitress adapter, and its store record plus hostname resolution come from the
SQLite store registry. S3 is implemented: items, images and item events live in the
store-scoped SQLite catalog, media is content-addressed behind `ImageStore`, and the
storefront, browse, detail and media routes read through `CatalogRepository` and the
media layer. S4 is implemented: per-item embeddings live in the store-scoped catalog,
runtime retrieval reads them through a generation-keyed per-store cache, publication
stays independent of index state, and coverage is disclosed and recorded. S5 is
implemented: platform telemetry is store-scoped and validated, with per-store reporting
that keeps demo/fixture and merchant-self traffic out of customer denominators. S6 is
implemented: founder-provisioned merchants, store-scoped sessions, CSRF-protected
sign-in/out and the management shell. S7 is implemented: authenticated photo+price
publication into a live store, with bounded upload validation, capture provenance,
duplicate-byte reuse and indexing handed to the existing indexer. S8-S10 are not
implemented.

S5 moves platform telemetry to the store-scoped `telemetry_events` table (indexed on
`(store_id, search_id)` and `(store_id, occurred_at)`). `backend/telemetry/validation.py`
owns the shared event codec and rules (shape, S4 coverage counts, search attribution);
`sqlite_store.py` provides `SqliteTelemetryStore`/`TelemetryStores` behind the
`TelemetrySink` contract, rejecting foreign-store events and matching demo/live traffic
classes to the store kind. `import_jsonl.py` replays a legacy JSONL log into the sink
with identical event IDs, so `report.summarize()` reproduces earlier counts.
`backend/telemetry/report.py` keeps the demo `summarize()` and adds `summarize_store()`,
a per-store report whose customer denominators exclude demo/fixture and merchant-self
traffic. Reports remain descriptive: it does not infer availability, demand, customers
or purchase outcomes, and it does not write telemetry.

S6 adds founder-provisioned merchant authentication. `backend/auth/` owns passwords
(PBKDF2-HMAC-SHA256, random salt, 600,000 iterations), the store-scoped
`merchants`/`merchant_sessions` SQL (`repository.py`), the per-store `MerchantAuth`
service, the process-local failed-login limiter and the cookie/CSRF helpers
(`service.py`), and the provisioning CLI (`cli.py`: interactive prompts, never
password arguments). `contracts/auth.py` carries `MerchantIdentity`/`MerchantSession`.
`apps/web/manage.py` and `manage_views.py` render the read-only `/manage`,
`/manage/login` and `/manage/logout` shell; `apps/web/wsgi.py` resolves the store and
then that store's merchant session, and classifies public storefront traffic from a
valid session as `merchant_self`. `docs/CREDENTIALS.md` records operator notes.

S7 adds mobile publish. `backend/media/uploads.py` bounds an upload (12 MiB), sniffs the
decoded format (JPEG/PNG/WebP only, no HEIC), rejects a declared content type that
contradicts the bytes, and renders through the existing EXIF-stripping derivative path.
`backend/catalog/publish.py` coordinates validation, media writing and capture
provenance, then calls `CatalogRepository.publish_item_with_image`, which writes the
item, image and item event and bumps the catalog generation exactly once inside one
transaction; a failed publication removes the derivative it wrote. `apps/web/manage.py`
serves the authenticated `/manage/publish` form (photo with camera capture, optional
price/title/category, capture attestation, CSRF), and `apps/web/wsgi.py` refreshes the
cached storefront application whenever the store's catalog generation changes so a new
item is browsable in the same request cycle.

`price.py` now supplies the small typed QueryPlan used by ranking and UI/telemetry.
`tools/expand_pitch_catalog.py` records deterministic CC0 selection in the expansion
manifest. `experiments/search_v0/evaluate_expanded.py` owns the evaluation-only lexical
and fixed hybrid comparison; neither is imported by production ranking.

## Stability rule
If files move or module responsibilities change, update this map in the same change.
