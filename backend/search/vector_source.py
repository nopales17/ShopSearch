"""Vector sources for ranking.

ADR-0004 replaces the positional whole-catalog index with a per-item embedding
binding. S3 ships the compatibility source: the committed CLIP index file, looked
up by item ID instead of position, so ranking behavior is unchanged this slice.
S4 adds the database-backed per-item source and index state.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Protocol

EMBEDDING_DIMENSIONS = 512


class VectorSourceError(ValueError):
    """Raised when a vector source is stale, malformed or missing an item."""


class VectorSource(Protocol):
    """Store-scoped provider of item embeddings."""

    def item_ids(self) -> frozenset[str]: ...

    def vector_for(self, item_id: str) -> tuple[float, ...]: ...


class CommittedIndexVectorSource:
    """Compatibility vector source over the committed whole-store index file."""

    def __init__(
        self,
        index_path: Path,
        *,
        expected_catalog_version: str,
        expected_model_id: str,
        expected_model_revision: str,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise VectorSourceError(f"could not load image index {index_path}: {error}") from error
        if index.get("catalog_version") != expected_catalog_version:
            raise VectorSourceError(
                "image index is stale or belongs to another catalog; rebuild it"
            )
        if (
            index.get("model_id") != expected_model_id
            or index.get("model_revision") != expected_model_revision
        ):
            raise VectorSourceError("image index belongs to another model; rebuild it")
        item_ids = index.get("item_ids")
        vectors = index.get("vectors")
        if not isinstance(item_ids, list) or not isinstance(vectors, list):
            raise VectorSourceError("image index must list item IDs and vectors")
        if len(item_ids) != len(vectors) or len(set(item_ids)) != len(item_ids):
            raise VectorSourceError("image index item identity is malformed")
        for vector in vectors:
            if (
                not isinstance(vector, list)
                or len(vector) != dimensions
                or any(not isinstance(value, (int, float)) for value in vector)
                or any(not math.isfinite(value) for value in vector)
            ):
                raise VectorSourceError("image index has invalid embedding dimensions")
        self._vectors = {
            str(item_id): tuple(float(value) for value in vector)
            for item_id, vector in zip(item_ids, vectors, strict=True)
        }

    def item_ids(self) -> frozenset[str]:
        return frozenset(self._vectors)

    def vector_for(self, item_id: str) -> tuple[float, ...]:
        try:
            return self._vectors[item_id]
        except KeyError:
            raise VectorSourceError(f"no embedding indexed for item {item_id}") from None
