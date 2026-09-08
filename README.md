# ShopSearch

ShopSearch explores a simple product thesis:

> Make messy physical specialty-retail inventory intuitively searchable online without requiring the merchant to manually build and maintain a conventional ecommerce catalog.

The first proof is intentionally narrow:

1. Load a small manually curated catalog of real product images.
2. Search it with natural language such as `small blue one`.
3. Apply hard constraints such as `under $50`.
4. Show actual inventory images instantly.
5. Measure whether real users browse, search, click items, call, or request directions.

Only after customer value is demonstrated do we automate catalog ingestion from store photos.

## Start here
Read:
- `docs/CHARTER.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/MAP.md`
- `AGENTS.md`

## Repository principle
The project separates:
- what exists → `docs/MAP.md` + code
- what matters now → `docs/STATUS.md`
- what comes later → `docs/ROADMAP.md`
- why architecture is shaped this way → `docs/adr/`
- what experiments actually established → `docs/EVIDENCE.md`

Git remembers history. `STATUS.md` should stay current and short.
