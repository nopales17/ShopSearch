# Current Status

Updated 2026-09-08.

## Phase and last known good
Phase 1 — customer search proof, including unfinished Phase 0 prerequisites.
Issue #1 remains runnable locally. P1, the authorized generic pitch demo before Issue #2, is complete: 30 CC0 real-object photographs, precomputed CLIP image embeddings, deterministic price constraints, polished homepage/catalog/search/detail UI and simulated Call/Directions with persistent correlated telemetry. These museum objects are not goods for sale or the prospective shop's inventory; prices are illustrative and capture dates unknown. No public deployment, live stock or automated ingestion is claimed.

PRODUCT defines the release; HYPOTHESES records dated strategic claims and gates.
Issue #1 added concrete store/fixture and response/event correlation fields to contracts.
ADR-0002 records the local standard-library runtime and single-writer JSONL limits,
preserving ADR-0001. ADR-0003 records P1's optional local model adapter; E-001 records its limited retrieval findings.

## Verification
19 unit/HTTP acceptance tests pass locally, including rendered-link navigation,
restart persistence, invalid/foreign attribution rejection, catalog validation and
concurrent duplicate-safe event writes. Compilation, Ruff lint/format and mypy pass
on Python 3.12. Browser form submission and item detail were manually checked.
CI uses the same checks on Python 3.11/3.12; remote CI has not been run in this pass.
P1's frozen agent-authored rubric passed 10/10 top-three/price tasks. Mean visual precision@5 was 0.489 and graded nDCG@5 was 0.733. Warm uncached retrieval p95 was 12.27 ms locally, excluding HTTP/telemetry. The manually tagged lexical comparator scored higher nDCG@5 (0.888). “Colorful” and “dark and weird” remain weak; unrelated queries return neighbors. See E-001, the frozen rubric and raw results in experiments/search_v0. This is not customer-value or model-superiority evidence.

Limits: loopback-only local HTTP server; one process per JSONL file; linear log scans;
page reloads count as new interactions. Token ranking returns up to 12 records even
with no overlap. Explicit service price/category filters work; natural-language
price parsing and customer filters are now available in P1's separate pitch mode. Fixture source records are
synthetic, resolvable observations; catalog-owned public snapshots assert no stock.

## Current objective
Deploy a polished prospective Customer Zero website with a manually curated, honestly represented catalog of at least 30 real store items, natural-language retrieval, deterministic price constraints, and validated discovery telemetry. The conditional store release remains pending; P1 does not complete Issue #2.

## Active acceptance criteria
See PRODUCT for the release contract. The local foundation and generic pitch are verified. The store release still needs verified business content, >=30 permitted store-item images, store-specific retrieval evaluation, supported production freshness wording, complete discovery reporting and deployment.

## Single next trunk task
Support the first formal pitch of P1 to the prospective Customer Zero, then record
the owner's actual response, objections, willingness-to-pay discussion and permission
(or refusal) to photograph/publish merchandise. The founder owns the external
conversation; agents must not invent its outcome or contact the owner unasked.
Do not begin the full Issue #2 workflow until permission and source inputs exist.

Factual correction: the shop is a prospective Customer Zero. The concept has not
been formally pitched; payment and willingness to pay remain unvalidated.

## Dependencies / blockers
No technical blocker remains to a local pitch; initial setup downloads pinned model weights and later inference is local. Issue #2 depends on permission, actual shop images and observation/price information. These inputs are not in the repository. Public launch has the further PRODUCT dependencies (verified business content, domain/hosting access, refresh responsibility, commercial terms and applicable publication/privacy requirements). No external issue creation/payment/deployment is established here. Demo traces are not customer-demand observations.

## Dependency order (roughly 1–2 weeks, not a waiting schedule)
1. Runnable fixture skeleton + minimum persistent telemetry. Completed in Issue #1.
2. P1 pulled bounded retrieval/UX work forward for the pitch. After permission: Issue #2 store catalog + measured manual effort baseline.
3. Fixed retrieval evaluation + selected semantic baseline.
4. Polished customer UX, events added with features.
5. Funnel/report validation.
6. Deploy and begin the 2–4 week usage window; insufficient traffic is inconclusive.

Sales may continue throughout. Bounded research can run independently under AGENTS; no research success bypasses production promotion gates. Store #2 payment and 5–20-store repeatability are commercial tests, not reasons to add multi-store intelligence.

## Explicitly deferred in production
Shelf vision, repeated-state reconciliation, barcode/invoice/POS integrations, customer image upload/similar search, owner recommendations/SER, generalized agents, multi-store intelligence, payments and generated substitute product imagery remain deferred.
