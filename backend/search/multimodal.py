"""Image-only CLIP index with deterministic price eligibility and cosine ranking."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.repository import LoadedCatalog
from backend.search.price import parse_price
from contracts.search import SearchQuery, SearchResponse, SearchResult


class TextEncoder(Protocol):
    def text(self, text: str) -> tuple[float, ...]: ...


class MultimodalSearchService:
    def __init__(self, catalog: LoadedCatalog, index_path: Path, encoder: TextEncoder) -> None:
        index = json.loads(index_path.read_text())
        if (
            index["catalog_version"] != catalog.version
            or index["model_revision"] != MODEL_REVISION
            or index["model_id"] != MODEL_ID
        ):
            raise ValueError("image index is stale or belongs to another model/catalog; rebuild it")
        if index["item_ids"] != [item.item_id for item in catalog.items]:
            raise ValueError("index item identity mismatch")
        self.catalog, self.encoder = catalog, encoder
        self.vectors = index["vectors"]
        if len(self.vectors) != len(catalog.items) or any(len(v) != 512 for v in self.vectors):
            raise ValueError("invalid CLIP index dimensions")
        if any(not math.isfinite(x) for vector in self.vectors for x in vector):
            raise ValueError("non-finite embedding")

    def search(self, query: SearchQuery) -> SearchResponse:
        if query.image_uri is not None or not 1 <= query.limit <= 100:
            raise ValueError("unsupported image query or result limit")
        if query.price_max is not None and (not query.price_max.is_finite() or query.price_max < 0):
            raise ValueError("price ceiling must be finite and nonnegative")
        parsed = parse_price(query.text or "")
        # Prices/categories never influence embeddings or become inventory truth.
        vector = self.encoder.text(parsed.visual) if parsed.visual else None
        scored = []
        for item, image in zip(self.catalog.items, self.vectors, strict=True):
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
