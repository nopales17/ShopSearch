"""Cosine ranking over stored image vectors with deterministic price eligibility.

The vector source supplies embeddings by item ID (ADR-0004); ranking, price
semantics and the bounded semantic candidate set for price sorts are unchanged.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from backend.catalog.read_model import LoadedCatalog
from backend.search.price import parse_price
from backend.search.vector_source import VectorSource
from contracts.search import SearchQuery, SearchResponse, SearchResult


class TextEncoder(Protocol):
    def text(self, text: str) -> tuple[float, ...]: ...


class MultimodalSearchService:
    def __init__(
        self, catalog: LoadedCatalog, vector_source: VectorSource, encoder: TextEncoder
    ) -> None:
        self.catalog, self.encoder = catalog, encoder
        # Every item search may return needs a vector; a missing one is a source error.
        self.vectors = {
            item.item_id: vector_source.vector_for(item.item_id) for item in catalog.items
        }

    def search(self, query: SearchQuery) -> SearchResponse:
        if query.image_uri is not None or not 1 <= query.limit <= 100:
            raise ValueError("unsupported image query or result limit")
        if query.price_max is not None and (not query.price_max.is_finite() or query.price_max < 0):
            raise ValueError("price ceiling must be finite and nonnegative")
        parsed = parse_price(query.text or "")
        # Prices/categories never influence embeddings or become inventory truth.
        vector = self.encoder.text(parsed.visual) if parsed.visual else None
        scored = []
        for item in self.catalog.items:
            image = self.vectors[item.item_id]
            if not parsed.accepts(item.price) or (
                query.category and item.category != query.category
            ):
                continue
            if query.price_max is not None and (item.price is None or item.price > query.price_max):
                continue
            score = sum(a * b for a, b in zip(vector, image, strict=True)) if vector else 0.0
            scored.append((item.item_id, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        if parsed.sort != "relevance":
            # Bound semantic candidates before price ordering; no relevance threshold.
            # Without semantic text, order all eligible known-price items.
            if parsed.visual:
                scored = scored[:12]
            direction = 1 if parsed.sort == "price_asc" else -1

            def price_key(pair: tuple[str, float]) -> tuple[Decimal, str]:
                price = self.catalog.items_by_result(pair[0]).price
                assert price is not None  # QueryPlan excludes unknown prices for sorting.
                return direction * price, pair[0]

            scored.sort(key=price_key)
        results = tuple(
            SearchResult(item_id, score, True, rank)
            for rank, (item_id, score) in enumerate(scored[: query.limit], 1)
        )
        return SearchResponse(str(uuid4()), self.catalog.version, results, is_placeholder=False)
