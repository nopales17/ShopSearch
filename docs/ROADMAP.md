# Roadmap

Each production phase must earn promotion. PRODUCT defines the current release; HYPOTHESES defines separate tests. Dependency order is not a calendar embargo: sales/customer discovery and bounded research may run alongside the single trunk objective under AGENTS. Research artifacts do not authorize production features.

## Commercial track
Customer Zero paid website/search → unrelated Store #2 payment → 5–20-store repeatability test. Track actual payment, retention, onboarding/refresh/support labor, acquisition cost and referrals. Three to five retained stores or a referral are intermediate signals, not repeatability proof. Use a truthful curated demo before automation is ready. Pricing and financing remain hypotheses; no future technical phase is a prerequisite for starting sales discovery.

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
Evaluate incremental search value (H1b) against categories/browsing separately from actual-catalog value (H1a). If search adds little, revise/test retrieval or UX; do not infer that a useful browseable catalog has no value. Phase 1 exit is local functionality, not proof of customer value.

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
Define eligible traffic, window and thresholds before measurement. With sufficient traffic and little inventory-discovery use, run a bounded UX correction and retest; insufficient traffic is inconclusive. A plausible UX problem authorizes that test, not production vision.

Production ingestion requires scoped evidence of useful catalog discovery plus a bounded H2 experiment demonstrating publication quality and lower total human effort. Record the promotion decision in STATUS; expensive automation is not justified merely by a demo.

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
- scoped zero-result / low-result intent, separating coverage and retrieval defects from physical absence
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
Evidence-aware policy beats defined owner, simple-heuristic and LLM-only baselines on preregistered decision/probe/cost metrics using time-correct replay, simulation or shadow evaluation. Preserve trace provenance and limitations; replay cannot prove unobserved counterfactual outcomes. Contract statuses are placeholders, not implemented SER or action authority.

## Phase 7 — multi-store learning
Goal:
Test scoped transfer across multiple stores without treating regional evidence as local truth.

## Phase 8 — vertical generalization
Goal:
Test one additional irregular-inventory vertical.

A successful test permits another scoped test, not an automatic horizontal platform claim. Expansion order and fundraising targets are not implementation deadlines.
