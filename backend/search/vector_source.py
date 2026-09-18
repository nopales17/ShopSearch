"""Vector sources for ranking.

ADR-0004 replaces the positional whole-catalog index with a per-item embedding
binding. S4 makes the runtime source the store-scoped `embeddings` table, cached
per store and keyed by the catalog and index generations. The committed index file
remains only as the demo import/compatibility source.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Mapping, Protocol

from backend.catalog.store_repository import StoreGenerations
from contracts.store import StoreScope

EMBEDDING_DIMENSIONS = 512


class VectorSourceError(ValueError):
    """Raised when a vector source is stale, malformed or missing an item."""


@dataclass(frozen=True)
class VectorSnapshot:
    """Usable vectors for one store at one pair of store generations."""

    vectors: Mapping[str, tuple[float, ...]]
    catalog_generation: int
    index_generation: int

    def vector_for(self, item_id: str) -> tuple[float, ...] | None:
        return self.vectors.get(item_id)

    def matches(self, catalog: int, index: int) -> bool:
        return self.catalog_generation == catalog and self.index_generation == index


class VectorSource(Protocol):
    """Provider of the currently usable item embeddings for one store."""

    def current(self) -> VectorSnapshot: ...


class EmbeddingReader(Protocol):
    """Persistence the vector cache reads through."""

    def generations(self, scope: StoreScope) -> StoreGenerations: ...

    def ready_vectors(
        self,
        scope: StoreScope,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int,
    ) -> dict[str, tuple[float, ...]]: ...


class CommittedIndexVectorSource:
    """Import/compatibility source over the committed whole-store index file.

    S4 keeps this only for the demo vector import and for parity checks against the
    pre-S4 path; production retrieval reads `DatabaseVectorSource`.
    """

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
        self._snapshot = VectorSnapshot(
            {
                str(item_id): tuple(float(value) for value in vector)
                for item_id, vector in zip(item_ids, vectors, strict=True)
            },
            0,
            0,
        )

    def current(self) -> VectorSnapshot:
        return self._snapshot


class VectorCache:
    """Process-wide per-store cache keyed by the catalog and index generations.

    Every read re-checks the store generations, so an embedding write in another
    process (the reindex CLI) invalidates the cached snapshot on the next search.
    """

    def __init__(
        self,
        repository: EmbeddingReader,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self._repository = repository
        self._model_id = model_id
        self._model_revision = model_revision
        self._dimensions = dimensions
        self._snapshots: dict[str, VectorSnapshot] = {}
        self._lock = Lock()

    def snapshot(self, scope: StoreScope) -> VectorSnapshot:
        generations = self._repository.generations(scope)
        cached = self._snapshots.get(scope.store_id)
        if cached is not None and cached.matches(generations.catalog, generations.index):
            return cached
        vectors = self._repository.ready_vectors(
            scope,
            model_id=self._model_id,
            model_revision=self._model_revision,
            dimensions=self._dimensions,
        )
        snapshot = VectorSnapshot(dict(vectors), generations.catalog, generations.index)
        with self._lock:
            existing = self._snapshots.get(scope.store_id)
            if existing is not None and existing.matches(generations.catalog, generations.index):
                return existing
            self._snapshots[scope.store_id] = snapshot
        return snapshot


class DatabaseVectorSource:
    """Store-scoped runtime source over the cached embeddings table."""

    def __init__(self, cache: VectorCache, scope: StoreScope) -> None:
        self._cache = cache
        self._scope = scope

    def current(self) -> VectorSnapshot:
        return self._cache.snapshot(self._scope)
