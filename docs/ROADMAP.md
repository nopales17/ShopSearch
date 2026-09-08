# Roadmap

Each phase must earn the next.

## Phase 0 — repository + website shell
Goal:
A clean, deployable local-business website skeleton exists.

Exit:
- customer-facing shell renders
- project knowledge architecture exists
- CI/test command works

## Phase 1 — search experience
Goal:
Prove natural-language product discovery over a manually curated catalog.

Exit:
- 30–100 real product images
- instant text→visual retrieval
- hard filters
- fixed retrieval evaluation
- telemetry wired

Falsification:
If the search experience is not meaningfully better than simple categories/filters, do not proceed to automated ingestion.

## Phase 2 — real usage
Goal:
Determine whether actual visitors use current-inventory discovery.

Exit evidence:
- real traffic
- catalog-open rate
- search rate
- item interaction rate
- store-intent actions

Falsification:
If meaningful traffic exists but almost nobody uses inventory discovery, investigate UX before building vision.

## Phase 3 — automated ingestion
Goal:
Reduce merchant cataloging labor.

First target:
One display case, not the whole store.

Exit:
- one display photo produces useful item candidates
- human review is fast
- usable items can be published
- merchant labor is measured

Primary metric:
human seconds per 100 useful published items

## Phase 4 — persistent physical state
Goal:
Reconcile repeated observations across time.

Exit:
- persisted items can be distinguished from likely new/removed items
- uncertainty is represented explicitly
- public availability wording follows evidence state

## Phase 5 — intent intelligence
Goal:
Turn customer interactions into scoped demand observations.

Exit:
- unique intent aggregation
- zero-result / low-result demand
- availability context
- outcome correlations
- no unsupported claim that search equals purchase demand

## Phase 6 — operational reasoning
Goal:
Evaluate evidence-aware decision support.

Initial question:
"What should we stock more of?"

Policy outputs:
- INSUFFICIENT
- WATCH
- PROBE
- RECOMMEND

Exit:
Evidence-aware policy beats defined baselines in replay, simulation, or shadow evaluation on decision-quality metrics.

## Phase 7 — multi-store learning
Goal:
Test scoped transfer across multiple stores without treating regional evidence as local truth.

## Phase 8 — vertical generalization
Goal:
Test one additional irregular-inventory vertical.

No horizontal platform claim before this phase.
