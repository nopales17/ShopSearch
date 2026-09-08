# First Six GitHub Issues

These are local issue definitions; remote issue creation is not established. Keep one production objective active. Ordering expresses dependencies, not forced calendar delays; bounded research and continuous sales/customer discovery may proceed under AGENTS. PRODUCT is the release acceptance specification. Add telemetry with each feature, not only at Issue #5.

---

## Issue #1 — Bootstrap the Phase 1 vertical slice

### Goal
Create the smallest runnable skeleton for:

`demo catalog → search service → customer UI → telemetry`

Do not implement embeddings yet.

### Scope
- choose a minimal runtime consistent with ADR-0001; establish app/backend wiring and local/CI run commands
- load validated, clearly labeled local fixture records through a catalog interface; resolve observation references and store/currency configuration for current callers only
- expose a placeholder search endpoint/service
- render placeholder visual results in the web app
- persist correlated search_submitted, search_results_returned and item_opened events with session/search/store IDs
- add one acceptance test that proves the vertical slice can execute, including persisted events

### Acceptance
- app runs locally
- loader supports >=30 records; fixture data is labeled and cannot masquerade as verified store inventory; actual-image acceptance belongs to Issue #2
- search request reaches backend and returns typed results
- UI renders returned records and an item can be opened
- persisted event counts and correlation match the test journey
- acceptance test passes locally and in CI; placeholder results are not represented as semantic retrieval

### Non-goals
- vision
- LLMs
- production auth
- POS
- recommendation logic

---

## Issue #2 — Build the manually curated demo catalog

### Goal
Create a realistic 30–100 item dataset suitable for testing fuzzy visual search.

### Scope
Each item should include where known:
- id
- real image
- price
- category
- minimal structured attributes
- observation timestamp / provenance (unknown capture times remain unknown), store scope and permission record

Use images the project has permission to use.

### Acceptance
- ≥30 usable real images
- records validate against catalog contracts
- no generated image is presented as an actual physical product
- dataset includes enough variation to test color, size, style, and price queries
- manual capture/entry/review/correction/publication effort is recorded; simple refresh/withdrawal instructions exist
- public wording follows PRODUCT, with unknown-price/time cases handled honestly

### Evaluation queries
Include at least:
- `small blue one`
- `simple clear`
- `colorful`
- `dark and weird`
- `under $50`
- `small blue under $50`

---

## Issue #3 — Implement semantic visual retrieval baseline

### Goal
Return useful image results for natural-language queries.

### Scope
- evaluate at least one multimodal embedding baseline
- precompute product image embeddings
- embed query text
- rank by similarity
- apply exact `price_max` filtering deterministically; parse narrow explicit price expressions, distinguish strict “under” from inclusive ceilings, display applied constraint, exclude unknown prices under a ceiling
- keep experimental model comparison under `experiments/search_v0/`

### Acceptance
- fixed evaluation file and expected-relevance rubric exist before tuning, with unmatched cases and a browse/category comparison
- at least 8/10 agreed evaluation queries have sensible top-5 results by manual judgment
- measure warm server p95 against the PRODUCT budget and record cold/browser-visible latency and conditions
- hard price constraints pass boundary/unknown-price tests, including strict “under”; no failed match is returned
- chosen baseline and weaknesses recorded in `docs/EVIDENCE.md`

### Non-goal
Do not add an LLM to rerank results unless the embedding baseline demonstrably fails a defined case.

---

## Issue #4 — Ship the customer catalog/search experience

### Goal
Make the search feel simpler than conventional ecommerce browsing.

### UX
Prominent homepage affordance:
`See What's In Store`

Catalog page:
`Describe what you're looking for`

Initial examples:
- small blue one
- something colorful
- simple under $50

### Scope
- verified local-business homepage content and browseable catalog before search
- fast text search
- visual result grid
- query chips/examples
- item detail view
- `Get Directions`
- `Call`
- supported freshness/partial-coverage wording per PRODUCT; no unsupported “recently” label
- loading, failure, empty and no-match states; events added with their interactions

### Acceptance
- mobile-first
- useful first result visible quickly
- no unsupported `in stock right now` claim
- search state survives normal UI interactions
- visual design feels like a real local business, not an AI demo

---

## Issue #5 — Validate discovery instrumentation and reporting

### Goal
Measure discovery behavior and validate the complete funnel. This observational report does not establish causal lift.

### Required events
- `session_started`
- `homepage_viewed` (homepage-session denominator)
- `catalog_opened`
- `search_submitted`
- `search_results_returned`
- `zero_results`
- `item_opened`
- `directions_clicked`
- `call_clicked`

### Acceptance
`similar_clicked` and `availability_requested` remain deferred-feature event types, not required UI. Add/validate event payload contracts only for shipped callers.

For each search, preserve original query, parsed filters, event/search/session/store IDs, returned item IDs/ranks/count, catalog/index version and displayed observation context. Preserve enough context to compute:
- unique search sessions
- result count
- zero-result rate
- clicked items
- direction/call actions after search

Do not infer a purchase from a direction or call click. Sessions are not unique people. Distinguish test traffic and browsing actions without a search; validate retries/duplicate prevention. Nearest-neighbor counts do not establish suitable matches, physical availability or unmet demand. Set retention/access and applicable public telemetry notice settings before launch.

### Output
Provide one simple internal report showing:
- homepage/catalog sessions and defined funnel denominators
- catalog opens
- searches
- zero-result searches
- top normalized queries
- item clicks
- direction clicks
- call clicks

---

## Issue #6 — Deploy and run the first falsification test

### Goal
Put the Phase 1 experience in front of real users before building shelf vision.

### Hypothesis
Customers care about seeing/searching actual local inventory before visiting.

### Scope
- production deployment
- analytics sanity check
- real store branding/content
- manually curated first inventory set
- record baseline Google/site metrics where available
- define 2–4 week observation window, eligible traffic minimum, denominators and decision thresholds before measurement
- resolve PRODUCT public-release dependencies; verify backup/rollback, refresh responsibility and actual event/report behavior

### Primary metrics
- catalog-open rate
- search rate among catalog visitors
- result interaction rate
- zero-result rate
- direction/call rate after catalog interaction
- repeat catalog visits if measurable

### Qualitative evidence
Record:
- customers arriving with screenshots
- customers asking whether a shown item is still available
- owner/staff observations about customer use

### Decision gate
Do not begin production shelf-photo ingestion merely because it is technically interesting.

Production ingestion promotion requires customer-discovery value plus a bounded H2 experiment demonstrating lower total human effort at acceptable publication quality. Record an explicit trunk decision.

A specific plausible usability problem earns a cheap UX test and remeasurement, not production vision. Insufficient traffic is inconclusive. Evaluate browsing value and incremental search separately. Bounded offline research may run alongside this observation window under AGENTS; no fixed waiting period is imposed on research or sales.

Document the result in `docs/EVIDENCE.md`.
