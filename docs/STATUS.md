# Current Status

Updated 2026-09-18.

## Phase and last known good
Phase 1 — customer search proof, including unfinished Phase 0 prerequisites.
Issue #1 remains runnable locally. P1's generic pitch has received the authorized bounded P2 improvement: 90 CC0 real-object photographs (30 original + 60 mechanically selected), rebuilt image embeddings and compositional semantic/price/sort queries. Existing homepage/catalog/detail and simulated actions remain. These museum objects are not goods for sale or the prospective shop's inventory; prices are illustrative and capture dates unknown. No public deployment, live stock or automated ingestion is claimed.

PRODUCT defines the release; HYPOTHESES records dated strategic claims and gates.
Issue #1 added concrete store/fixture and response/event correlation fields to contracts.
ADR-0002 records the local standard-library runtime and single-writer JSONL limits,
preserving ADR-0001. ADR-0003 records P1's optional local model adapter; E-001 records its limited retrieval findings.

## Verification
26 unit/HTTP acceptance tests pass locally, including rendered-link navigation,
restart persistence, invalid/foreign attribution rejection, catalog validation and
concurrent duplicate-safe event writes. Compilation, Ruff lint/format and mypy pass
on Python 3.12. Browser form submission and item detail were manually checked.
CI uses the same checks on Python 3.11/3.12; remote CI has not been run in this pass.
P1 now records `homepage_viewed`, and `backend/telemetry/report.py` produces a
read-only local demo funnel report with explicit denominators. Incomplete search
traces are correlated per session/search ID and reported separately from `zero_results`
events. Report counts are recorded demo interactions, not people, purchases,
availability, demand or customer value.
P1's frozen agent-authored rubric passed 10/10 top-three/price tasks. Mean visual precision@5 was 0.489 and graded nDCG@5 was 0.733. Warm uncached retrieval p95 was 12.27 ms locally, excluding HTTP/telemetry. The manually tagged lexical comparator scored higher nDCG@5 (0.888). “Colorful” and “dark and weird” remain weak; unrelated queries return neighbors. See E-001, the frozen rubric and raw results in experiments/search_v0. This is not customer-value or model-superiority evidence.

P2 ran one index build and one preregistered CLIP/lexical/fixed-hybrid comparison.
Expanded proxy-label nDCG@5: 0.619 / 0.875 / 0.836; precision@5: 0.578 / 0.844 / 0.867.
All methods had strong top-three matches on 9/9 visual tasks and zero price violations.
New labels are incomplete metadata proxies, favoring lexical retrieval; original P1
judgments/results remain unchanged. Hybrid stays experimental; production relevance
is still CLIP. E-002 records scope, regressions and limitations.

Query plans support upper/lower bounds, inclusive between ranges and deterministic
ascending/descending price sorting. Semantic price sorts order the 12 closest eligible
CLIP candidates, visibly disclosed; price-only sorts consider all known-price items.
Unknown prices cannot satisfy price-dependent queries. No relevance threshold was added.

Limits: loopback-only local HTTP server; one process per JSONL file; linear log scans;
page reloads count as new interactions. Token ranking returns up to 12 records even
with no overlap. Explicit service price/category filters work; natural-language
price parsing and customer filters are now available in P1's separate pitch mode. Fixture source records are
synthetic, resolvable observations; catalog-owned public snapshots assert no stock.
Funnel reporting covers persisted local demo traffic only; public-telemetry retention,
access and notice decisions remain unresolved.

## Current objective
Build the reusable store-scoped platform machinery that the Customer Zero release will be
delivered on, so a storefront can be provisioned as soon as permission, business inputs and
merchandise images exist. The release contract in PRODUCT is unchanged and still owns the
store release; the conditional store release remains pending, and P1 does not complete
Issue #2.

Founder decisions recorded 2026-09-18: the PRODUCT release boundary is amended to permit
founder-provisioned, store-scoped storefronts and more than one store, with generic
self-service tenant management still deferred; publication authority stays independent of
semantic indexing; several founder-provisioned merchant accounts per store are permitted;
isolation is enforced by repository boundaries, schema constraints and adversarial tests
rather than static SQL inspection; and SQLite, local blob storage, Waitress and Caddy are
the selected initial deployment implementations behind adapters, not permanent product
architecture. `adr/0004-production-runtime.md` and `adr/0005-store-scoped-platform.md`
record the architecture; `docs/SLICES.md` records the implementation sequence and
acceptance criteria. Nothing in S1-S10 is implemented yet.

## Active acceptance criteria
See `docs/SLICES.md` for per-slice acceptance criteria of the platform transition, and PRODUCT for the release contract. The local foundation and generic pitch are verified. The store release still needs verified business content, >=30 permitted store-item images, store-specific retrieval evaluation, supported production freshness wording, complete discovery reporting and deployment.

## Single next trunk task
S1 in `docs/SLICES.md`: move the existing storefront onto the production HTTP adapter
described in ADR-0004, preserving behavior exactly. Execute only S1; its acceptance
criteria and non-goals are in the slice register, and the escalation rules in AGENTS apply.

In parallel and founder-owned, not an agent task: record the prospective owner's stated
requirements, objections, pricing discussion and permission
(or refusal) to photograph/publish merchandise. The founder owns the external
conversation; agents must not invent its outcome or contact the owner unasked.
Do not begin the full Issue #2 workflow until permission and source inputs exist.

Factual correction (2026-09-18, founder-provided): the shop remains a prospective
Customer Zero. The prospective owner has expressed that he wants a website after seeing
comparable storefronts. That is expressed interest only. Pricing, final design, payment,
merchandise-publication permission and the exact business inputs remain unresolved; no
commitment, payment, willingness-to-pay figure or publication permission is established.

## Dependencies / blockers
No technical blocker remains to a local pitch; initial setup downloads pinned model weights and later inference is local. Issue #2 depends on permission, actual shop images and observation/price information. These inputs are not in the repository. Public launch has the further PRODUCT dependencies (verified business content, domain/hosting access, refresh responsibility, commercial terms and applicable publication/privacy requirements). No external issue creation/payment/deployment is established here. Demo traces are not customer-demand observations.

Open founder decisions that block deployment but not S1-S9: hosting target and budget (the
pinned CLIP runtime implies roughly 2-4 GB RAM and a persistent volume); domain strategy
(a ShopSearch subdomain versus the owner's own domain, with automated domain purchase
deferred); telemetry retention, access and notice, which PRODUCT requires resolved before
public telemetry; and whether HEIC uploads must be supported, which would add a dependency
and need an ADR-0004 amendment. Two smaller decisions were taken by default in ADR-0005 and
can be reversed on request: sold items are excluded from customer surfaces rather than shown
marked sold, and an explicit merchant attestation counts as support for a capture date when
image metadata carries none, recorded with its source.

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
