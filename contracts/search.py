from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class SearchQuery:
    text: str | None = None
    image_uri: str | None = None
    price_max: Decimal | None = None
    category: str | None = None
    limit: int = 12


@dataclass(frozen=True)
class SearchResult:
    item_id: str
    semantic_score: float
    filters_satisfied: bool
    rank: int
    explanation: str | None = None


@dataclass(frozen=True)
class SearchResponse:
    search_id: str
    catalog_version: str
    results: tuple[SearchResult, ...]
    is_placeholder: bool = True


class SearchService(Protocol):
    def search(self, query: SearchQuery) -> SearchResponse: ...
