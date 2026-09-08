# Current Status

Updated 2026-09-08.

## Phase and last known good
Phase 1 — customer search proof, including unfinished Phase 0 prerequisites.
Repository bootstrap and documentation only. Backend modules are empty; web/tests contain instructions; the single illustrative catalog record has no supplied image or observation provenance. No runnable app, CI, retrieval evaluation or project evidence exists yet.

White-paper reconciliation completed as documentation only. PRODUCT defines the release; HYPOTHESES records dated strategic claims and gates. No production contract or ADR changed.

## Current objective
Deploy a polished Customer Zero website with a manually curated, honestly represented catalog of at least 30 real items, natural-language retrieval, deterministic price constraints, and validated discovery telemetry.

## Active acceptance criteria
See PRODUCT for the release contract: verified mobile business site, >=30 permitted actual-item images, free-text ranked retrieval, deterministic price ceilings (including strict “under”), supported freshness wording, fixed retrieval evaluation, correlated discovery events/internal report, reproducible local/CI checks and verified deployment. These are requirements, not completed capabilities.

## Single next trunk task
Issue #1 — bootstrap the runnable catalog → placeholder search → customer UI → persistent telemetry slice. Select a minimal runtime consistent with ADR-0001, validate clearly labeled local fixture records through a catalog interface, render typed results, record correlated search_submitted/search_results_returned/item_opened events, and add one end-to-end acceptance test plus local/CI commands. No embeddings or real-inventory claims yet. See GITHUB_ISSUES for scope and acceptance.

## Dependencies / blockers
No known blocker to Issue #1. Real-photo catalog acceptance and public launch depend on founder/store inputs listed in PRODUCT; these are not assumed supplied. Runtime selection is a trunk implementation choice. No external issue creation/payment/deployment is established here.

## Dependency order (roughly 1–2 weeks, not a waiting schedule)
1. Runnable skeleton + minimum persistent telemetry.
2. Curated real catalog + manual effort baseline.
3. Fixed retrieval evaluation + selected semantic baseline.
4. Polished customer UX, events added with features.
5. Funnel/report validation.
6. Deploy and begin the 2–4 week usage window; insufficient traffic is inconclusive.

Sales may continue throughout. Bounded research can run independently under AGENTS; no research success bypasses production promotion gates. Store #2 payment and 5–20-store repeatability are commercial tests, not reasons to add multi-store intelligence.

## Explicitly deferred in production
Shelf vision, repeated-state reconciliation, barcode/invoice/POS integrations, customer image upload/similar search, owner recommendations/SER, generalized agents, multi-store intelligence, payments, generated substitute product imagery. No research track is claimed to have run.
