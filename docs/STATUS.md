# Current Status

Updated 2026-09-08.

## Phase and last known good
Phase 1 — customer search proof, including unfinished Phase 0 prerequisites.
Issue #1 fixture vertical slice is runnable locally. It validates and loads 30 explicitly non-production fixture records through a single-store configuration, renders a server-side catalog/search/item flow, and persists append-only JSONL telemetry. CI runs the same standard-library checks. No real merchandise, Customer Zero business content, semantic retrieval, retrieval evaluation, production telemetry, or project evidence exists yet.

PRODUCT defines the release; HYPOTHESES records dated strategic claims and gates.
Issue #1 added concrete store/fixture and response/event correlation fields to contracts.
ADR-0002 records the local standard-library runtime and single-writer JSONL limits,
preserving ADR-0001. No EVIDENCE entries were added.

## Issue #1 verification
13 unit/HTTP acceptance tests pass locally, including rendered-link navigation,
restart persistence, invalid/foreign attribution rejection, catalog validation and
concurrent duplicate-safe event writes. Compilation, Ruff lint/format and mypy pass
on Python 3.12. Browser form submission and item detail were manually checked.
CI uses the same checks on Python 3.11/3.12; remote CI has not been run in this pass.
No public deployment or semantic retrieval quality is claimed.

Limits: loopback-only local HTTP server; one process per JSONL file; linear log scans;
page reloads count as new interactions. Token ranking returns up to 12 records even
with no overlap. Explicit service price/category filters work; natural-language
price parsing and customer filters remain Issue #3. Fixture source records are
synthetic, resolvable observations; catalog-owned public snapshots assert no stock.

## Current objective
Deploy a polished Customer Zero website with a manually curated, honestly represented catalog of at least 30 real items, natural-language retrieval, deterministic price constraints, and validated discovery telemetry.

## Active acceptance criteria
See PRODUCT for the release contract. Issue #1 completed the runnable local/CI foundation, typed placeholder search response, fixture validation, store/session/search event correlation, and one browser-to-telemetry acceptance test. The following remain: verified mobile business content, >=30 permitted actual-item images, semantic retrieval and fixed relevance evaluation, deterministic price ceilings, supported production freshness wording, complete discovery reporting, and verified deployment. These remain requirements, not completed capabilities.

## Single next trunk task
Issue #2 — build the manually curated demo catalog. Obtain and record permission for 30–100 usable real Customer Zero product photos; record source/capture provenance, store scope, known prices/categories/minimal attributes and unknowns; validate publication records; document manual capture/entry/review/correction/publication effort and a simple refresh/withdrawal workflow. Replace no fixture data in Issue #1 until the real catalog meets Issue #2 acceptance. Do not implement embeddings, real public availability claims, or visual ingestion.

## Dependencies / blockers
Issue #2 depends on permitted actual images and available observation/price information from Customer Zero. These inputs are not in the repository. Public launch has the further PRODUCT dependencies (verified business content, domain/hosting access, refresh responsibility, commercial terms and applicable publication/privacy requirements). No external issue creation/payment/deployment is established here.

## Dependency order (roughly 1–2 weeks, not a waiting schedule)
1. Runnable fixture skeleton + minimum persistent telemetry. Completed in Issue #1.
2. Curated real catalog + manual effort baseline. Next: Issue #2.
3. Fixed retrieval evaluation + selected semantic baseline.
4. Polished customer UX, events added with features.
5. Funnel/report validation.
6. Deploy and begin the 2–4 week usage window; insufficient traffic is inconclusive.

Sales may continue throughout. Bounded research can run independently under AGENTS; no research success bypasses production promotion gates. Store #2 payment and 5–20-store repeatability are commercial tests, not reasons to add multi-store intelligence.

## Explicitly deferred in production
Shelf vision, repeated-state reconciliation, barcode/invoice/POS integrations, customer image upload/similar search, owner recommendations/SER, generalized agents, multi-store intelligence, payments, generated substitute product imagery. No research track is claimed to have run.
