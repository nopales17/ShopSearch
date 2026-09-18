# ADR-0005: Store-scoped platform boundaries, isolation and catalog/search independence

## Status
Accepted 2026-09-18 by founder decision during the platform transition review.

Preserves ADR-0001's single deployable boundary and ARCHITECTURE's catalog / search /
ingestion / telemetry boundaries. Amends ARCHITECTURE's Phase 1 statement that store
scope comes from one validated configuration. Implemented by ADR-0004's runtime.

## Context
`PRODUCT.md` was amended on 2026-09-18 to permit founder-provisioned, store-scoped
storefronts and more than one store, while generic self-service tenant management remains
deferred. The prospective Customer Zero has expressed interest in a website; pricing,
design, payment, publication permission and business inputs are unresolved, so the
machinery must exist before the store content does.

Two further properties are required. Merchant publication must not be able to leak across
stores even under implementation error. And catalog authority must not become dependent on
retrieval, which is a downstream consumer of the catalog, not its owner.

## Decision

### 1. Store scope is mandatory, and it is a type, not a convention
Every catalog, media, embedding and telemetry operation is scoped by a `StoreScope` value
object carrying one `store_id`. A `StoreScope` is obtained only from hostname resolution
or from an authenticated merchant session. Repository protocols expose no unscoped
variant, so an unscoped read or write is a type error rather than a review finding.

### 2. Isolation is enforced by boundaries and schema, not by text matching
Enforcement is layered:

- **Repository boundary.** Raw store-scoped persistence access does not leave the
  repository layer. Web adapters, view functions, ranking code and tools receive
  repository objects, never connections, cursors or SQL.
- **Schema constraints.** Store-scoped tables carry `store_id`, and child rows reference
  their parent by a composite key including `store_id`, so a row in one store cannot
  reference a row in another. `PRAGMA foreign_keys=ON` (or the equivalent for a later
  engine) is set on every connection. Uniqueness that is per-store is declared per-store
  (for example merchant username unique within a store, image sha256 unique within a
  store).
- **Import boundary test.** An automated test asserts that no module outside the
  persistence layer imports `sqlite3` or the connection factory.
- **Adversarial isolation tests.** Cross-store item access, cross-store media access,
  cross-store search results, cross-store telemetry attribution and a valid merchant
  session presented on another store's hostname are each tested and must fail closed.

The previously proposed static "every SQL statement must contain store_id" grep is
explicitly rejected: it is brittle, trivially bypassed by string composition, and gives
false assurance compared with the four layers above.

### 3. Hostname resolution, with no default store
A normalized `Host` header (lowercased, port stripped, trailing dot stripped, IDNA
decoded) resolves through a domain table to exactly one store. An unregistered hostname
returns 404 and reveals no store data. There is no default, wildcard or first-store
fallback in production; local development uses an explicit host-to-store map supplied by
configuration.

### 4. Merchant authentication
Multiple merchant accounts per store are supported from the start and are provisioned by
the founder through a CLI. There are no roles or permission levels: every merchant account
of a store has the same abilities within that store. Credentials are hashed with
PBKDF2-HMAC-SHA256; sessions are opaque random tokens stored hashed, delivered in a
Secure, HttpOnly, SameSite=Lax cookie, bound to one `(merchant_id, store_id)` pair, and
valid only on that store's resolved hostname. State-changing requests carry a CSRF token.
Credential reset is founder-mediated; there is no email dependency, no self-service signup
and no password-reset flow. Every mutation records the acting `merchant_id`.

### 5. Catalog and publication are independent of search indexing
Publication authority belongs to the catalog. Semantic indexing is a downstream derived
artifact and must never gate it.

- An item may be published and fully browsable while its embedding is pending, failed or
  stale. Nothing about indexing changes an item's listing state.
- Each item carries an explicit `index_state` of `pending`, `ready`, `failed` or `stale`,
  with an attempt count and last error, maintained by a single-purpose indexer. That
  indexer is one component with one table, not a generic job framework.
- Query routing: a query with no visual text (browse, category filter, price bound,
  price sort) is served deterministically over all published items and never depends on
  index state. A query with visual text ranks only items whose embedding is `ready`.
- Disclosure: when visual-text retrieval runs while a store has published items that are
  not `ready`, the storefront states plainly that some recently added items are not yet
  searchable by description and keeps a browse path to the full published selection. The
  indexed subset is never presented as the store's full represented selection, and a
  pending index is never presented as physical absence.
- Telemetry: search events record published count, ready count and excluded-unindexed
  count alongside the existing query, filter and result fields, so a zero-result search
  can be attributed to retrieval, catalog coverage or pending indexing rather than
  collapsing them.
- Merchant surfaces show each item's index state honestly, including failure.

Two generation counters are kept per store: a catalog generation, bumped by content or
listing-state mutations, and an index generation, bumped by embedding changes. The vector
cache is keyed by both. Index-state changes never bump the catalog generation.

### 6. Listing state is a merchant assertion, not inventory truth
`draft`, `published`, `hidden` and `sold` describe the listing. `hidden` is withdrawal
from public view; `sold` is the merchant's assertion that this specimen is gone. Neither
is an availability inference about anything else, and neither is derived from telemetry or
retrieval. Nothing is hard-deleted: every mutation appends an item event with before and
after state, preserving the provenance and correction history PRODUCT requires.

### 7. Public claims and freshness are store configuration
Public claim wording, disclosures and whether store actions are simulated come from the
store record, not from code literals. Photo capture time is recorded only from image
metadata or an explicit merchant attestation, with the source stored; otherwise capture
time stays unknown and no recency wording is shown. Upload time is import time and is
never presented as capture time.

### 8. The demo store is the first tenant
The existing Form & Field photographic demo becomes a store record flagged as a demo, with
its own hostname and branding. Its CC0, illustrative-price and not-for-sale disclosures are
mandatory and cannot be disabled by branding configuration, and its traffic keeps a
separate classification that is excluded from live customer reporting. A merchant browsing
their own storefront while authenticated is likewise classified separately from customer
traffic.

### 9. Still deferred
Self-service merchant onboarding, roles and permissions, Square/POS synchronisation,
checkout, payments, billing, delivery, shelf scanning, temporal reconciliation of repeated
observations, automated domain purchasing, elaborate theming, cross-store analytics or
multi-store intelligence, customer image upload and find-similar, availability-request
workflows, owner recommendations and SER.

## Consequences
Isolation failures become schema or type errors rather than review findings. The catalog
keeps its authority when retrieval degrades: a merchant can publish and a customer can
browse even if the model is unavailable, at the cost of an honestly disclosed reduction in
semantic search coverage. Two generation counters and an explicit index state add
bookkeeping. Multiple merchant accounts without roles means any account of a store can
withdraw or amend any of that store's listings, which the item event log records.

## Revisit when
A store needs differentiated merchant permissions; self-service onboarding is actually
authorized by PRODUCT; indexing latency becomes visible enough to customers to need a
different worker model; or isolation requirements change because a second application host
is introduced.
