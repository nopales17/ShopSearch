"""Server-rendered storefront; store-specific public copy comes from the store record.

S2 moved the demo store's wordmark, hero images, categories, query chips, credits
and public claim wording into store configuration (ADR-0005 §7). Structural
markup, generic UX labels and escaping stay here. Page bytes for the demo store
are pinned to S1 by a golden test.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from backend.catalog.read_model import LoadedCatalog
from backend.search.price import parse_price
from contracts.catalog import CatalogItem
from contracts.search import SearchCoverage
from contracts.store import HeroImage, Store, StorePresentation


def page(store: Store, title: str, body: str, active: str = "") -> str:
    presentation = store.presentation
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{escape(title)} · {presentation.page_title_suffix}</title><meta name="description" content="{presentation.meta_description}">
    <link rel="stylesheet" href="/static/pitch.css"><script src="/static/pitch.js" defer></script></head><body>
    <div class="demo-strip">{presentation.demo_strip}</div>
    <header><a class="wordmark" href="/" aria-label="{presentation.wordmark_aria_label}">{presentation.wordmark_primary} <span>{presentation.wordmark_accent}</span> {presentation.wordmark_suffix}</a>
    <nav aria-label="Main navigation"><a {'aria-current="page"' if active == "catalog" else ""} href="/catalog">{presentation.catalog_nav_label} <span>↗</span></a><a href="/#about">{presentation.about_nav_label}</a></nav></header>
    {body}
    <footer id="about"><div><a class="wordmark" href="/">{presentation.wordmark_primary} <span>{presentation.wordmark_accent}</span> {presentation.wordmark_suffix}</a><p>{presentation.tagline}</p></div>
    <div class="footer-note">{presentation.footer_disclosure} <a href="/credits">{presentation.footer_credits_label} ↗</a></div></footer>
    <dialog id="demo-dialog"><button class="dialog-close" aria-label="Close dialog">×</button><p class="eyebrow">{presentation.dialog_eyebrow}</p><h2 id="dialog-title">{presentation.dialog_title}</h2><p id="dialog-copy">{presentation.dialog_copy}</p><button class="primary dialog-done">{presentation.dialog_done_label}</button></dialog>
    </body></html>"""


def card(
    item: CatalogItem,
    presentation: StorePresentation,
    search_id: str | None = None,
    query: str = "",
) -> str:
    params = {"q": query}
    if search_id:
        params["search_id"] = search_id
    link = f"/items/{item.item_id}?{urlencode(params)}"
    price = f"${item.price:.0f}" if item.price is not None else presentation.price_unknown_label
    return f'''<article class="product"><a class="product-image" href="{escape(link)}" aria-label="View {escape(item.title or "")}"><img src="{escape(item.image_uri or "")}" alt="{escape(item.title or "")}" loading="lazy" width="600" height="600"><span class="image-arrow" aria-hidden="true">↗</span></a>
    <div class="product-meta"><div><p class="product-category">{escape(item.category or "")}</p><h3><a href="{escape(link)}">{escape(item.title or "")}</a></h3></div><span class="price">{price}<small>{presentation.card_price_label}</small></span></div></article>'''


def home(catalog: LoadedCatalog, store: Store) -> str:
    presentation = store.presentation
    main = _hero(presentation, "main")
    inset = _hero(presentation, "inset")
    discover_url = "/catalog?" + urlencode({"q": presentation.discover_example_query})
    featured = "".join(card(item, presentation) for item in catalog.items[:4])
    footnote = presentation.hero_footnote_template.format(count=len(catalog.items))
    return page(
        store,
        "Objects worth discovering",
        f"""
    <main><section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> {presentation.hero_eyebrow}</p>
    <h1>{presentation.hero_title_html}</h1><p class="hero-description">{presentation.hero_description}</p>
    <a class="primary" href="/catalog">{presentation.hero_cta_label} <span>↗</span></a><span class="hero-footnote">{footnote}</span></div>
    <div class="hero-gallery"><img class="hero-main" src="{main.src}" alt="{main.alt}" width="{main.width}" height="{main.height}"><div class="hero-inset"><img src="{inset.src}" alt="{inset.alt}" width="{inset.width}" height="{inset.height}"><span>{inset.label}</span></div><span class="hero-label">{main.label}</span></div></section>
    <section class="discover-band"><span>{presentation.discover_heading_html}</span><a href="{discover_url}">“{presentation.discover_example_query}” <span>→</span></a></section>
    <section class="featured"><div class="section-heading"><div><p class="eyebrow">{presentation.featured_eyebrow}</p><h2>{presentation.featured_heading}</h2></div><a class="text-link" href="/catalog">{presentation.featured_link_label} ↗</a></div><div class="product-grid">{featured}</div></section></main>""",
    )


def catalog_page(catalog: LoadedCatalog, store: Store, query: str = "") -> str:
    presentation = store.presentation
    cards = "".join(card(item, presentation) for item in catalog.items)
    chips = "".join(
        f'<button type="button" class="query-chip" data-query="{escape(example)}">'
        f"{escape(example)} <span>↗</span></button>"
        for example in presentation.example_queries
    )
    categories = "".join(f"<option>{name}</option>" for name in presentation.categories)
    summary = presentation.results_summary_template.format(count=len(catalog.items))
    return page(
        store,
        "Explore the collection",
        f'''
    <main class="catalog-main"><div class="catalog-title"><p class="eyebrow">{presentation.catalog_eyebrow}</p><h1>{presentation.catalog_title_html}</h1><p>{presentation.catalog_intro}</p></div>
    <form id="search-form" action="/catalog" method="get"><label class="sr-only" for="query">Describe what you're looking for</label><span class="search-icon" aria-hidden="true">⌕</span><input id="query" name="q" maxlength="500" placeholder="{presentation.search_placeholder}" value="{escape(query)}" autocomplete="off"><button class="primary" type="submit">Search <span>→</span></button></form>
    <div class="query-chips"><span>{presentation.query_chips_label}</span>{chips}</div>
    <div class="collection-toolbar"><p id="result-summary" aria-live="polite">{summary}</p><label for="category">Browse <select id="category"><option value="">All objects</option>{categories}</select></label></div>
    <div class="search-context"><span id="applied-filter"></span><button type="button" id="clear-search" hidden>Clear search ×</button></div>
    <p id="search-error" role="alert" hidden></p><section id="results" class="product-grid" aria-label="Collection results">{cards}</section>
    <noscript><p>{presentation.noscript_notice}</p></noscript>
    <p class="catalog-disclaimer">{presentation.catalog_disclaimer}</p></main>''',
        "catalog",
    )


def item_page(item: CatalogItem, store: Store, query: str, search_id: str | None) -> str:
    presentation = store.presentation
    source = item.attributes
    price = f"${item.price:.2f}" if item.price is not None else presentation.price_unknown_label
    params = urlencode({"q": query})
    materials = str(source.get("materials") or "").strip()
    description = (
        presentation.item_description_template.format(materials=materials.capitalize())
        if materials
        else presentation.item_description_plain
    )
    source_url = str(source.get("source_url") or "").strip()
    # S11 mixed provenance: inside the demo, an item the merchant uploaded is rendered
    # as a local demo upload. It never inherits the committed museum collection's
    # original title, measurements, CMA/CC0 attribution, accession or source link.
    local_demo_upload = store.is_demo and source.get("merchant_upload") is True
    if local_demo_upload:
        details = (
            f"<dl><div><dt>Photo source</dt>"
            f"<dd>{escape(presentation.item_upload_source_value)}</dd></div></dl>"
        )
        fine_print = presentation.item_upload_fine_print_html
        source_link = ""
    else:
        details = (
            f"<dl><div><dt>Original title</dt>"
            f"<dd>{escape(source.get('source_title') or item.title or '')}</dd></div>"
            f"<div><dt>Dimensions</dt>"
            f"<dd>{escape(source.get('measurements') or 'Not recorded in this source')}</dd></div>"
            f"<div><dt>Photo source</dt><dd>{presentation.item_source_value}</dd></div></dl>"
        )
        fine_print = presentation.item_fine_print_html
        source_link = (
            f'<a class="text-link" href="{escape(source_url)}" target="_blank" rel="noopener noreferrer">{presentation.item_source_link_label} ↗</a>'
            if source_url
            else ""
        )
    return page(
        store,
        item.title or "Object",
        f'''
    <main class="detail-main"><a class="back-link" href="/catalog?{escape(params)}">← Back to the collection</a><div class="detail-layout"><div class="detail-image"><img src="{escape(item.image_uri or "")}" alt="{escape(item.title or "")}" width="900" height="1000"></div>
    <div class="detail-copy"><p class="eyebrow">{escape(item.category or "")} / {presentation.item_collection_suffix}</p><h1>{escape(item.title or "")}</h1><p class="detail-price">{price} <span>{presentation.item_price_label}</span></p>
    <p class="detail-description">{escape(description)}</p>
    {details}
    <div class="detail-actions"><button class="primary demo-action" data-kind="call" data-item="{item.item_id}" data-search="{escape(search_id or "")}">Call the shop <span>↗</span></button><button class="secondary demo-action" data-kind="directions" data-item="{item.item_id}" data-search="{escape(search_id or "")}">Get directions <span>↗</span></button></div>
    <p class="fine-print">{fine_print}</p>{source_link}</div></div></main>''',
    )


def result_payload(
    catalog: LoadedCatalog,
    store: Store,
    items: tuple[CatalogItem, ...],
    query: str,
    search_id: str | None,
    elapsed_ms: float,
    coverage: SearchCoverage | None = None,
) -> dict[str, object]:
    parsed = parse_price(query)
    filter_label = parsed.label()
    return {
        "html": "".join(card(item, store.presentation, search_id, query) for item in items),
        "count": len(items),
        "search_id": search_id,
        "filter_label": filter_label,
        "elapsed_ms": round(elapsed_ms, 2),
        "coverage": (
            {
                "published": coverage.published,
                "ready": coverage.ready,
                "excluded_unindexed": coverage.excluded_unindexed,
                "visual_text": coverage.visual_text,
            }
            if coverage is not None
            else None
        ),
        "coverage_html": coverage_notice(store, coverage),
    }


def coverage_notice(store: Store, coverage: SearchCoverage | None) -> str:
    """Disclose missing description coverage; never an absence or stock claim."""

    if coverage is None or not coverage.visual_text or coverage.excluded_unindexed < 1:
        return ""
    presentation = store.presentation
    sentence = presentation.coverage_disclosure_template.format(
        excluded=coverage.excluded_unindexed, published=coverage.published
    )
    return (
        f'<p class="coverage-notice">{sentence} '
        f'<a href="/catalog">{escape(presentation.coverage_browse_label)}</a></p>'
    )


def credits(catalog: LoadedCatalog, store: Store) -> str:
    presentation = store.presentation
    rows = "".join(
        f'<li><a href="{escape(item.attributes["source_url"])}">{escape(item.title or "")}</a> — {escape(item.attributes["accession_number"])} · {escape(item.attributes["license"])}</li>'
        for item in catalog.items
        if str(item.attributes.get("source_url") or "").strip()
        and item.attributes.get("merchant_upload") is not True
    )
    return page(
        store,
        "Photo credits",
        f'<main class="credits"><p class="eyebrow">{presentation.credits_eyebrow}</p><h1>{presentation.credits_title_html}</h1><p>{presentation.credits_copy_html}</p><p><a href="{presentation.credits_policy_url}">{presentation.credits_policy_label}</a></p><ul>{rows}</ul></main>',
    )


def _hero(presentation: StorePresentation, role: str) -> HeroImage:
    return next(image for image in presentation.hero_images if image.role == role)
