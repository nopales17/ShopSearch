# Architecture

## Style
Start as a modular monolith.

Do not introduce microservices until independently deployable boundaries are justified by real operational pressure.

## Core flow

```text
manual catalog / later photo ingestion
                ↓
            observations
                ↓
          catalog representation
                ↓
      embeddings + structured metadata
                ↓
              search
                ↓
          customer results
                ↓
            telemetry
```

Later:

```text
photos / invoices / POS / web behavior
                ↓
          evidence-producing adapters
                ↓
         scoped epistemic state
                ↓
        operational decision layer
```

## Boundary rules

### Catalog
Owns:
- product representation
- item identity
- observation references
- public representation fields

Does not own:
- search ranking
- operational recommendations

### Search
Owns:
- query interpretation for retrieval
- semantic ranking
- deterministic filter application
- result scoring

Does not own:
- availability truth
- catalog mutation
- operational recommendations

### Ingestion
Owns:
- converting external observations into typed candidates/observations

Does not own:
- final authority over inventory truth

### Telemetry
Owns:
- immutable interaction events
- event context

Does not own:
- business conclusions

### Decision
Later owns:
- scoped claims
- evidence references
- limitations
- action status
- probe/recommend distinctions

Does not own:
- raw data ingestion

## Important semantic distinction

Never collapse these:

1. Observation:
   "This object was visible in photo P at time T."

2. Catalog identity:
   "This observation likely corresponds to item I."

3. Availability:
   "Item I is believed available under evidence state S."

4. Customer-facing claim:
   "Recently seen in store."

5. Operational inference:
   "This category may be undersupplied."

Each is a separate claim with different support.

## Initial storage
For Phase 1:
- JSON/SQLite is sufficient for the demo catalog and telemetry.
- FAISS or brute-force cosine similarity is sufficient for small retrieval sets.

Do not add distributed infrastructure.

## Model strategy
Expensive model work should happen primarily at ingestion/index time.

Customer search should be:
- fast
- cached where useful
- based on stored embeddings and metadata
- deterministic for hard constraints

## Model outputs
Model-generated attributes may be stored as model observations with provenance.

They should not become irreversible truth without a policy or review step.

## Public availability language
Until stronger integrations exist, prefer language such as:
- "recently photographed"
- "recently seen in store"
- "availability may have changed"

Do not claim real-time stock unless supported.

## Phase 1 enforcement and future compatibility
These are implementation constraints for immediate callers, not claims that the current dataclasses enforce them. Keep ADR-0001's single deployable boundary; the suggested web framework is not an accepted second service.

- Catalog owns a deterministic public representation policy. Search returns relevance and item references; a composed response may carry catalog-produced freshness fields, but search cannot derive availability or invent explanations.
- Keep stable catalog IDs independent of photo/source IDs. Define resolvable observation references when the loader is built. Preserve source/capture time separately from import/publication time; unknown capture time cannot support recency. Store scope may come from one validated configuration in Phase 1; no tenant framework is needed.
- Validate incoming records and event payloads at boundaries; dataclass annotations do not validate JSON. Deliberately parse decimal prices, bind currency to the store, and reject invalid references/identifiers. Implement only the fields required by the first caller.
- Manual review authorizes initial public attributes/prices. Later model proposals must retain provenance and pass explicit review/policy before publication. A generic confidence score cannot encode evidential support or override conflicting observations.
- Better crop quality, barcode identity, invoice receiving records and POS state are different evidence dimensions, not a universal quality/authority ladder. A barcode can identify a product type without identifying an individual specimen. Future adapters may include barcode/product databases without requiring vision; add concrete enum cases only with a real caller.
- Explicit price constraints must be enforced before return, including strict versus inclusive bounds and unknown-price exclusion (PRODUCT). `filters_satisfied` does not permit returning failed matches. Stored embeddings/indexes are derived data, not catalog authority.
- Telemetry persists validated append-only event snapshots with event/session/search/store IDs, result IDs/ranks/count, query/filters, catalog/index version and resolvable displayed observation context. Frozen dataclasses with mutable payloads do not ensure immutability. Prevent duplicate counts; failures are not zero-match events. Browse actions need no search ID.
- Retain enough context to separate no results, unsuitable nearest neighbors, incomplete catalog coverage and physical absence. Neither retrieval score nor result count is an availability or demand estimate.
- Do not implement a generic fusion graph, reconciliation engine, decision trace system, tenant framework or agent manager now. Current contracts are sketches with no deployed consumers; targeted additive changes at first use preserve these directions without speculative interfaces.

Future decision work must distinguish evidence available at decision time, support/conflict roles, scope, action consequence, authorization, probes and outcomes. Preserve these semantics in research artifacts first. The decision contract does not yet implement SER, and its status vocabulary remains provisional (H4).
