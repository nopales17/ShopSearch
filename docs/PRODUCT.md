# Customer Zero product specification

Status: accepted release scope, not implemented. Updated 2026-09-08.

## Objective
Deploy a polished Customer Zero website with a manually curated, honestly represented catalog of at least 30 real items, natural-language retrieval, deterministic price constraints, and validated discovery telemetry.

## Customer and business context
Founder-reported on 2026-09-08: Customer Zero is a friend's newly opened smoke shop with little/no modern POS or web inventory. The friend wants to pay for a professional website. Payment, contract terms, customer usage, and repeatability have not been established in this repository.

The customer is deciding whether to visit. The first value is seeing actual merchandise; incremental semantic-search value is tested separately from catalog browsing. A paid website is the entry offer, not permission to become bespoke web consulting. Store #2 must be an unrelated paying merchant; 5–20 stores are the first broader repeatability test. Prices and recurring terms remain unvalidated (H5).

## Shipped customer journey
1. Mobile-first local-business homepage with verified name, address, hours, phone, real imagery, and prominent “See What's In Store.” Use supplied social links/reviews only when verified and permitted; do not fabricate endorsements.
2. Browse an attractive grid immediately, without submitting a query. Describe a preference using text, e.g. “small blue one,” “simple clear,” or “something colorful under $50.” Search is direct retrieval, not a chatbot conversation.
3. Show ranked actual-product images and known prices, with the applied price constraint visible and editable. Retain query/filter state across item navigation and back navigation.
4. Open an item for its actual image, known details, honest observation wording, and Call / Get Directions actions.
5. Provide clear loading, failure, empty-catalog, and no-match states. No match means no result in this represented selection, not that the physical store has none.

No customer image upload, find-similar button, availability-request workflow, checkout, or owner agent in this release. Do not advertise “show us a picture.” An unused contract field or event enum is not a shipped feature.

## Representation and manual operations
- Publish at least 30 real items with permitted usable photographs; 30–100 is the initial evaluation range, not a claim of whole-store coverage.
- Clearly describe the catalog as a selection of photographed merchandise.
- Curator records item ID, image source/permission, known price/category/attributes, store scope, and observation provenance. Unknown values remain unknown; no invented price, title fact, or capture timestamp.
- Distinguish photo capture/observation time from import/publication time. “Photographed today” requires a supported capture date in the store timezone. If capture time is unknown, omit recency claims and say availability may have changed. Prefer a dated observation to an indefinitely “recent” label.
- Curator validates records and images, reviews public fields, publishes, and can correct or withdraw listings. Document this simple workflow and name a refresh contact before launch; no dashboard is required.
- Measure photography, entry, review, correction, and publication time, useful items published, and coverage limitations. Manual labor is the automation comparison baseline.
- No generated substitute imagery. Presentation edits must preserve the actual item; the first release needs only ordinary photos.
- Use one store configuration for branding, location, currency, timezone, and approved content/disclosures. Do not build tenant management or a generic policy engine.

## Search acceptance
- Free text returns ranked visual results through stored image embeddings and a simple evaluated baseline; hard constraints are deterministic.
- `price_max` is inclusive. Natural-language “under $50” is strict (< 50); “up to $50” is inclusive. Implement a narrow explicit parser/constraint representation when retrieval is built; do not silently round or weaken constraints. Unknown prices are excluded under either ceiling.
- Define expected relevance before tuning. At least 8/10 fixed agreed queries must have sensible top-5 results by the recorded human rubric. Also test unsupported/no-match queries and compare equivalent tasks with browsing/categories.
- Suggested performance budget: warm server search p95 <= 1 second at demo scale on the intended deployment. Confirm measurement conditions before evaluation; record cold-start and browser-visible latency separately. This is a target, not evidence or an SLA.
- Automated checks cover price boundaries, unknown prices, invalid records, supported public wording, and the end-to-end flow. No result that fails a hard constraint may be returned.

## Telemetry and interpretation
Instrument from the first runnable slice and add events alongside their UI actions. Persist session_started, catalog_opened, search_submitted, search_results_returned, zero_results (when applicable), item_opened, directions_clicked, and call_clicked. Add homepage_viewed when implementing the homepage denominator. Deferred-feature events are not required until those features exist.

Each search needs an ID, pseudonymous session ID, store ID, timestamp, original query, parsed filters, returned IDs/ranks/count, and catalog/index version. Preserve displayed observation context by an immutable snapshot or resolvable version. Item/action events link to the originating search when applicable; browsing actions must also work without a search ID. Event IDs support duplicate prevention. Classify test/demo traffic separately.

Provide a simple internal report: homepage/catalog sessions, searches, zero-result searches, normalized queries, item clicks, call/directions clicks, and defined denominators. Keep original query distinct from derived normalization. A session is not a unique person. Calls/directions are clicks, not completed calls, visits, or purchases. A nearest-neighbor list is not proof of a suitable match; no/low results may reflect catalog coverage, filters, retrieval failure, or physical absence.

Before public telemetry, document retention, access, and any applicable notice/consent settings; do not collect direct personal identifiers by default. Internal reports are not publicly exposed. Do not add indefinite raw-query retention merely for hypothetical future SER training.

## Release and learning gates
- Reproducible local run and CI acceptance test; deployed mobile site and all advertised actions verified.
- At least 30 validated real images, supported wording, deterministic price behavior, fixed retrieval evaluation, and verified event/report counts.
- Verified business content, domain/hosting access, correction/refresh responsibility, backup/rollback procedure, and store-specific publication requirements resolved before public release.
- Record a 2–4 week initial observation window, eligible traffic denominator and decision thresholds before collection. Low traffic is inconclusive. Engagement does not establish incremental sales or automation value. See H1 and ROADMAP.

## Inputs pending (stage-specific)
None prevents Issue #1 using clearly labeled local fixtures. Before real catalog acceptance: permitted images, actual observation details, known prices/currency. Before public launch: verified business details/branding, store timezone/location and merchandise scope, domain/hosting access, owner content acceptance and refresh contact, commercial terms, and applicable publication/privacy requirements. The white paper's regulatory statements are dated, unverified source claims; determine actual requirements for this store before launch, without assuming owned-site discovery is exempt. Runtime and hosting choices can be resolved by the trunk; they are not reasons to wait for the founder before scaffolding.

## Strategic source boundary
The September 2026 white paper supplies context, not additional release requirements. See HYPOTHESES for its source fingerprint, qualified claims, and long-horizon ideas. This document governs current product scope; STATUS records actual progress.
