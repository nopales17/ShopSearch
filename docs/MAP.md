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
│   ├── MAP.md                this file
│   ├── EVIDENCE.md           append-only experimental findings
│   ├── GITHUB_ISSUES.md      historical bootstrap definitions; future remote issue mapping
│   └── adr/                  architecture decision records
├── contracts/
│   ├── catalog.py            item/observation/availability + listing/index/capture states
│   ├── store.py              StoreScope + store record/presentation contracts
│   ├── search.py             query/result contracts
│   ├── telemetry.py          immutable interaction-event contracts
│   └── decision.py           future evidence-aware recommendation contract
├── backend/
│   ├── platform/             persistence layer: connection factory, migrations, paths
│   ├── domain/               pure domain logic
│   ├── catalog/              catalog validation/read model, store-scoped repository, demo import
│   ├── media/                ImageStore + content-addressed local store + EXIF-free derivatives
│   ├── stores/               store registry, hostname resolution, seed + provisioning CLI
│   ├── search/               placeholder + CLIP ranking; vector source; deterministic price parser
│   ├── ingestion/            ingestion adapters
│   ├── telemetry/            local append-only JSONL persistence + read-only report
│   ├── decision/             future SER-style decision logic
│   └── adapters/             local pinned CLIP encoder/model download
├── apps/
│   └── web/                  Flask/Waitress + legacy stdlib HTTP; fixture + pitch UI
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
`backend/telemetry/jsonl_store.py` preserves correlated append-only events with distinct
fixture_test/pitch_demo traffic. `apps/web/wsgi.py` is the production HTTP adapter: it
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

`docs/SLICES.md` owns the ordered implementation slices for the store-scoped platform
transition and their acceptance criteria; `docs/adr/0004-production-runtime.md` and
`docs/adr/0005-store-scoped-platform.md` own the runtime and boundary decisions it
implements. S1 and S2 are implemented: the photographic demo is served by the
Flask/Waitress adapter, and its store record plus hostname resolution come from the
SQLite store registry. S3 is implemented: items, images and item events live in the
store-scoped SQLite catalog, media is content-addressed behind `ImageStore`, and the
storefront, browse, detail and media routes read through `CatalogRepository` and the
media layer. S4-S10 are not implemented: embeddings live only in the committed CLIP
index file read through the compatibility vector source, and telemetry remains JSONL.

`backend/telemetry/report.py` reads a persisted local event JSONL and prints
deterministic demo funnel counts with explicit denominators. It does not infer
availability, demand, customers or purchase outcomes, and it does not write telemetry.

`price.py` now supplies the small typed QueryPlan used by ranking and UI/telemetry.
`tools/expand_pitch_catalog.py` records deterministic CC0 selection in the expansion
manifest. `experiments/search_v0/evaluate_expanded.py` owns the evaluation-only lexical
and fixed hybrid comparison; neither is imported by production ranking.

## Stability rule
If files move or module responsibilities change, update this map in the same change.
