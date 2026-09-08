"""Deliberately simple, deterministic fixture ranking for Issue #1."""

from __future__ import annotations

from collections import Counter
from uuid import uuid4

from backend.catalog.repository import LoadedCatalog
from contracts.search import SearchQuery, SearchResponse, SearchResult


class PlaceholderSearchService:
    """Ranks fixture text by token overlap; it is not semantic retrieval."""

    def __init__(self, catalog: LoadedCatalog) -> None:
        self._catalog = catalog

    def search(self, query: SearchQuery) -> SearchResponse:
        if query.image_uri is not None:
            raise ValueError("image queries are not supported")
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if query.price_max is not None and (not query.price_max.is_finite() or query.price_max < 0):
            raise ValueError("price_max must be finite and nonnegative")
        tokens = _tokens(query.text or "")
        candidates = [
            item
            for item in self._catalog.items
            if _matches_category(item.category, query.category)
            and (
                query.price_max is None
                or (item.price is not None and item.price <= query.price_max)
            )
        ]
        ranked = sorted(
            candidates,
            key=lambda item: (
                -_score(tokens, item.title or "", item.category or "", item.attributes),
                item.item_id,
            ),
        )[: query.limit]
        results = tuple(
            SearchResult(
                item_id=item.item_id,
                semantic_score=float(
                    _score(tokens, item.title or "", item.category or "", item.attributes)
                ),
                filters_satisfied=True,
                rank=index,
                explanation=None,
            )
            for index, item in enumerate(ranked, start=1)
        )
        return SearchResponse(
            search_id=str(uuid4()), catalog_version=self._catalog.version, results=results
        )


def _tokens(text: str) -> Counter[str]:
    return Counter(part.lower() for part in text.replace("-", " ").split() if part)


def _score(tokens: Counter[str], title: str, category: str, attributes: dict[str, object]) -> int:
    haystack = " ".join([title, category, *[str(value) for value in attributes.values()]]).lower()
    return sum(count for token, count in tokens.items() if token in haystack)


def _matches_category(item_category: str | None, category: str | None) -> bool:
    return category is None or item_category == category
