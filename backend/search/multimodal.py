"""Cosine ranking over stored image vectors with deterministic price eligibility.

The vector source supplies per-item embeddings (ADR-0004). Ranking, price
semantics, the bounded semantic candidate set for price sorts and deterministic
ordering are unchanged; S4 only adds query routing and coverage reporting so that
publication never depends on indexing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from backend.catalog.read_model import LoadedCatalog
from backend.search.price import parse_price
from backend.search.vector_source import VectorSource
from contracts.search import SearchCoverage, SearchQuery, SearchResponse, SearchResult


class TextEncoder(Protocol):
    def text(self, text: str) -> tuple[float, ...]: ...


class MultimodalSearchService:
    def __init__(
        self, catalog: LoadedCatalog, vector_source: VectorSource, encoder: TextEncoder
    ) -> None:
        self.catalog, self.vector_source, self.encoder = catalog, vector_source, encoder

    def search(self, query: SearchQuery) -> SearchResponse:
        if query.image_uri is not None or not 1 <= query.limit <= 100:
            raise ValueError("unsupported image query or result limit")
        if query.price_max is not None and (not query.price_max.is_finite() or query.price_max < 0):
            raise ValueError("price ceiling must be finite and nonnegative")
        parsed = parse_price(query.text or "")
        snapshot = self.vector_source.current()
        visual_text = bool(parsed.visual)
        # Prices/categories never influence embeddings or become inventory truth.
        vector = self.encoder.text(parsed.visual) if visual_text else None
        scored = []
        for item in self.catalog.items:
            if not parsed.accepts(item.price) or (
                query.category and item.category != query.category
            ):
                continue
            if query.price_max is not None and (item.price is None or item.price > query.price_max):
                continue
            if visual_text:
                # Only visual-text retrieval needs a ready embedding; browse,
                # category and price-only paths never depend on index state.
                assert vector is not None
                image = snapshot.vector_for(item.item_id)
                if image is None:
                    continue
                score = sum(a * b for a, b in zip(vector, image, strict=True))
            else:
                score = 0.0
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
        ready = sum(
            1 for item in self.catalog.items if snapshot.vector_for(item.item_id) is not None
        )
        return SearchResponse(
            str(uuid4()),
            self.catalog.version,
            results,
            is_placeholder=False,
            coverage=SearchCoverage(
                published=len(self.catalog.items),
                ready=ready,
                excluded_unindexed=len(self.catalog.items) - ready,
                visual_text=visual_text,
            ),
        )
