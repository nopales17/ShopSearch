# Platform transition slice register

Ordered implementation slices for the transition from the Form & Field pitch demo to a
reusable, store-scoped ShopSearch platform.

This document owns **slice sequence, scope and acceptance criteria**. It does not own
product scope (`PRODUCT.md`), architecture (`ARCHITECTURE.md`, `adr/0004`, `adr/0005`),
current state (`STATUS.md`) or evidence (`EVIDENCE.md`). Where this file appears to
conflict with those, they win and the conflict is an escalation.

Authorized by the founder on 2026-09-18 together with the PRODUCT release-boundary
amendment permitting founder-provisioned, store-scoped storefronts.

## How to execute a slice

1. Read `AGENTS.md`, `docs/CHARTER.md`, `docs/STATUS.md`, `docs/ARCHITECTURE.md`,
   `docs/MAP.md`, then `docs/adr/0004-production-runtime.md`,
   `docs/adr/0005-store-scoped-platform.md`, then this file.
2. Execute only the single slice named as the next trunk task in `STATUS.md`. Do not
   start the next slice in the same change, and do not pull later slices forward because
   they look easy.
3. Before coding, state in the change description: the slice, the affected modules, the
   acceptance criteria being satisfied and what is intentionally not changing.
4. Add focused unit and acceptance tests for the changed behavior and its boundaries.
5. Run `make check PYTHON=.venv/bin/python` before finishing. A local pass is not a remote
   CI run.
6. Update the documentation the slice names, including `docs/MAP.md` whenever files,
   modules or responsibilities move, and `docs/STATUS.md` when implemented state changes.

### Definition of done for every slice
- Every acceptance criterion in the slice is covered by an automated test unless the
  criterion explicitly says it is a manual or documented check.
- The full suite passes; no existing test is weakened or deleted to make a slice pass. If
  an existing assertion is genuinely wrong after a slice, say so explicitly and escalate
  rather than quietly editing it.
- The demo storefront still serves its journeys end to end.
- No slice leaves the trunk unable to run.

### Escalate instead of deciding
Stop and surface the decision if a slice appears to require: a product scope or release
boundary change; a new architectural boundary or a change to ADR-0001/0002/0004/0005; a
new runtime dependency not already named in ADR-0004; a change to price, provenance,
freshness, availability or public-claim semantics; a change to telemetry classification or
retention; anything touching external communication, hosting credentials, domains,
commercial terms or the prospective Customer Zero. `AGENTS.md` owns the routing rules.

## Invariants (all slices)

1. One deployable boundary. Catalog owns representation and publication; search consumes
   it; search never mutates the catalog and never derives availability.
2. Retrieval is not redesigned. `backend/search/price.py` semantics are unchanged: `under`
   is strict, `up to` is inclusive, unknown prices are excluded under either bound, sorts
   are deterministic, the semantic candidate set for price sorts stays bounded at 12, and
   no result that fails a hard constraint is ever returned.
3. Every catalog, media, embedding and telemetry operation is store-scoped through a
   `StoreScope`. No unscoped variant exists. No default-store fallback exists.
4. Raw store-scoped persistence access does not leave the repository layer.
5. Publication never depends on semantic indexing. Index state is explicit, and the
   indexed subset is never presented as the store's full represented selection.
6. Observation, catalog identity, availability and public claim stay distinct. Upload time
   is not capture time. Capture time is recorded only from image metadata or explicit
   merchant attestation, with the source stored.
7. `hidden` and `sold` are merchant assertions about a listing, not inventory truth.
8. Nothing is hard-deleted. Item mutations append item events; telemetry stays append-only
   with inline result snapshots.
9. Public claim wording, disclosures and simulated-action flags come from store
   configuration. The demo store's disclosures are mandatory, and demo and merchant-self
   traffic are never reported as live customer traffic.
10. Publicly served image derivatives carry no EXIF metadata. Sessions stay pseudonymous;
    no direct personal identifiers are collected by default.
11. No generated or substitute product imagery; no invented price, title fact or capture
    timestamp.
12. Dependencies are added only with a concrete caller in the same slice, and only if
    ADR-0004 already names them.

## Non-goals for the whole transition

Square or other POS synchronisation; checkout, payments or billing; delivery; shelf
scanning; temporal reconciliation of repeated observations; automated domain purchasing;
generic self-service merchant onboarding; merchant roles or permission levels; elaborate
theming; cross-store analytics or multi-store intelligence; customer image upload or
find-similar; availability-request workflows; owner recommendations or SER; a generic job
framework; a vector database; service decomposition.

---

## S1 — Production HTTP adapter, behavior-preserving

**Objective.** Move the existing storefront from the standard-library HTTP server to the
WSGI adapter named in ADR-0004, changing nothing else.

**Scope.** A Flask application plus a Waitress entry point, placed in `apps/web/` beside
the existing composition modules; port the existing pitch routes and response headers; keep
every view function, the catalog loader, the search service and the telemetry store exactly
as they are; add `requirements.txt` pinning Flask and Waitress; add a `make serve` target.
Choosing the exact pinned versions is a permitted local implementation decision: take
current stable releases that support Python 3.11 and 3.12 and pin them exactly, as
`requirements-dev.txt` and `requirements-pitch.txt` already do.

**Out of scope.** Any database, store registry, hostname routing, authentication, upload,
schema or view change. No new routes. No behavior change of any kind.

**Acceptance criteria.**
- Every existing acceptance test passes against the new server factory, over real loopback
  ports, with assertions unchanged.
- `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, the session cookie name and
  its `Path`/`SameSite`/`HttpOnly` attributes are unchanged on every route.
- Route-for-route parity: `/`, `/catalog`, `/credits`, `/items/<id>`, `/api/search`,
  `/api/demo-action`, `/health`, static assets and images; the existing invalid-input
  cases still return 400 or 404 as they do today.
- No file under `backend/` or `contracts/` is modified.
- `make check` passes, including Ruff format and mypy on the new adapter.

**Documentation.** `MAP.md` (new adapter files), `README.md` run instructions, `STATUS.md`.

## S2 — Persistence substrate, store registry and hostname resolution

**Objective.** Introduce the database, the store record and hostname-to-store resolution,
and move every store-specific literal out of code into store configuration.

**Scope.** `backend/platform/db.py` (connection factory, WAL, `foreign_keys` pragma,
versioned forward-only migration runner); `backend/stores/` with the store repository and
`StoreScope`; `stores` and `store_domains` tables; a store-provisioning CLI; host
normalization and resolution; a development host-to-store map from configuration; seeding
of the demo store from today's hardcoded Form & Field configuration, including branding
tokens, hero item IDs, example query chips, category list, credits and public claim
wording.

**Out of scope.** Items, images, embeddings, telemetry tables, authentication.

**Acceptance criteria.**
- Migrations apply cleanly to an empty database, are idempotent on re-run, and record
  applied versions.
- `Host: Shop.Example.COM:8443`, `shop.example.com.` and `shop.example.com` resolve to the
  same store; an unregistered host returns 404 whose body contains no store data; there is
  no configuration in which an unknown host falls back to a store.
- The demo storefront renders byte-identically to S1 for wordmark, hero images, category
  list, query chips, footer credits and public claim strings, all now sourced from the
  store record.
- No store-specific literal remains in `apps/web` view code; a test asserts the demo
  store's mandatory disclosures cannot be removed by branding configuration.
- The CLI creates a store with a domain and rejects a duplicate hostname.
- Only the persistence layer imports `sqlite3`, asserted by test.

**Documentation.** `MAP.md`, `STATUS.md`.

## S3 — Mutable catalog and durable media

**Objective.** Replace the immutable JSON catalog with a store-scoped mutable repository
and a content-addressed image store, and import the demo dataset into them.

**Scope.** `items`, `images` and `item_events` tables with composite store-scoped keys;
`CatalogRepository` with the `draft`/`published`/`hidden`/`sold` state machine and an
`index_state` column defaulting to `pending`; `backend/media/` with the `ImageStore`
protocol, a local filesystem implementation, derivative generation, EXIF capture-time
reading and EXIF stripping on derivatives, and `media_url()`; extraction of the private
validation helpers currently imported by `backend/catalog/pitch.py`; an idempotent
importer for the 90-photo demo dataset; storefront browse and detail served from the
repository; a compatibility vector source that maps the committed index file by item ID
rather than by position, so search keeps working unchanged this slice.

**Out of scope.** Embedding computation, the indexer, merchant authentication, upload.

**Acceptance criteria.**
- The importer is idempotent: a second run changes no item, image or blob count.
- Every imported item resolves to bytes whose SHA-256 matches its stored `sha256`.
- Served derivatives contain no EXIF; a test asserts no `GPS*` and no `DateTimeOriginal`
  in the output bytes.
- Items whose source has no capture metadata store capture time as unknown with source
  `unknown`; no import timestamp is ever written into a capture-time field.
- `published()` excludes `draft`, `hidden` and `sold` items; browse and detail acceptance
  journeys pass against the repository.
- Search results for the frozen pitch query set are identical to S2 output, item for item
  and rank for rank.
- A cross-store fetch of a valid item ID returns 404; the composite foreign keys reject an
  attempt to attach an image of one store to an item of another.

**Documentation.** `MAP.md`, `STATUS.md`, `data/pitch/README.md` if dataset handling
changes.

## S4 — Per-item embeddings, index state and honest search coverage

**Objective.** Move embeddings into the database per item, add the single-purpose indexer
and the index-state machine, and make search coverage honest without changing ranking.

**Scope.** `embeddings` table; import of existing vectors; per-store vector cache keyed by
catalog generation and index generation; `MultimodalSearchService` reading from the vector
source; the indexer as one background component with bounded retries and backoff, plus a
CLI to reindex a store; query routing per ADR-0005 section 5; the storefront coverage
disclosure; the search telemetry coverage fields.

**Out of scope.** Ranking changes, relevance thresholds, hybrid or lexical retrieval,
model changes.

**Acceptance criteria.**
- For every frozen pitch query, the database-backed service returns the identical item
  ordering as the committed index path.
- An embedding whose `image_sha256`, `model_id` or `model_revision` no longer matches its
  item is treated as `stale`, excluded from ranking and reported, never silently ranked.
- A published item with `index_state` of `pending` or `failed` appears in browse, in
  category filtering, in price-bounded results and in price sorts, and is excluded only
  from visual-text ranking.
- When visual-text retrieval runs while the store has published items that are not
  `ready`, the response states that some items are not yet searchable by description, the
  count is accurate, and a browse path to the full published selection is present.
- `search_results_returned` payloads carry published count, ready count and
  excluded-unindexed count; a zero-result search with pending items is distinguishable in
  the log from a zero-result search over a fully indexed store.
- The indexer retries a failed item with backoff, stops at the configured attempt cap,
  records the last error, and never changes an item's listing state.
- Warm search latency over the demo store is measured and recorded as a measurement, not
  as an SLA or as evidence.

**Documentation.** `MAP.md`, `STATUS.md`.

## S5 — Telemetry on the platform substrate

**Objective.** Move telemetry to the store-scoped database, preserving the event contract
and every validation rule.

**Scope.** `telemetry_events` table with indexes on `(store_id, search_id)` and
`(store_id, occurred_at)`; a `TelemetrySink` implementation behind the existing contract;
traffic classes extended to include live store traffic and merchant-self traffic;
per-store reporting.

**Out of scope.** New event types, retention policy implementation, public exposure of
reports, any change to `report.summarize()` semantics.

**Acceptance criteria.**
- Existing telemetry unit tests pass with unchanged assertions against the new sink.
- Duplicate event IDs are still rejected, or ignored when byte-identical; search
  attribution against a foreign session, store or catalog version is still rejected.
- A merchant browsing their own storefront while authenticated is recorded as
  merchant-self traffic and excluded from that store's customer denominators.
- Demo-store traffic never appears in a live store's report and vice versa.
- `report.summarize()` over the imported demo events reproduces the counts the current
  committed tests expect.
- Reports state denominators explicitly and make no claim about people, purchases,
  availability, demand or customer value.

**Documentation.** `MAP.md`, `STATUS.md`.

## S6 — Merchant authentication

**Objective.** Founder-provisioned merchant accounts, sessions and an authenticated
management shell.

**Scope.** `merchants` and `merchant_sessions` tables; PBKDF2-HMAC-SHA256 hashing; login
and logout; opaque session tokens stored hashed; CSRF tokens on state-changing requests;
login rate limiting; a CLI to create, disable and reset merchant accounts; a `/manage`
page listing the store's items with their listing state and index state.

**Out of scope.** Self-service signup, email, password-reset flows, roles or permissions,
publishing or editing.

**Acceptance criteria.**
- Multiple merchant accounts can exist for one store; usernames are unique within a store
  and may repeat across stores.
- Wrong password, disabled account, expired session and revoked session are all rejected.
- A valid session for store A presented on store B's hostname is rejected.
- A missing or invalid CSRF token on a state-changing request is rejected.
- Repeated failed logins are throttled within the configured window.
- Password hashes and session tokens never appear in any response, log line or error page.
- `/manage` without a session redirects to login and leaks no item data, including in
  404 versus 403 distinctions.
- The CLI can reset a credential without database surgery, and resetting revokes that
  merchant's existing sessions.

**Documentation.** `MAP.md`, `STATUS.md`, operator notes for credential handling.

## S7 — Mobile publish: photo plus price

**Objective.** The merchant labor baseline from CHARTER: an individual photo and a known
price become a published, browsable item from a phone.

**Scope.** A mobile-first upload form using the camera capture attribute, one price field,
optional title and category; multipart handling with a byte cap and content sniffing; image
decode, normalization and derivative generation; capture-time recording from image metadata
or an explicit "I just took this photo" attestation; publication in one request; catalog
generation bump; enqueueing for indexing.

**Out of scope.** Bulk upload, multiple images per item, AI-proposed attributes, cropping
tools, HEIC support unless ADR-0004 is amended to add the dependency.

**Acceptance criteria.**
- A valid image with a price produces exactly one item, one image, one item event and one
  catalog generation bump, and the item is browsable in the same request cycle, before any
  embedding exists.
- The same item becomes visual-text searchable once indexing completes, with no further
  merchant action.
- A submission with no price stores price state unknown and is excluded by both `under $X`
  and `up to $X`.
- A non-image payload, an oversized payload and a payload whose declared content type
  contradicts its bytes are all rejected without creating partial rows or orphan blobs.
- An indexer or model failure leaves the item published with `index_state` of `failed` and
  a recorded error; it never leaves the item unpublished and never blocks the response.
- Capture time is recorded with its source; the attestation path and the metadata path are
  distinguishable forever, and neither can be produced from upload time.
- Re-uploading identical bytes within a store reuses the stored blob and does not create a
  second image row.
- The form is usable at 375px width and its actions are reachable without zooming.

**Documentation.** `MAP.md`, `STATUS.md`, `PRODUCT.md` if measured merchant labor is
recorded.

## S8 — Edit, hide and sold

**Objective.** The correction and withdrawal operations PRODUCT requires of a curator.

**Scope.** Amend title, price including to unknown, and category; hide and unhide; mark
sold; relist; every mutation writes an item event and bumps the catalog generation; image
replacement re-enqueues indexing and marks the previous embedding stale.

**Out of scope.** Bulk edits, scheduled changes, deletion.

**Acceptance criteria.**
- Amending a price to unknown removes the item from price-bounded results on the next
  search; amending it back restores it.
- Hiding removes the item from browse and search within one request; unhiding restores it
  with its history intact.
- Marking sold excludes the item from customer surfaces and records the transition with a
  timestamp and the acting merchant.
- Every mutation appends exactly one item event carrying before and after state; no
  mutation path deletes a row.
- Replacing an image marks the old embedding stale, re-enqueues indexing, and leaves the
  item published and browsable throughout.
- A merchant of store A cannot amend, hide, sell or relist an item of store B, and the
  response does not disclose that the item exists.

**Documentation.** `MAP.md`, `STATUS.md`.

## S9 — Isolation hardening with a second store

**Objective.** Prove isolation adversarially with two real stores rather than asserting it.

**Scope.** A second seeded store with its own hostname, branding, catalog, merchant
accounts and telemetry; the adversarial test suite; the import-boundary test; review that
every store-scoped table carries composite store-scoped keys.

**Out of scope.** Any new customer or merchant feature.

**Acceptance criteria.**
- Store A's item ID requested on store B's hostname returns 404.
- Store A's media URL requested on store B's hostname returns 404.
- No search over store B's catalog, across the full seeded set and the frozen query set,
  returns a store A item.
- Telemetry rows for store B contain no store A item IDs, and a search event cannot be
  attributed across stores.
- A merchant session for store A is rejected on store B for both reads and mutations.
- The import-boundary test fails if any module outside the persistence layer imports
  `sqlite3` or the connection factory.
- A deliberate attempt to insert a child row referencing a parent in another store fails
  at the schema level, demonstrated by test.

**Documentation.** `MAP.md`, `STATUS.md`, `tests/README.md`.

## S10 — Deployment, operations and retirement of the fixture slice

**Objective.** Make the platform hostable and recoverable, and remove the superseded
demo-era duplication.

**Scope.** Environment-based configuration and secrets; reverse-proxy and service
configuration; nightly database backup and media synchronisation; a restore drill;
structured operational logging distinct from telemetry; health endpoint covering database
and media; retirement of `apps/web/server.py` and the fixture catalog loader once the
platform storefront covers their journeys; the documented migration path and revisit
triggers from ADR-0004.

**Out of scope.** Domain purchase, commercial terms, public launch itself, public telemetry
exposure. Public launch additionally depends on the unresolved PRODUCT inputs and on the
telemetry retention, access and notice decisions, which are founder-owned.

**Acceptance criteria.**
- A restore from the previous night's backup onto a clean directory reproduces the
  storefront, catalog, images and telemetry counts; the drill is documented with the
  commands actually run and the observed result.
- A process restart loses no published item and no persisted event.
- The health endpoint reflects real database and media reachability, not a constant.
- Secrets are read from the environment; no credential, cookie secret or hostname-specific
  value is committed.
- The fixture slice is removed only after the platform storefront passes equivalent
  journeys, and its removal is recorded in `STATUS.md` and `MAP.md` with ADR-0002 marked
  as historical.
- CI passes on Python 3.11 and 3.12.
- `STATUS.md`, `MAP.md` and `ARCHITECTURE.md` describe the shipped state and claim no
  customer value, demand, adoption or availability.

---

## S11 — Interactive Form & Field merchant demo

**Objective.** Extend only the explicit local Form & Field demo composition so one known
local demo merchant can sign in, publish a photographed demo item, browse it before
indexing, explicitly make pending items searchable using the existing indexer, and
exercise the existing S8 edit/listing/photo-replacement lifecycle. Preserve the committed
90-item museum corpus as read-only, truthfully distinguish its CMA/CC0 provenance from
locally uploaded demo content, provide a deterministic isolated reset, and leave generic
production startup and all S1–S10 semantics unchanged.

**Scope.** An explicit in-memory interactive-demo capability passed only by
`apps.web.demo` into the existing merchant composition; the local demonstration
credential `demo`/`demo` provisioned through the unchanged S6 machinery; a dedicated
ignored demo runtime root with `make demo` and `make demo-reset`; merchant mutation of
uploaded demo items only (`attributes["merchant_upload"] is True`); a separate
`Make searchable now` POST action that reuses `EmbeddingIndexer`; mixed
museum/upload rendering with the minimum new store-presentation wording; and the
documentation and tests that record all of it.

**Out of scope.** A new architecture, schema migration, dependency or ADR; generic
tenant or capability frameworks; any content-origin/provenance framework; production
or deployed demo credentials; merchant signup, roles, billing or theming; deployment
or external communication; search, ranking or retrieval redesign; a new embedding
model; background workers, schedulers, daemons or a job queue; new telemetry event
types; editing the committed museum source dataset; and any change to production demo
or publication semantics.

**Acceptance criteria.**
- `make demo` starts the polished Form & Field storefront from the dedicated demo
  database/media root and prints the storefront URL, `/manage/login`, and demo/demo.
- `/manage/login` displays demo/demo only when the explicit interactive-demo capability
  is active.
- demo/demo signs in through unchanged PBKDF2, sessions, cookie, throttling and CSRF
  machinery.
- Generic `make serve`, `open_platform_stack()` and ordinary `create_pitch_app()` never
  provision demo/demo and never enable demo mutation.
- Even if a demo store and merchant account manually exist in generic composition, the
  demo store remains read-only.
- Initial pristine demo contains exactly the committed 90 items and 90 valid ready
  embeddings, with existing IDs, prices, images, source URLs, licenses and museum
  metadata unchanged.
- A valid authenticated interactive-demo upload creates exactly one item, image, event
  and catalog-generation bump; it is immediately browsable and remains pending.
- Before indexing, visual-text search excludes the uploaded item and accurately reports
  published/ready/excluded-unindexed coverage; browse/category/price paths continue to
  include it according to existing semantics.
- Publication leads to useful "View in storefront" and "Make searchable now" controls.
- "Make searchable now" is POST-only, authenticated, CSRF-protected and only available
  in the explicit interactive demo.
- Successful indexing makes the uploaded item visually searchable without changing its
  listing state or adding a second catalog event.
- Indexing failure leaves the item published/browsable, records failed state/error and
  renders an honest notice; it never rolls publication back.
- Uploaded items support edit, hide/unhide, sold/relist and photo replacement with all
  existing S8 event/generation/no-op invariants preserved.
- Image replacement returns search state to pending/stale-excluded behavior until the
  separate indexing action succeeds.
- Only items explicitly carrying `merchant_upload is True` expose or accept mutation.
- Direct mutation POSTs against any committed museum item fail without changing rows,
  events, generations, embeddings or media.
- Museum detail pages retain existing CMA/CC0 provenance, original title, measurements,
  fine print and source link.
- Uploaded-item detail pages contain none of those unsupported museum assertions and
  explicitly identify the local-demo upload origin and limitations.
- Footer/catalog/credits/public-claim wording accurately scopes CMA/CC0 claims to the
  committed museum collection and separately acknowledges local demo uploads.
- Credits remain museum-source-only.
- Anonymous storefront traffic remains `pitch_demo`; authenticated storefront traffic
  remains `merchant_self`.
- `make demo` bootstraps the pristine isolated runtime if it does not yet exist.
- Re-running `make demo` preserves existing local demo uploads/mutations rather than
  silently resetting them.
- `make demo-reset` touches only the dedicated demo runtime root and safely requires the
  demo server not to be actively using it.
- After reset, uploads/media/mutations/sessions/telemetry are gone and the 90-item /
  90-ready baseline plus demo/demo credential is restored.
- Reset does not touch model weights, committed files, generic local platform state,
  another store or configured production state.
- No dependency, migration, architecture boundary, telemetry event type, search redesign
  or weakened isolation/security invariant is introduced.
- `make check PYTHON=.venv/bin/python` passes.
- Existing blanket "demo is read-only" tests are replaced/refined into explicit
  composition cases: the interactive demo permits only uploaded-item mutation, and
  generic composition keeps demo stores read-only.
- The normal customer Form & Field demo journeys remain working end to end.

**Composition and deletion boundaries.** S11 is an explicit local-demo composition
exception. It does not weaken production demo or publication semantics: the capability
is a constructor argument that generic startup never passes, the demo store stays
read-only everywhere else, and no store field, environment variable, hostname or
database fact can enable it. Deleting the isolated disposable demo runtime is not a
production catalog deletion path; committed catalogs still append item events and never
hard-delete, and `make demo-reset` operates on one ignored directory whose name it
verifies before removal.

**Documentation.** `MAP.md`, `STATUS.md`, `README.md`, `OPERATIONS.md`, `CREDENTIALS.md`,
`apps/web/README.md`.
