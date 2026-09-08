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
