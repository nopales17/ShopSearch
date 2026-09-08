# ShopSearch

ShopSearch explores a simple product thesis:

> Make messy physical specialty-retail inventory intuitively searchable online without requiring the merchant to manually build and maintain a conventional ecommerce catalog.

The first proof is intentionally narrow:

1. Load a small manually curated catalog of real product images.
2. Search it with natural language such as `small blue one`.
3. Apply hard constraints such as `under $50`.
4. Show actual inventory images instantly.
5. Measure whether real users browse, search, click items, call, or request directions.

Production photo ingestion requires customer-value and labor/quality evidence. Bounded research and sales discovery may run alongside the trunk without changing production scope. Customer image uploads are deferred; the first search input is text.

## Start here
Read `AGENTS.md` first, then its prescribed order:
- `docs/CHARTER.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/MAP.md`
- `docs/PRODUCT.md` before product implementation
- `docs/HYPOTHESES.md` for experiments, strategic context and promotion gates

## Repository principle
The project separates:
- what exists → `docs/MAP.md` + code
- what matters now → `docs/STATUS.md`
- what comes later → `docs/ROADMAP.md`
- why architecture is shaped this way → `docs/adr/`
- what experiments actually established → `docs/EVIDENCE.md`

The dated September 2026 white paper is summarized and qualified in `docs/HYPOTHESES.md`; it is not implementation state, evidence, or a scope override. The repository is currently a scaffold, not a runnable application.

Git remembers history. `STATUS.md` should stay current and short.
