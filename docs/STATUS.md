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
S6 adds founder-provisioned merchant authentication: store-scoped `merchants` and
`merchant_sessions` tables (usernames unique per store and reusable across stores),
PBKDF2-HMAC-SHA256 credentials with a random salt and 600,000 iterations, opaque 32-byte
session tokens stored only as SHA-256 digests, 12-hour sessions, a
`Secure`/`HttpOnly`/`SameSite=Lax` `Path=/` cookie, CSRF-protected sign-in and sign-out,
a process-local 5-failures/15-minute throttle keyed by store and normalized username
with generic invalid-credential responses, and a founder CLI (create/list/disable/reset
with interactive password prompts; reset revokes sessions). The read-only `/manage`
shell lists the store's items with listing and index state, redirects unauthenticated
requests to sign-in without leaking item data, and a valid merchant session for the
resolved store classifies that merchant's public storefront traffic as `merchant_self`
instead of customer traffic.
S7 adds the merchant photo+price publish path. `/manage/publish` accepts one photo
(camera capture supported), an optional price, optional title/category and the explicit
"I just took this photo" attestation behind the S6 session and CSRF boundary. Uploads
are bounded (12 MiB; JPEG/PNG/WebP only, no HEIC), format is sniffed from decoded bytes
rather than the filename or declared type, and derivatives reuse the existing
EXIF-stripping path. One submission writes the item, its image and its item event and
bumps the catalog generation exactly once in a single transaction, with the
authenticated merchant id as the event actor, `published` listing state and `pending`
index state; a failed publication removes the derivative it wrote. Capture time comes
from EXIF when present, otherwise from the attestation with source
`merchant_attestation`, otherwise stays unknown. Exact re-submission of source bytes in
the same store reuses the stored blob and creates nothing new. Indexing stays the
existing S4 indexer: the item is browsable immediately and becomes visual-text
searchable after one indexer run, with no further merchant action.
S8 adds the merchant correction and withdrawal operations on `/manage/items/<id>`:
amend title/category/price (blank stays unknown), hide/unhide, mark sold/relist, and
replace the photo through the same bounded S7 upload pipeline. Each real change is one
atomic catalog mutation: exactly one `item_events` row with before and after state and
the authenticated merchant as actor, plus exactly one catalog-generation bump, in the
same transaction. `draft` remains unreachable and only `published`↔`hidden`,
`published`→`sold` and `sold`→`published` are accepted, so hiding, selling and relisting
preserve the item, its history and its media. An unchanged submission is a true no-op
with no event and no bump. Image replacement keeps the item's identity and listing
state, resets `index_state` to `pending`, and leaves the previous embedding row in
place but unusable because its `image_sha256` no longer matches; the item stays
browsable and is excluded from visual-text ranking until the existing S4 indexer runs
once. The internal catalog lookup that mutation and duplicate-cleanup paths use works
for every listing state, so duplicate source bytes belonging to a hidden or sold item
can no longer delete that item's referenced blob.
S9 adds adversarial isolation proof with a second seeded store rather than new
capability. `data/stores/isolation-fixture.json` is a committed synthetic store document
(no demo or prospective Customer Zero content), provisioned twice in tests as
`isolation-alpha` and `isolation-beta` with distinct hostnames, branding, catalogs,
media, embeddings, merchants and telemetry, plus a registered-but-unprovisioned
hostname. The fixture deliberately reuses identifiers across stores — the same item IDs,
the same source image bytes and the same merchant username with different credentials —
so isolation cannot come from accidentally unique fixture values. One application process
serves both hostnames concurrently (`storefronts={alpha, beta}`) with no default,
wildcard or first-match fallback: an unknown hostname, an unprovisioned registered
hostname and the registered demo hostname all return the same store-free 404. The
concentrated suite crosses every boundary on purpose: item and detail requests, media
URLs (including an identical content address that each store owns independently), the
frozen query set over both full seeded catalogs, per-store catalog/index generations and
vector caches, merchant cookies and CSRF tokens, telemetry writes and attribution,
reports, and every S7/S8 mutation. A schema audit covers all nine store-scoped tables and
proves with direct inserts that SQLite rejects cross-store child rows, unknown-store rows
and a hostname claimed by two stores. No isolation defect was found, so no migration was
added.
S10 makes the runtime hostable and recoverable and retires the superseded Issue #1
fixture runtime. Production startup is now generic: `backend/runtime/config.py` is one
typed `SHOPSEARCH_*` boundary (database path, media root, explicit store-ID allowlist,
bind host/port, log level, backup root, optional development host map) that fails closed
with an operator error instead of falling back to the demo or to repository defaults.
`open_platform_stack()` opens the configured database and media root, runs the
forward-only migrations and provisions nothing; the Form & Field demo is seeded only by
the explicit `python -m apps.web.demo` command, and `make run` plus the fixture slice
(`apps/web/server.py`, the fixture catalog loader, placeholder search and the JSONL
runtime store) are removed after the platform storefront passed equivalent journeys.
`/health` now performs a real trivial read through the catalog repository and a media-root
check through the media adapter, answering at the runtime boundary before hostname
resolution with `200 ok` or `503 database unavailable` / `503 media unavailable` and no
store data, paths or SQL errors. Operational logs are JSON lines on the standard logging
stack, separate from telemetry, covering startup/shutdown, configuration, request
method/path/status/duration/store and backup/restore outcome, and never carrying
passwords, session cookies, CSRF tokens, bodies, uploads, header dumps or query strings.
`backend/ops/` adds a consistent online-backup command (SQLite's backup API inside the
persistence layer, WAL folded into a single self-contained snapshot, media tree mirrored,
every snapshot image row verified before success) and a restore command that refuses to
overwrite an existing destination unless the operator passes an explicit destructive
flag and re-verifies media references afterwards. `deploy/` carries a hostname-free Caddy
template (no wildcard or on-demand TLS), a systemd service plus a nightly backup timer,
and an environment-file example with placeholders only; `docs/OPERATIONS.md` records the
runtime directories, ownership, commands and the executed local restore drill. The
pitch-demo retrieval-index artifact is now an import/parity input for the demo path only:
a platform store no longer reads it at startup and no longer carries a fabricated
`retrieval_index_sha256` on live events.
S11 makes the explicit local Form & Field demo interactive and gives it a disposable
runtime. `apps/web/demo_runtime.py` owns the dedicated ignored root
(`data/local/form-and-field-demo/` with `shopsearch.sqlite3` and `media/`), the additive
bootstrap, the `demo`/`demo` local demonstration credential (provisioned through the
unchanged S6 hash/session machinery) and the verified reset. `apps/web/demo.py` serves
the storefront only from that root and is the only caller that passes the explicit
in-memory interactive-demo capability. That capability is a constructor argument in the
merchant composition: it is not persisted, not a store field, not an environment
variable, and not derived from `Store.is_demo`, hostname, database contents or the
existence of the demo merchant, so generic `make serve`, `open_platform_stack()` and an
ordinary `create_pitch_app()` still never provision the credential, never reveal it on
the sign-in page and never enable demo mutation. Inside the interactive demo a merchant
publishes one photograph with an optional price/title/category through the unchanged S7
pipeline; the item is browsable immediately and stays `pending` until an explicit
POST-only, CSRF-protected "Make searchable now" action runs the existing
`EmbeddingIndexer` with the shared demo encoder. Publication is never rolled back by an
indexing failure, which is recorded as `failed` with its error and disclosed honestly.
Every item mutation is server-side limited to items whose
`attributes["merchant_upload"] is True`, so the committed 90 museum records stay
read-only and keep their CMA/CC0 attribution, original title, measurements, source link
and fine print; uploaded demo items render separate local-demo wording from two new
store-presentation fields. The demo store's footer, catalog disclaimer, credits copy,
meta description and public claim now scope CMA/CC0 to the committed museum collection
and acknowledge local uploads separately, and the credits list stays museum-source-only.
`make demo` preserves an existing runtime (uploads and mutations); `make demo-reset`
refuses to touch a runtime whose recorded demo process is still alive, then deletes only
that one verified directory, rebuilds the 90-item / 90-ready-embedding baseline plus the
credential and exits without starting the server.

## Verification
236 unit/HTTP acceptance tests pass locally, including rendered-link navigation,
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
S6 adds password-hashing defaults and random-salt checks, multiple accounts per store
with cross-store username reuse and duplicate rejection, wrong-password/disabled
rejection, session store-scoping with only hashed tokens persisted, 12-hour expiry,
revocation and reset-driven revocation, failed-login throttling with window expiry and
success clearing the counter, CLI create/list/disable/reset (including the guarantee
that no password argument is accepted), shell tests for the unauthenticated `/manage`
redirect without item data, CSRF rejection on login and logout, byte-identical generic
invalid-credential responses, logout revocation, cross-store session rejection with
same-store acceptance, `merchant_self` storefront classification for a valid session
only (foreign/revoked/disabled/expired cookies keep the store's default class), and a
response-body scan proving password hashes and session tokens never appear.
S7 adds upload validation (empty, non-image, mismatched declared type, unsupported
format, over-cap bytes, oversized request), Decimal price parsing with blank-as-unknown,
one-item/one-image/one-event/one-generation publication counts, browsable-before-indexing
plus visual-search exclusion with truthful coverage and searchability after one indexer
run, indexer-failure leaving the item published with `index_state=failed` and a recorded
error, distinguishable EXIF/merchant-attestation/unknown capture provenance, duplicate
byte reuse without a second image row or mutation, cross-store non-deduplication,
auth/CSRF failures creating no state, demo stores having no publish form or publish
path, orphan-blob cleanup on a failed publication, and a structural 375px form check.
S8 adds unit and HTTP acceptance coverage for each mutation's exact counts (one event
and one catalog-generation bump per real change; zero for a no-op edit, a repeated
listing action or a current-bytes replacement), before/after event payloads with the
acting merchant, rejection of transitions outside the four allowed ones, price
known→unknown→known changing bounded-price results immediately while the item stays
browsable, hide/unhide and sold/relist changing browse, detail, media and price-search
surfaces in the same request cycle with media retained and the item id and history
preserved, image replacement leaving a published item browsable with the old vector
excluded and one indexer run rebinding it to the new image, duplicate owned by a hidden
item not deleting that item's blob, a simultaneous identical replacement resolved by
the migration-0006 unique index with one caller receiving the duplicate outcome, and
cross-store item ids returning the same non-disclosing response as an unknown item for
reads and every mutation while changing no item, image, event, generation or blob.
S9 adds the adversarial two-store suite: both hostnames served concurrently from one
application (WSGI client and a real loopback Waitress process with two Host headers),
store-A-only and store-B-only item IDs 404ing on the other hostname while deliberately
shared item IDs resolve to each store's own title, price, image and claim; media
addresses resolving only for the store that owns them, with the identical shared address
served independently by both and a hidden/sold item's bytes still invisible on its own
hostname; the frozen query set (evaluation queries plus controls, 15 in total) over both
full seeded catalogs, where every returned item belongs to the resolved store and each
returned record is verified through that store's detail page; per-store catalog and index
generations and vector-cache snapshots, where a store-A publish, edit, hide/unhide,
relist or embedding write leaves store-B's snapshot object, generation pair and effective
search payload unchanged; a store-A merchant cookie and CSRF token conferring no
authority on store B for reads or for publish/edit/listing/replace, with the shared
username resolving to different merchant identities and credentials; telemetry rows,
search attribution and `summarize_store` reports staying disjoint, with cross-store sink
writes and cross-store search/catalog attribution rejected and merchant-self traffic in
one store never entering the other store's customer denominators; and identical source
bytes in two stores remaining independent addresses where a failed or duplicate store-A
operation deletes nothing store B references. The schema audit enumerates every table and
proves cross-store `images`, `item_events`, `embeddings` and `merchant_sessions` rows,
unknown-store rows and a hostname claimed by two stores are rejected at the schema level.
The persistence import boundary now also fails if the raw connection factory escapes the
repository layer, with the one repository-composition exception
(`backend/auth/service.py`, which executes no SQL) pinned by test.
S11 adds the interactive-demo acceptance suite and the dedicated-runtime unit suite
(`tests/acceptance/test_interactive_demo.py`, `tests/unit/test_demo_runtime.py`): the
sign-in page shows demo/demo only in the interactive composition; generic composition
refuses publish and every item mutation even with a real demo merchant account and
session, and exposes no index action; a valid upload creates exactly one item, image,
event and catalog-generation bump, is browsable immediately and stays `pending`; visual
text excludes it and reports published/ready/excluded-unindexed counts before indexing
and includes it with `excluded_unindexed=0` afterwards; "Make searchable now" is
POST-only, authenticated and CSRF-protected, adds no catalog event, does not bump the
catalog generation and bumps only the index generation; index failure leaves the item
published and browsable with a recorded error and an honest notice; uploaded items
support edit, hide/unhide, sold/relist and photo replacement with the existing S8
invariants, with replacement returning the item to `pending` and excluded until
reindexed; edit/listing/photo-replacement/index POSTs against every committed museum item
fail with rows, item events, generations, embeddings and media bytes unchanged; uploaded
and museum detail pages render their own provenance; anonymous and authenticated
storefront traffic stay `pitch_demo` and `merchant_self`; bootstrap creates and
re-bootstrap preserves the pristine baseline (90 items, 90 ready embeddings, unchanged
IDs, prices, images, source URLs, licenses and museum metadata, verified credential);
reset removes uploads, media, sessions and telemetry and restores the pristine media
digest; reset refuses a runtime whose demo pid is alive and any directory not named
`form-and-field-demo`, treats a stale pid file as stopped, and leaves a sibling generic
runtime database and media byte-identical.
`tests/unit/test_store_presentation.py` updates the pinned demo page hashes for the
S11 copy revision (the museum detail body still renders identically; `item` differs only
by the shared page meta description) and adds mixed-provenance rendering tests. The
blanket "demo is read-only" tests in `tests/acceptance/test_merchant_shell.py` and
`tests/acceptance/test_merchant_publish.py` are refined into explicit generic-composition
cases. All 259 tests pass locally.
S10 adds runtime and operations coverage: production startup serves the two-store
isolation shape from `open_platform_stack()` with no demo store in the registry, while
the registered demo hostname keeps returning the store-free 404; the platform runtime
serves catalog and search with a guard that raises if `data/pitch/image_index.json` is
read at all, and live telemetry carries no `retrieval_index_sha256` and only the store's
own catalog version; `python -m apps.web.wsgi` exits 2 with a named-variable configuration
error for each missing `SHOPSEARCH_DATABASE`/`SHOPSEARCH_MEDIA_ROOT`/`SHOPSEARCH_STORES`;
`/health` returns 200 for a healthy runtime, 503 `media unavailable` for a media root
blocked by a plain file and 503 `database unavailable` for an injected repository
failure, with a generic body that contains no path or SQL text and no session cookie;
operational JSON logs carry method/path/status/duration/store with no query string and no
password, session token or CSRF value even when a real sign-in, a rejected CSRF mutation
and an upload rejection are exercised, while telemetry stays in the database and holds no
operational fields. The backup/restore suite proves a live WAL database snapshots into
exactly `database.sqlite3` + `media/` with the snapshot in `delete` journal mode, that
every backed-up image row resolves to backed-up bytes, that removing a mirrored blob
fails the restore, that a restore into a clean directory reproduces the snapshot's item,
image, item-event and telemetry counts exactly and serves catalog/detail/media/search
from the restored paths alone, and that restoring over an existing database or a
non-empty media root is refused without the explicit destructive flag. A separate restart
test publishes an item, browses, stops every repository/server handle, reopens the same
paths and finds the item, its media, its item event and the persisted telemetry intact.
The executed local drill and its observed numbers are recorded in `docs/OPERATIONS.md`.
Compilation, Ruff lint/format and mypy pass on Python 3.12. Browser form submission and
item detail were manually checked. The documented `make serve` target was smoke-tested
with the pinned CLIP runtime over loopback (`/health` and a price-bounded search). CI
runs the same checks on Python 3.11/3.12; the S4 commit c37985f passed both the 3.11
and 3.12 jobs, the S5 commit 30e0cb6 passed both as well, and the S6 commit 2f70437
passed both. The S7 commit 2dc6db0 also passed both jobs, as did the S8 commit 357c60a
(earlier results are in the GitHub Actions history). The S8 smoke was run locally with
the pinned CLIP runtime over the WSGI test client against a live store:
publish (item+1/image+1/event+1/generation+1), browsable with `excluded_unindexed=1`
before indexing, price known→unknown→known changing bounded results, hide/unhide and
sold/relist each removing and restoring every customer surface with media retained,
one indexer run reaching `ready`, image replacement (event+1/generation+1, media still
served, old vector excluded) and a second indexer run rebinding the new image.
S9 was verified by the two-store suite and by a bounded local smoke in which one Waitress
process served both hostnames over loopback: both stores browsed and searched over their
own three-item catalogs (`coverage` published=3/ready=3), both merchants signed in and
saw only their own items in `/manage`, and every cross-host attempt failed closed —
store-A-only and store-B-only item IDs 404ed on the other hostname, store A's media URL
and hash 404ed on store B, store A's cookie yielded no identity on store B, an unknown
and an unprovisioned hostname returned the store-free 404, store B's session with store
A's CSRF token was rejected, and store B's session could not edit or hide a store-A-only
item, leaving both stores' item/image/event counts and generation pairs unchanged. The
S9 commit f9f8f67 passed both the 3.11 and 3.12 CI jobs, and the S10 commit c173394
passed both as well.
S11 was verified by the two new suites above and by a bounded local smoke of the real
command over loopback with the pinned CLIP runtime on 2026-09-18 (a stale pre-S11 demo
server held port 8000, so the same command ran on a free port): startup printed the
storefront URL, `/manage/login`, demo/demo and the verified 90-item / 90-ready baseline
from `data/local/form-and-field-demo`; the sign-in page showed the credential and
demo/demo signed in; a published upload created one item and was browsable while absent
from visual text with coverage published=91/ready=90/excluded-unindexed=1; the
confirmation page carried "View in storefront" and "Make searchable now"; both worked;
the same query returned the item after explicit indexing with
published=91/ready=91/excluded-unindexed=0; `make demo-reset` refused while the demo was
running (exit 2, "still using") and afterwards rebuilt and verified the pristine
baseline, leaving the generic local platform database byte-identical. This smoke was run
with the S11 working tree, not from a committed revision, and it is a local
implementation check rather than evidence about a customer, merchant, demand or
availability.
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
store's catalog. S9 proves that with two simultaneously provisioned stores, but both are
synthetic test fixtures: the committed `isolation-fixture` document and the
`isolation-alpha`/`isolation-beta` provisionings exist only inside tests, are never served
by the production composition, and assert no merchant, customer or availability fact.
Their telemetry is generated test traffic, not customer evidence, and S9 adds no
cross-store search, analytics or shared merchant identity. The indexer is a component
plus a CLI, not a daemon thread: the only runtime producers of `pending` items are the
S7 publish and S8 replacement operations, and no generic job framework is introduced. Coverage
counts and disclosure wording come from the store record, but the notice itself renders
client-side from the search response so the server-rendered page bytes stay unchanged.
The retired Issue #1 fixture slice no longer runs: its server, fixture catalog loader,
placeholder search and JSONL runtime store are gone, and only the one-way historical
JSONL→platform importer remains. The platform storefront writes telemetry to the
database. `data/local/pitch-telemetry.jsonl` (gitignored) is a
historical, incompatible local artifact: it contains pre-S4 `search_results_returned`
events without the S4 coverage counts, so it is not migrated into the database, no
importer bypass exists and its events are not rewritten. `stores.catalog_path` remains
as an unused S2 column because SQLite has no idempotent `DROP COLUMN`; no code reads or
writes it. Merchant sessions are deliberate and store-scoped; the `Secure` merchant
cookie means a browser only accepts it over HTTPS or a localhost origin, so plain-HTTP
acceptance tests use the WSGI test client with an `https://` base URL while the
unauthenticated redirect is also exercised over real loopback HTTP. Login throttling is
process-local by design for the one-process runtime, there is no account deletion,
roles, self-service signup, or email, and `/manage` can only amend an existing item
(title/category/price), hide/unhide it, mark it sold/relist it or replace its photo;
bulk edits, scheduling and deletion are not implemented. Served media is a local
content-addressed filesystem store. S10 implements the operator backup (consistent
SQLite snapshot plus media synchronisation and verification), the restore command and
the nightly systemd timer definition, with the destination supplied by configuration;
the executed local drill is recorded in `docs/OPERATIONS.md`. Deployment templates,
health, configuration and operational logging are implemented and locally verified, but
no hosting provider, VM, domain, DNS record, TLS certificate or off-host backup
destination has been provisioned or configured, so nothing is deployed and no
availability, adoption, customer-value or production-traffic claim is made. The generic
runtime no longer reads the pitch-demo retrieval index, and live-store telemetry carries
no fabricated `retrieval_index_sha256`; the demo path still records the artifact's real
hash where it refers to the pitch-demo import/parity artifact. Caddy and systemd were not
available on the development machine, so those configuration files were reviewed by hand
but not syntax-validated locally.
Merchant publication is bounded to 12 MiB per photo and to JPEG/PNG/WebP, so HEIC
photos from some phones are rejected until ADR-0004 is amended; the request cap is that
byte cap plus multipart framing. Publishing is limited to live stores: the demo store
keeps its mandatory CC0/not-for-sale wording and exposes no publish form, so merchant
merchandise is never mixed into the illustrative demo. Duplicate detection is a
store-scoped `images.source_sha256` check inside the publication transaction, backed by
the unique `images_store_source_idx` index on `(store_id, source_sha256, variant)` added
in migration 0006, so two simultaneous identical uploads resolve to one item, one image,
one publish event and one generation bump, with one caller receiving the duplicate
outcome. Publishing bumps the S4 catalog generation
(which invalidates the storefront snapshot and vector cache) and leaves the
represented-catalog version string unchanged, because search telemetry and the demo
import bind to that version. No merchant-labor measurement was recorded for S7, so
PRODUCT.md is unchanged.
The interactive demo's `demo`/`demo` credential is deliberately weak, printed at startup
and displayed on the sign-in page; it exists only in the explicit local composition and
is re-provisioned through the normal S6 machinery on every `make demo` start (which
revokes previous demo sessions). It is not a production credential and must never be
used for a deployed store. Because the merchant cookie is `Secure`, a browser completes
the demo sign-in on a localhost origin over HTTP or on HTTPS; the real-loopback smoke
above passed the cookie explicitly because its raw HTTP client is not a browser. The
demo runtime is disposable ignored local state with no backup or migration path: only
the committed 90-item baseline and the credential are expected to be reproducible, and
`make demo-reset` deletes the whole root by design. Only one local demo process should
use a runtime at a time; the recorded pid file is what makes a concurrent reset refuse,
and it is not a general lock service. `data/local/shopsearch.sqlite3` and
`data/local/media/` remain the generic local platform state and are untouched by the
demo.
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
per-store reporting and explicit traffic classes. S6 is implemented: founder-provisioned
merchant accounts, store-scoped sessions, CSRF-protected sign-in/out, the read-only
management shell and merchant-self traffic classification. S7 is implemented:
authenticated photo+price publication with bounded upload validation, capture
provenance, duplicate-byte reuse and the existing indexer as the only indexing step.
S8 is implemented: authenticated amend, hide/unhide, sold/relist and photo replacement,
each one atomic catalog mutation with one item event and one catalog-generation bump,
with hidden and sold items keeping their media and history. S9 is implemented: a
synthetic two-store isolation fixture and its adversarial suite prove that catalog, media,
search, embeddings, telemetry and merchant authority fail closed across two
simultaneously provisioned stores. S10 is implemented: the production runtime is generic
and environment-configured, `/health` reports real database and media reachability,
operational logs are separate from telemetry, the operator backup/restore commands with
a nightly systemd timer and provider-neutral deployment templates are in place with an
executed local restore drill, and the superseded Issue #1 fixture runtime is retired with
ADR-0002 marked historical. S11 is implemented: the explicit local Form & Field demo is
interactive from its own disposable runtime with a local-only demo/demo credential,
uploaded demo items can be published, browsed before indexing, explicitly made searchable
and edited through the existing S8 operations, the committed museum corpus stays
read-only with its CMA/CC0 provenance, and generic production composition is unchanged
and still unable to enable demo mutation. The S1–S10 platform transition is complete in
the repository and S11 is complete.

## Active acceptance criteria
See `docs/SLICES.md` for per-slice acceptance criteria of the platform transition, and PRODUCT for the release contract. The local foundation and generic pitch are verified. The store release still needs verified business content, >=30 permitted store-item images, store-specific retrieval evaluation, supported production freshness wording, complete discovery reporting and deployment.

## Single next trunk task
The S1–S10 platform transition is complete and the authorized S11 interactive-demo
slice is implemented, so there is no further authorized implementation slice to start.
The next trunk task is founder-owned and external: record the prospective
owner's stated requirements, objections, pricing discussion and permission (or refusal)
to photograph and publish merchandise, then decide the hosting provider, domain, TLS and
an independent off-host backup destination, and resolve public-telemetry retention,
access and notice. Until those inputs exist, agents must not provision hosting, configure
DNS, issue certificates, contact the owner, expand scope or claim a deployment; no further
implementation slice is authorized by this document.

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
