# Charter

## Product thesis
Physical specialty retailers often have visually meaningful, irregular, fast-changing inventory that is expensive to represent in a conventional ecommerce catalog.

ShopSearch tests whether modern multimodal systems can reduce that cataloging burden enough that a physical store can become genuinely searchable online.

## Initial user
A customer deciding whether to visit a local specialty retailer.

## Initial merchant
A nontechnical independent retailer with little or no customer-facing inventory technology is the initial wedge, not the limit of the product. Merchants with competent websites or structured catalogs may still have valuable physical assortment missing online; the segmentation hypothesis is H10 in `HYPOTHESES.md`.

## Reusable product and delivery
The scalable unit is:

> merchant inventory evidence → ShopSearch representation/search → reusable customer experience

Build a reusable physical-inventory representation and discovery module, not a custom web-design agency. Delivery may embed into Shopify, WordPress, Wix, Squarespace or custom sites, or use a ShopSearch-hosted storefront when the merchant lacks a competent site. Do not assume replacement of an already-good website. These are delivery directions, not implemented integrations or current release requirements; `PRODUCT.md` owns the prospective Customer Zero release.

The long-term objective is to make as much physical inventory searchable as is economically practical, not to require exhaustive digitization regardless of cost.

## First customer promise
A visitor should be able to:
- see recently represented merchandise,
- describe what they want naturally,
- receive visually relevant results quickly,
- apply exact constraints such as price,
- and take a store-intent action such as directions or calling.

Example:

> "small blue one under $50"

should return real matching merchandise rather than generic marketing copy.

## First merchant promise
The merchant should not need to understand embeddings, vector databases, agents, or AI infrastructure.

The simplest near-term ingestion labor baseline is:

> individual photo + known price → searchable

The merchant should not need to fill a conventional ecommerce product form. Curator/system work still preserves permission, provenance and truthful publication. Unknown prices remain unknown. AI may eventually propose category, visual attributes, descriptions, crops and embeddings asynchronously; proposals require appropriate validation and do not establish truth. This is workflow direction, not permission to implement enrichment now.

Whole-display scanning is one candidate automation method. It must beat this baseline on total merchant labor per correctly published and maintained item; see `ROADMAP.md` and H2. The first proof remains manually curated.

## Core hypotheses

### H1 — Customer value
Customers care about seeing and searching actual local inventory before visiting.

### H2 — Catalog-cost reduction
Computer vision can reduce the merchant labor required to keep irregular inventory discoverable.

### H3 — Intent value
Customer searches reveal useful information not present in sales records alone, including unmet demand.

### H4 — Decision value
Evidence-aware reasoning can eventually use inventory, intent, and outcomes to improve bounded operational decisions.

These hypotheses must be tested separately.

## Current scope
The current project tests H1 first; no hypothesis has been established yet. See `PRODUCT.md` for release scope and `HYPOTHESES.md` for separate tests and promotion gates.

Use a manually curated catalog before automating ingestion.

## Non-goals
This project is not currently:
- a POS
- a payment processor
- a generalized autonomous business agent
- a perfect real-time inventory system
- an ecommerce shipping platform
- a loyalty platform
- a social-media automation suite
- a multi-vertical ontology project

## Product principles
1. Physical reality is primary; digital records are representations of it.
2. Freshness must be explicit.
3. Uncertainty must not be silently hidden.
4. Customer interaction should be simpler than conventional ecommerce filtering.
5. Merchant effort per useful published item is a first-class metric.
6. Real behavior beats founder intuition.
7. High-consequence recommendations require stronger evidence than low-risk experiments.
8. Founder onboarding, setup and support minutes per location are first-class commercial scalability metrics, separate from merchant catalog labor. Early sales are founder-led; H5 defines the repeatability test.
