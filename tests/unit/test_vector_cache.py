from __future__ import annotations

import unittest

from backend.catalog.store_repository import StoreGenerations
from backend.search.vector_source import DatabaseVectorSource, VectorCache
from contracts.store import StoreScope


class FakeEmbeddingReader:
    """Records cache lookups so generation-keyed invalidation is observable."""

    def __init__(self, vectors: dict[str, tuple[float, ...]] | None = None) -> None:
        self.generations_calls = 0
        self.vector_calls = 0
        self.generation = StoreGenerations(1, 1)
        self.vectors = vectors or {"item-a": (1.0, 0.0)}
        self.forwarded: list[tuple[str, str, int, str]] = []

    def generations(self, scope: StoreScope) -> StoreGenerations:
        self.generations_calls += 1
        return self.generation

    def ready_vectors(
        self, scope: StoreScope, *, model_id: str, model_revision: str, dimensions: int
    ) -> dict[str, tuple[float, ...]]:
        self.vector_calls += 1
        self.forwarded.append((scope.store_id, model_id, dimensions, model_revision))
        return dict(self.vectors)

    def bump(self, *, catalog: int = 0, index: int = 0, vectors=None) -> None:
        self.generation = StoreGenerations(
            self.generation.catalog + catalog, self.generation.index + index
        )
        if vectors is not None:
            self.vectors = vectors


class VectorCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.reader = FakeEmbeddingReader()
        self.cache = VectorCache(
            self.reader, model_id="model-a", model_revision="rev-1", dimensions=2
        )
        self.scope = StoreScope("pitch-demo")

    def test_snapshot_is_reused_while_generations_are_unchanged(self) -> None:
        first = self.cache.snapshot(self.scope)
        second = self.cache.snapshot(self.scope)
        self.assertIs(first, second)
        self.assertEqual(self.reader.vector_calls, 1)
        # Generations are re-checked on every lookup so another process can invalidate.
        self.assertEqual(self.reader.generations_calls, 2)
        self.assertEqual(first.catalog_generation, 1)
        self.assertEqual(first.index_generation, 1)
        self.assertEqual(self.reader.forwarded[0], ("pitch-demo", "model-a", 2, "rev-1"))

    def test_index_generation_bump_rebuilds_and_swaps_content(self) -> None:
        first = self.cache.snapshot(self.scope)
        self.assertEqual(first.vector_for("item-a"), (1.0, 0.0))
        self.reader.bump(index=1, vectors={"item-b": (0.0, 1.0)})
        second = self.cache.snapshot(self.scope)
        self.assertIsNot(first, second)
        self.assertEqual(second.vector_for("item-a"), None)
        self.assertEqual(second.vector_for("item-b"), (0.0, 1.0))
        self.assertEqual(second.index_generation, 2)
        self.assertEqual(self.reader.vector_calls, 2)

    def test_catalog_generation_bump_rebuilds(self) -> None:
        first = self.cache.snapshot(self.scope)
        self.reader.bump(catalog=1, vectors={"item-a": (0.5, 0.5)})
        second = self.cache.snapshot(self.scope)
        self.assertIsNot(first, second)
        self.assertEqual(second.vector_for("item-a"), (0.5, 0.5))
        self.assertEqual(second.catalog_generation, 2)
        self.assertEqual(self.reader.vector_calls, 2)

    def test_unknown_items_have_no_vector_rather_than_an_error(self) -> None:
        snapshot = self.cache.snapshot(self.scope)
        self.assertIsNone(snapshot.vector_for("item-missing"))

    def test_database_source_delegates_to_the_cache_for_its_scope(self) -> None:
        source = DatabaseVectorSource(self.cache, self.scope)
        self.assertIs(source.current(), self.cache.snapshot(self.scope))
        self.assertEqual(self.reader.vector_calls, 1)
