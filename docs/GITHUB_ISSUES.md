# First Six GitHub Issues

Create these in order. Keep only one implementation-active at a time.

---

## Issue #1 — Bootstrap the Phase 1 vertical slice

### Goal
Create the smallest runnable skeleton for:

`demo catalog → search service → customer UI → telemetry`

Do not implement embeddings yet.

### Scope
- establish app/backend wiring
- load demo catalog records through a catalog interface
- expose a placeholder search endpoint/service
- render placeholder visual results in the web app
- add one acceptance test that proves the vertical slice can execute

### Acceptance
- app runs locally
- at least 30 demo catalog records can be loaded once real images are added
- search request reaches backend and returns typed results
- UI renders returned records
- acceptance test passes

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
- observation timestamp / provenance

Use images the project has permission to use.

### Acceptance
- ≥30 usable real images
- records validate against catalog contracts
- no generated image is presented as an actual physical product
- dataset includes enough variation to test color, size, style, and price queries

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
- apply exact `price_max` filtering deterministically
- keep experimental model comparison under `experiments/search_v0/`

### Acceptance
- fixed evaluation file exists
- at least 8/10 agreed evaluation queries have sensible top-5 results by manual judgment
- search latency feels immediate at demo scale
- hard price filter never returns an item above the limit
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
`Describe what you're looking for or show us a picture`

Initial examples:
- small blue one
- something colorful
- simple under $50

### Scope
- fast text search
- visual result grid
- query chips/examples
- item detail view
- `Get Directions`
- `Call`
- freshness wording such as `Recently photographed`

### Acceptance
- mobile-first
- useful first result visible quickly
- no unsupported `in stock right now` claim
- search state survives normal UI interactions
- visual design feels like a real local business, not an AI demo

---

## Issue #5 — Instrument the discovery funnel

### Goal
Measure whether inventory discovery changes customer behavior.

### Required events
- `catalog_opened`
- `search_submitted`
- `search_results_returned`
- `zero_results`
- `item_opened`
- `similar_clicked`
- `directions_clicked`
- `call_clicked`

### Acceptance
For each search, preserve enough context to later compute:
- unique search sessions
- result count
- zero-result rate
- clicked items
- direction/call actions after search

Do not infer a purchase from a direction click.

### Output
Provide one simple internal report showing:
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
- define 2–4 week observation window

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

Proceed only if:
- customer behavior shows meaningful inventory-discovery use,
or
- a specific usability problem plausibly explains weak use and is cheap to test.

Document the result in `docs/EVIDENCE.md`.
