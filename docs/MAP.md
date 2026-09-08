# Repository Map

```text
shopsearch/
├── AGENTS.md                 agent operating constraints
├── README.md                 project entrypoint
├── docs/
│   ├── CHARTER.md            durable product thesis + boundaries
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
│   ├── catalog/              catalog implementation
│   ├── search/               retrieval/ranking implementation
│   ├── ingestion/            ingestion adapters
│   ├── telemetry/            event persistence/aggregation
│   ├── decision/             future SER-style decision logic
│   └── adapters/             DB/model/external-provider integrations
├── apps/
│   └── web/                  customer + lightweight owner UI
├── data/
│   ├── demo/                 local demo records/images metadata
│   └── fixtures/             deterministic test fixtures
├── experiments/
│   ├── search_v0/            disposable retrieval experiments
│   └── vision_v0/            future disposable ingestion experiments
└── tests/
    ├── unit/
    ├── integration/
    └── acceptance/
```

## Stability rule
If files move or module responsibilities change, update this map in the same change.
