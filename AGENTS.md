# Agent Operating Rules

## Mission
Build the smallest reliable system that turns recently observed physical specialty-retail inventory into an intuitive, searchable customer experience with minimal merchant cataloging labor.

## Read first
Before making changes, read in this order:
1. `docs/CHARTER.md`
2. `docs/STATUS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/MAP.md`

Read `docs/ROADMAP.md` only when selecting future work.
Read relevant ADRs before changing architecture.
Read `docs/PRODUCT.md` before product implementation. Read `docs/HYPOTHESES.md` when designing experiments, interpreting strategic sources, or proposing a promotion gate.

The white paper is dated strategic context, not implementation state, measured evidence, architecture authority, or permission to expand scope. PRODUCT is the release specification; STATUS and code/tests describe progress; EVIDENCE contains actual findings.

## One active objective
There is exactly one production implementation-active milestone at a time, owned by the trunk.

Sales/customer discovery may run continuously. Bounded research may run alongside the trunk without waiting for calendar phases: specify question, dataset, budget, artifact, metric and stop/promotion criterion; keep code/results in experiments and do not mutate production contracts, dependencies or modules. Parallel work is allowed, not automatically requested. Only the trunk promotes a minimal implementation after evidence review, relevant gates, and an explicit STATUS decision (ADR if architecture changes). A research success does not automatically authorize production scope. Issue ordering expresses dependencies, not forced idle time.

Do not start unrelated features because they are interesting.
Do not skip roadmap phases without recording why in `docs/STATUS.md`.

## Architecture invariants
1. Domain logic does not depend on UI frameworks.
2. Search ranks relevance; search does not decide inventory truth.
3. Observations, inferred catalog identity, availability state, and customer-facing claims are distinct concepts.
4. LLM/model outputs are proposals or observations, never authoritative database truth by themselves.
5. External providers enter through adapters.
6. Experimental code stays in `experiments/` until explicitly promoted.
7. Do not create an abstraction for a hypothetical future caller.
8. Prefer deterministic logic for hard constraints such as price, store, category, and explicit availability state.
9. Preserve provenance for any observation that can affect customer-facing availability or future operational reasoning.
10. Never silently convert uncertainty into certainty.

## Current product boundary
In scope now:
- customer-facing website
- manually curated demo catalog
- natural-language retrieval of actual product images (customer image uploads deferred)
- hard metadata filters
- basic telemetry
- photo-assisted ingestion remains outside current production scope; bounded research may run separately

Out of scope unless the roadmap explicitly promotes it:
- POS replacement
- payment processing
- autonomous purchasing
- generalized business-agent framework
- perfect real-time inventory
- multi-store optimization
- autonomous social media
- loyalty programs
- microservices
- Kubernetes

## Before coding
State in your working notes:
- current objective
- affected modules
- acceptance criterion
- what is intentionally not being changed

## Before finishing
1. Run relevant tests.
2. Confirm acceptance criteria.
3. Update `docs/STATUS.md`.
4. Update `docs/MAP.md` only if structure changed.
5. Add or amend an ADR only if an architectural decision changed.
6. Add evidence to `docs/EVIDENCE.md` only when an experiment established something.
7. Do not rewrite historical evidence entries to make results look better.

## Evidence discipline
Distinguish:
- observation: what was directly recorded
- inference: what is concluded from observations
- decision: what action is proposed
- outcome: what happened after action

A search, click, direction request, visual detection, and purchase are not equivalent evidence.

## Coding style
- Keep modules narrow.
- Avoid generic `utils.py`.
- Avoid god objects and generic `AgentManager` abstractions.
- Prefer typed contracts.
- New dependencies need a concrete reason.
- New abstractions should have at least one immediate real caller.
- Keep production code boring; keep experiments disposable.

## Completion rule
A task is not complete because code exists.
It is complete when:
- the relevant acceptance test passes,
- the vertical slice still works,
- project state is updated,
- and the repo is easier for the next agent to understand.
