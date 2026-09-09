"""Server-rendered photographic boutique demo; all public copy is demo-scoped."""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from backend.catalog.repository import LoadedCatalog
from backend.search.price import parse_price
from contracts.catalog import CatalogItem

EXAMPLES = [
    "small blue one",
    "colorful",
    "simple clear one",
    "dark and weird",
    "under $50",
    "small blue under $50",
]


def page(title: str, body: str, active: str = "") -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{escape(title)} · Form & Field demo</title><meta name="description" content="Explore a curated photographic demo of glass, vessels and curious objects. Illustrative prices; no live inventory.">
    <link rel="stylesheet" href="/static/pitch.css"><script src="/static/pitch.js" defer></script></head><body>
    <div class="demo-strip">A specialty-retail demo · Real object photographs · Illustrative prices</div>
    <header><a class="wordmark" href="/" aria-label="Form and Field home">FORM <span>&</span> FIELD</a>
    <nav aria-label="Main navigation"><a {'aria-current="page"' if active == "catalog" else ""} href="/catalog">The collection <span>↗</span></a><a href="/#about">About this demo</a></nav></header>
    {body}
    <footer id="about"><div><a class="wordmark" href="/">FORM <span>&</span> FIELD</a><p>An imagined shop. A real way to explore.</p></div>
    <div class="footer-note">Manually curated with CC0 photographs from the Cleveland Museum of Art. These collection objects are not offered for sale. Prices are illustrative, not valuations. No shop adoption, live stock or automated photo ingestion is implied. <a href="/credits">Photo credits ↗</a></div></footer>
    <dialog id="demo-dialog"><button class="dialog-close" aria-label="Close dialog">×</button><p class="eyebrow">PREVIEW ONLY</p><h2 id="dialog-title">A connection to your shop.</h2><p id="dialog-copy">In a real shop, this would connect visitors with the business. This demo sends no calls and opens no directions.</p><button class="primary dialog-done">Got it</button></dialog>
    </body></html>"""


def card(item: CatalogItem, search_id: str | None = None, query: str = "") -> str:
    params = {"q": query}
    if search_id:
        params["search_id"] = search_id
    link = f"/items/{item.item_id}?{urlencode(params)}"
    price = f"${item.price:.0f}" if item.price is not None else "Price not set"
    return f'''<article class="product"><a class="product-image" href="{escape(link)}" aria-label="View {escape(item.title or "")}"><img src="{escape(item.image_uri or "")}" alt="{escape(item.title or "")}" loading="lazy" width="600" height="600"><span class="image-arrow" aria-hidden="true">↗</span></a>
    <div class="product-meta"><div><p class="product-category">{escape(item.category or "")}</p><h3><a href="{escape(link)}">{escape(item.title or "")}</a></h3></div><span class="price">{price}<small>demo price</small></span></div></article>'''


def home(catalog: LoadedCatalog) -> str:
    featured = "".join(card(item) for item in catalog.items[:4])
    return page(
        "Objects worth discovering",
        f"""
    <main><section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> GLASS, VESSELS & CURIOUS OBJECTS</p>
    <h1>Good things.<br><em>Found here.</em></h1><p class="hero-description">A little color. An unexpected shape. Something that feels like you. Take a closer look at the collection.</p>
    <a class="primary" href="/catalog">See What's In Store <span>↗</span></a><span class="hero-footnote">{len(catalog.items)} objects to explore · A curated demo collection</span></div>
    <div class="hero-gallery"><img class="hero-main" src="/images/pitch-128096.jpg" alt="Sapphire blue glass bowl" width="600" height="720"><div class="hero-inset"><img src="/images/pitch-160044.jpg" alt="Iridescent blue and amber vase" width="320" height="420"><span>AN EYE FOR THE UNEXPECTED</span></div><span class="hero-label">01 / A STUDY IN BLUE</span></div></section>
    <section class="discover-band"><span>Don't know its name?<br><strong>Describe what catches your eye.</strong></span><a href="/catalog?q=small+blue+one">“small blue one” <span>→</span></a></section>
    <section class="featured"><div class="section-heading"><div><p class="eyebrow">THE COLLECTION</p><h2>A few things to fall for.</h2></div><a class="text-link" href="/catalog">Explore all objects ↗</a></div><div class="product-grid">{featured}</div></section></main>""",
    )


def catalog_page(catalog: LoadedCatalog, query: str = "") -> str:
    cards = "".join(card(item) for item in catalog.items)
    chips = "".join(
        f'<button type="button" class="query-chip" data-query="{escape(q)}">{escape(q)} <span>↗</span></button>'
        for q in EXAMPLES
    )
    categories = "".join(
        f"<option>{name}</option>" for name in ["Vases", "Bowls", "Drinkware", "Curios"]
    )
    return page(
        "Explore the collection",
        f'''
    <main class="catalog-main"><div class="catalog-title"><p class="eyebrow">SEE WHAT'S IN STORE</p><h1>Find your kind of <em>different.</em></h1><p>Search by color, shape, mood or price. There's no need to know the name.</p></div>
    <form id="search-form" action="/catalog" method="get"><label class="sr-only" for="query">Describe what you're looking for</label><span class="search-icon" aria-hidden="true">⌕</span><input id="query" name="q" maxlength="500" placeholder="Try “small blue one under $50”" value="{escape(query)}" autocomplete="off"><button class="primary" type="submit">Search <span>→</span></button></form>
    <div class="query-chips"><span>Try a little inspiration</span>{chips}</div>
    <div class="collection-toolbar"><p id="result-summary" aria-live="polite">{len(catalog.items)} objects in the demo collection</p><label for="category">Browse <select id="category"><option value="">All objects</option>{categories}</select></label></div>
    <div class="search-context"><span id="applied-filter"></span><button type="button" id="clear-search" hidden>Clear search ×</button></div>
    <p id="search-error" role="alert" hidden></p><section id="results" class="product-grid" aria-label="Collection results">{cards}</section>
    <noscript><p>JavaScript is needed for instant search in this local demo. You can still browse and open all objects.</p></noscript>
    <p class="catalog-disclaimer">Real photographs, manually selected. Illustrative prices. Visual similarity does not confirm availability.</p></main>''',
        "catalog",
    )


def item_page(item: CatalogItem, query: str, search_id: str | None) -> str:
    source = item.attributes
    price = f"${item.price:.2f}" if item.price is not None else "Price not set"
    params = urlencode({"q": query})
    return page(
        item.title or "Object",
        f'''
    <main class="detail-main"><a class="back-link" href="/catalog?{escape(params)}">← Back to the collection</a><div class="detail-layout"><div class="detail-image"><img src="{escape(item.image_uri or "")}" alt="{escape(item.title or "")}" width="900" height="1000"></div>
    <div class="detail-copy"><p class="eyebrow">{escape(item.category or "")} / THE DEMO COLLECTION</p><h1>{escape(item.title or "")}</h1><p class="detail-price">{price} <span>illustrative demo price</span></p>
    <p class="detail-description">{escape(source["materials"].capitalize())}. A closer look at the color, texture and details that make this object distinctive.</p>
    <dl><div><dt>Original title</dt><dd>{escape(source["source_title"])}</dd></div><div><dt>Dimensions</dt><dd>{escape(source.get("measurements") or "Not recorded in this source")}</dd></div><div><dt>Photo source</dt><dd>The Cleveland Museum of Art · CC0</dd></div></dl>
    <div class="detail-actions"><button class="primary demo-action" data-kind="call" data-item="{item.item_id}" data-search="{escape(search_id or "")}">Call the shop <span>↗</span></button><button class="secondary demo-action" data-kind="directions" data-item="{item.item_id}" data-search="{escape(search_id or "")}">Get directions <span>↗</span></button></div>
    <p class="fine-print">Demo actions only. No real business is contacted.<br>This museum object is not for sale. Photo date and current availability are not asserted.</p><a class="text-link" href="{escape(source["source_url"])}" target="_blank" rel="noopener noreferrer">View the original source ↗</a></div></div></main>''',
    )


def result_payload(
    catalog: LoadedCatalog,
    items: tuple[CatalogItem, ...],
    query: str,
    search_id: str | None,
    elapsed_ms: float,
) -> dict[str, object]:
    parsed = parse_price(query)
    filter_label = parsed.label()
    return {
        "html": "".join(card(item, search_id, query) for item in items),
        "count": len(items),
        "search_id": search_id,
        "filter_label": filter_label,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def credits(catalog: LoadedCatalog) -> str:
    rows = "".join(
        f'<li><a href="{escape(item.attributes["source_url"])}">{escape(item.title or "")}</a> — {escape(item.attributes["accession_number"])} · CC0</li>'
        for item in catalog.items
    )
    return page(
        "Photo credits",
        f'<main class="credits"><p class="eyebrow">SOURCE & PERMISSION</p><h1>Real objects.<br><em>Open photographs.</em></h1><p>All photographs are credited to the Cleveland Museum of Art and designated CC0 in its collection API. They are used unchanged as a manually curated demo assortment; no endorsement or sale is implied.</p><p><a href="https://www.clevelandart.org/open-access">CMA Open Access policy ↗</a></p><ul>{rows}</ul></main>',
    )
