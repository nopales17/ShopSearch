# Repository Map

```text
shopsearch/
├── .github/workflows/ci.yml   Python 3.11/3.12 checks
├── AGENTS.md                 agent operating constraints
├── Makefile                  local run/test/check commands
├── requirements-dev.txt      pinned lint/type tools
├── requirements-pitch.txt    optional pinned local CLIP runtime
├── README.md                 project entrypoint
├── docs/
│   ├── CHARTER.md            durable product thesis + boundaries
│   ├── PRODUCT.md            Customer Zero release specification + pending inputs
│   ├── HYPOTHESES.md         test register + dated white-paper source/qualifications
│   ├── STATUS.md             current working memory
│   ├── ROADMAP.md            staged future work + falsification gates
│   ├── ARCHITECTURE.md       module boundaries + invariants
│   ├── MAP.md                this file
│   ├── EVIDENCE.md           append-only experimental findings
│   ├── GITHUB_ISSUES.md      historical bootstrap definitions; future remote issue mapping
│   └── adr/                  architecture decision records
├── contracts/
│   ├── catalog.py            item/observation/availability contracts
│   ├── search.py             query/result contracts
│   ├── telemetry.py          immutable interaction-event contracts
│   └── decision.py           future evidence-aware recommendation contract
├── backend/
│   ├── domain/               pure domain logic
│   ├── catalog/              separate fixture and photographic-demo validation/loading
│   ├── search/               placeholder + CLIP ranking; deterministic price parser
│   ├── ingestion/            ingestion adapters
│   ├── telemetry/            local append-only JSONL persistence
│   ├── decision/             future SER-style decision logic
│   └── adapters/             local pinned CLIP encoder/model download
├── apps/
│   └── web/                  shared stdlib HTTP; fixture + photographic pitch UI
├── data/
│   ├── demo/                 explicitly non-production fixture catalog + store config
│   └── pitch/                90 CC0 photos, source catalog, selection, expansion manifest and index
├── tools/                    photo preparation, mechanical expansion and offline image-index build
├── experiments/
│   ├── search_v0/            frozen P1 + separate expanded proxy rubric, evaluators/results/protocols
│   └── vision_v0/            future disposable ingestion experiments
└── tests/
    ├── acceptance/           fixture and pitch HTTP/telemetry journeys
    ├── unit/                 validation, typed search and persistence checks
    └── README.md             test strategy and commands
```

`backend/catalog/repository.py` validates fixture records; `pitch.py` validates the
separate permitted photo catalog and provenance. `backend/search/placeholder.py`
retains Issue #1 token ranking. `multimodal.py` ranks precomputed image vectors using
the local CLIP adapter; `price.py` enforces supported price phrases independently.
`backend/telemetry/jsonl_store.py` preserves correlated append-only events with distinct
fixture_test/pitch_demo traffic. `apps/web/pitch_server.py` reuses the Issue #1 HTTP
boundary and composes the photographic demo; `pitch_views.py` and static pitch CSS/JS
provide the UI. `data/local/` holds ignored model weights, preparation files and logs.
No dataset represents Customer Zero inventory. ADR-0003 explains the pitch extension.

`price.py` now supplies the small typed QueryPlan used by ranking and UI/telemetry.
`tools/expand_pitch_catalog.py` records deterministic CC0 selection in the expansion
manifest. `experiments/search_v0/evaluate_expanded.py` owns the evaluation-only lexical
and fixed hybrid comparison; neither is imported by production ranking.

## Stability rule
If files move or module responsibilities change, update this map in the same change.
