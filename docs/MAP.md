# Repository Map

```text
shopsearch/
├── .github/workflows/ci.yml   Python 3.11/3.12 checks
├── AGENTS.md                 agent operating constraints
├── Makefile                  local run/test/check commands
├── requirements-dev.txt      pinned lint/type tools; no runtime dependencies
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
│   ├── GITHUB_ISSUES.md      first six implementation issues
│   └── adr/                  architecture decision records
├── contracts/
│   ├── catalog.py            item/observation/availability contracts
│   ├── search.py             query/result contracts
│   ├── telemetry.py          immutable interaction-event contracts
│   └── decision.py           future evidence-aware recommendation contract
├── backend/
│   ├── domain/               pure domain logic
│   ├── catalog/              fixture catalog validation/loading
│   ├── search/               deterministic placeholder ranking
│   ├── ingestion/            ingestion adapters
│   ├── telemetry/            local append-only JSONL persistence
│   ├── decision/             future SER-style decision logic
│   └── adapters/             DB/model/external-provider integrations
├── apps/
│   └── web/                  stdlib customer fixture UI + server/static CSS
├── data/
│   └── demo/                 explicitly non-production fixture catalog + store config
├── experiments/
│   ├── search_v0/            disposable retrieval experiments
│   └── vision_v0/            future disposable ingestion experiments
└── tests/
    ├── acceptance/           end-to-end fixture browser/telemetry test
    ├── unit/                 validation, typed search and persistence checks
    └── README.md             test strategy and commands
```

`backend/catalog/repository.py` validates fixture catalog records. `backend/search/placeholder.py` supplies deliberately non-semantic token ranking. `backend/telemetry/jsonl_store.py` persists append-only local JSONL event snapshots. `apps/web/server.py` composes those modules into the current one-process web application. `data/local/` is ignored runtime data. Contracts now include current store/session/search correlation fields; they do not yet provide production policy enforcement. All current catalog records and rendered visual cards are fixtures, not Customer Zero inventory.

## Stability rule
If files move or module responsibilities change, update this map in the same change.
