# Current Status

Updated 2026-09-18.

## Phase and last known good
Phase 1 — customer search proof, including unfinished Phase 0 prerequisites.
Issue #1 remains runnable locally. P1's generic pitch has received the authorized bounded P2 improvement: 90 CC0 real-object photographs (30 original + 60 mechanically selected), rebuilt image embeddings and compositional semantic/price/sort queries. Existing homepage/catalog/detail and simulated actions remain. These museum objects are not goods for sale or the prospective shop's inventory; prices are illustrative and capture dates unknown. No public deployment, live stock or automated ingestion is claimed.

PRODUCT defines the release; HYPOTHESES records dated strategic claims and gates.
Issue #1 added concrete store/fixture and response/event correlation fields to contracts.
ADR-0002 records the local standard-library runtime and single-writer JSONL limits,
preserving ADR-0001 and continuing to describe the Issue #1 fixture slice.
ADR-0003 records P1's optional local model adapter; E-001 records its limited retrieval
findings. S1 moved the photographic storefront to the ADR-0004 Flask/Waitress HTTP
adapter without changing routes, headers, cookies, views, catalog loading, search or
telemetry storage.
S2 added the ADR-0004 persistence substrate (`backend/platform/db.py`: WAL,
`foreign_keys`, versioned forward-only migrations), the store registry with
`StoreScope` (`backend/stores/`), normalized hostname-to-store resolution with no
default fallback, the founder store-provisioning CLI, and seeding of the demo store
from `data/stores/pitch-demo.json`. The demo store's wordmark, hero images, category
list, query chips, credits, disclosures and public claim wording are now store
configuration; the storefront renders byte-identically to S1. An unregistered Host
gets a 404 with no store data, and only the persistence layer imports `sqlite3`.
S3 replaced the runtime JSON catalog with the store-scoped `CatalogRepository`
(`items`, `images`, `item_events`; composite store-scoped keys; `draft`/`published`/
`hidden`/`sold` listing state; independent `index_state` defaulting to `pending`) and
a content-addressed `ImageStore` behind `media_url()`. The committed demo dataset is
imported idempotently; served images are EXIF-free derivatives; capture time is taken
only from image metadata and is otherwise unknown. Browse, detail and media routes read
through the repository and media layer; at S3 search still read a compatibility vector
source keyed by item ID, so ranking was unchanged (S4 replaces that source).
S4 moved embeddings into the store-scoped catalog: one `embeddings` row per item holds
an opaque float32 vector with explicit dim/model/image binding, and `store_generations`
holds per-store catalog and index counters. The committed demo vectors are imported
unchanged and bound to each item's stored image. Runtime retrieval reads those rows
through a per-store cache keyed by both generations; a vector counts as `ready` only
while `model_id`, `model_revision` and `image_sha256` match the item, otherwise it is
`stale` and never ranked. Browse, category and price paths serve every published item
regardless of index state, visual-text retrieval ranks only ready items, the storefront
discloses the excluded count with a browse path, and `search_results_returned` records
published/ready/excluded counts. `backend/search/indexer.py` is the single-purpose
indexer with bounded retries, backoff and an attempt cap, plus a reindex CLI.
S5 moved platform telemetry onto the store-scoped database: `telemetry_events` rows are
append-only with the required `(store_id, search_id)` and `(store_id, occurred_at)`
indexes, written through a `TelemetrySink` implemented by `SqliteTelemetryStore`. The
event contract, duplicate handling, search/session/store/catalog attribution and the S4
coverage fields are unchanged and validated before any row is written; demo/fixture,
live customer and merchant-self traffic are explicit classes, and a store's rows cannot
cross its scope. `summarize()` keeps its demo semantics and a new per-store report
excludes demo/fixture and merchant-self traffic from customer denominators. A JSONL
import path replays a legacy demo log with identical event IDs, and the storefront now
writes through the sink instead of the local JSONL log.

## Verification
117 unit/HTTP acceptance tests pass locally, including rendered-link navigation,
restart persistence, invalid/foreign attribution rejection, catalog validation,
concurrent duplicate-safe event writes, and S1 route/response-header/session-cookie
parity with a byte-for-byte legacy-versus-WSGI comparison of deterministic routes.
S2 adds migration idempotency and applied-version checks, hostname normalization and
loopback host resolution (`Shop.Example.COM:8443` / trailing dot / bare), unknown-host
404 with no store data, CLI store creation and duplicate-hostname rejection, mandatory
demo-disclosure enforcement, an import-boundary test for `sqlite3`, and golden-hash
parity of the four deterministic demo pages against the pre-S2 bytes.
S3 adds importer idempotence (a second run creates no item, image, event or blob),
stored-SHA/byte verification for every imported image, rejection of bytes whose
content address does not match the stored hash, EXIF/GPS/DateTimeOriginal
absence in served derivatives, unknown-capture-time enforcement plus schema checks,
listing-state filtering, composite-FK rejection of a cross-store image, cross-store
item and media 404s, publication independent of `index_state`, and frozen-query rank
parity. Parity is asserted both structurally (identical item order, prices, categories
and per-item vectors) and by comparing the repository-backed and JSON-backed services
over every frozen query and control; the same comparison was also run manually with the
pinned CLIP runtime (34 query/limit combinations, zero mismatches).
S4 adds exact frozen-query parity between the database-backed vector source and the
committed-index path (item, rank and cosine score; 34 query/limit combinations with the
pinned CLIP runtime, zero mismatches), stale-binding exclusion for foreign model,
foreign revision, wrong dimension and drifted image bindings, pending/failed items
remaining browsable and price-searchable while excluded from visual text, the coverage
disclosure with accurate counts and a browse link, the published/ready/excluded
telemetry fields (a zero-result search with unindexed items is distinguishable from one
over a fully indexed store), indexer retry/backoff/attempt-cap behaviour with the last
error recorded and listing state untouched, and generation-keyed cache invalidation
(50 warm searches rebuilt the vector snapshot once; an embedding write forced a
rebuild).
Warm search latency over the demo store was measured locally on 2026-09-18 (Python
3.12, pinned CLIP runtime, 512-d vectors, 90 published and 90 ready, database-backed
source with the in-process cache, excluding HTTP and telemetry): p50 1.87 ms, p95
2.96 ms, max 3.34 ms over 85 warm searches. This is a local measurement under those
conditions, not an SLA or evidence of customer value.
S5 adds sink tests for identical-duplicate tolerance, conflicting-ID rejection,
store-scope and traffic-class enforcement (including merchant_self), foreign session,
store and catalog-version attribution rejection, the preserved S4 coverage validation
and the required telemetry indexes; isolation tests proving demo and live stores never
share a report and that merchant-self traffic is excluded from customer denominators;
and an import test proving `summarize()` over imported demo events is identical to
`summarize()` over the source events, including the committed expected counts.
Compilation, Ruff lint/format and mypy pass on Python 3.12. Browser form submission and
item detail were manually checked. The documented `make serve` target was smoke-tested
with the pinned CLIP runtime over loopback (`/health` and a price-bounded search). CI
runs the same checks on Python 3.11/3.12; the S4 commit c37985f passed both the 3.11
and 3.12 jobs, and the S5 commit 30e0cb6 passed both as well (earlier results are in the
GitHub Actions history).
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

Limits: loopback-only local Waitress/WSGI storefront (with the legacy stdlib fixture
server retained for Issue #1); one process per JSONL file; linear log scans; page
reloads count as new interactions. Token ranking returns up to 12 records even with no
overlap. Explicit service price/category filters work; natural-language price parsing
and customer filters are now available in P1's separate pitch mode. Fixture source
records are synthetic, resolvable observations; catalog-owned public snapshots assert
no stock.
The catalog, media metadata, embeddings, generation counters and telemetry now live in
the same SQLite file as the registry, with store-scoped keys. The committed CLIP index
file is an import/parity source only, so after an image change the old vector stays
`stale` (never ranked) until the indexer runs. Only the demo store is provisioned with a
catalog in the composition, and a resolved store without one gets 404 rather than another
store's catalog (S9 hardens this with a second real store). The indexer is a component
plus a CLI, not a daemon thread: S4 has no runtime producer of pending items because
merchant uploads arrive in S7, and no generic job framework is introduced. Coverage
counts and disclosure wording come from the store record, but the notice itself renders
client-side from the search response so the server-rendered page bytes stay unchanged.
JSONL telemetry remains only for the retired Issue #1 fixture slice and for reading
historical local logs; the platform storefront writes to the database. A pre-S4 JSONL
log can contain `search_results_returned` events without the S4 coverage counts, and the
importer validates strictly, so such entries are rejected with their position instead of
being silently rewritten or dropped; reconciling that historical log is a separate
decision. Merchant-self classification exists and is tested, but nothing detects
authenticated merchant requests yet (S6). `stores.catalog_path` remains as an unused S2
column because SQLite has no idempotent `DROP COLUMN`; no code reads or writes it.
Served media is a local content-addressed filesystem store; backup, restore and media
synchronisation are S10.
Funnel reporting covers recorded local demo and store traffic only; public-telemetry
retention, access and notice decisions remain unresolved.

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
acceptance criteria. S1 and S2 are implemented: the photographic storefront is served
by the Flask/Waitress adapter in `apps/web/wsgi.py` with hostname-resolved store
configuration from the SQLite registry, preserving the standard-library adapter's
behavior and tests. S3 is implemented: the store-scoped mutable catalog, listing state,
content-addressed media and idempotent demo import replace the runtime JSON catalog.
S4 is implemented: per-item embeddings, index state, a generation-keyed vector cache,
truthful coverage counts and disclosure, and the bounded-retry indexer with its CLI.
S5 is implemented: store-scoped, validated telemetry on the platform substrate with
per-store reporting and explicit traffic classes. S6-S10 are not implemented yet.

## Active acceptance criteria
See `docs/SLICES.md` for per-slice acceptance criteria of the platform transition, and PRODUCT for the release contract. The local foundation and generic pitch are verified. The store release still needs verified business content, >=30 permitted store-item images, store-specific retrieval evaluation, supported production freshness wording, complete discovery reporting and deployment.

## Single next trunk task
S6 in `docs/SLICES.md`: founder-provisioned merchant accounts, sessions and an
authenticated management shell. Execute only S6; its acceptance criteria and non-goals
are in the slice register, and the escalation rules in AGENTS apply. Do not pull later
slices forward.

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
