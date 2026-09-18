from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.store_repository import CatalogRepository
from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.multimodal import MultimodalSearchService
from backend.search.vector_source import DatabaseVectorSource, VectorCache
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import (
    CaptureTimeSource,
    EvidenceRef,
    IndexState,
    ListingState,
    ObservationSource,
)
from contracts.search import SearchQuery
from tests.unit.test_pitch import StubEncoder

DIMENSIONS = 512


class IndexStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database_path = self.root / "shopsearch.sqlite3"
        self.stores = StoreRepository.open(self.database_path)
        self.repository = CatalogRepository.open(self.database_path)
        self.addCleanup(self.repository.close)
        self.addCleanup(self.stores.close)
        self.store = seed_store(self.stores, DEFAULT_DEMO_STORE_PATH)
        self.scope = self.store.scope
        self.vector_cache = VectorCache(
            self.repository, model_id=MODEL_ID, model_revision=MODEL_REVISION
        )

    def add_item(
        self,
        item_id: str,
        *,
        price: str = "10.00",
        category: str = "Bowls",
        sort_order: int = 0,
        listing_state: ListingState = ListingState.PUBLISHED,
        index_state: IndexState = IndexState.PENDING,
    ) -> str:
        image_sha = hashlib.sha256(item_id.encode()).hexdigest()
        self.repository.create_item(
            self.scope,
            item_id=item_id,
            title=item_id,
            category=category,
            price=Decimal(price),
            price_kind="known",
            attributes={"source_title": item_id},
            provenance=(
                EvidenceRef(
                    ObservationSource.MANUAL,
                    f"source-{item_id}",
                    datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
            ),
            catalog_version="test-v1",
            sort_order=sort_order,
            listing_state=listing_state,
            index_state=index_state,
        )
        self.repository.add_image(
            self.scope,
            item_id=item_id,
            sha256=image_sha,
            source_sha256=image_sha,
            media_type="image/jpeg",
            width=8,
            height=8,
            byte_size=8,
            capture_time=None,
            capture_time_source=CaptureTimeSource.UNKNOWN,
        )
        return image_sha

    def index(self, item_id: str, *, model_revision: str = MODEL_REVISION, dim: int = DIMENSIONS):
        image = self.repository.display_image(self.scope, item_id)
        assert image is not None
        return self.repository.put_ready_embedding(
            self.scope,
            item_id=item_id,
            vector=tuple(0.1 for _ in range(dim)),
            model_id=MODEL_ID,
            model_revision=model_revision,
            image_sha256=image.sha256,
        )

    def service(self) -> MultimodalSearchService:
        catalog = self.repository.loaded_catalog(self.store)
        source = DatabaseVectorSource(self.vector_cache, self.scope)
        return MultimodalSearchService(catalog, source, StubEncoder())

    def summary(self):
        return self.repository.index_summary(
            self.scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=DIMENSIONS
        )

    def test_only_ready_items_rank_and_unindexed_items_stay_browsable(self) -> None:
        self.add_item("item-ready", price="10.00")
        self.add_item("item-pending", price="20.00", category="Vases")
        self.add_item("item-failed", price="30.00", category="Vases")
        self.add_item("item-stale", price="40.00", category="Vases")
        self.index("item-ready")
        self.index("item-stale", model_revision="another-revision")
        self.repository.mark_index_failed(
            self.scope, item_id="item-failed", attempts=3, error="RuntimeError: model unavailable"
        )
        service = self.service()

        ranked = service.search(SearchQuery(text="small blue one", limit=100))
        self.assertEqual([r.item_id for r in ranked.results], ["item-ready"])
        coverage = ranked.coverage
        assert coverage is not None
        self.assertEqual(
            (coverage.published, coverage.ready, coverage.excluded_unindexed), (4, 1, 3)
        )
        self.assertTrue(coverage.visual_text)

        browse = service.search(SearchQuery(text="", limit=100))
        self.assertEqual(
            {r.item_id for r in browse.results},
            {"item-ready", "item-pending", "item-failed", "item-stale"},
        )
        assert browse.coverage is not None
        self.assertFalse(browse.coverage.visual_text)

        category = service.search(SearchQuery(text="", category="Vases", limit=100))
        self.assertEqual(
            {r.item_id for r in category.results},
            {"item-pending", "item-failed", "item-stale"},
        )

        price_bound = service.search(SearchQuery(text="under $50", limit=100))
        self.assertEqual(len(price_bound.results), 4)

        price_sort = service.search(SearchQuery(text="cheapest one", limit=100))
        self.assertEqual(
            [r.item_id for r in price_sort.results],
            ["item-ready", "item-pending", "item-failed", "item-stale"],
        )

    def test_foreign_model_embedding_is_stale_and_never_ranked(self) -> None:
        self.add_item("item-foreign")
        self.index("item-foreign", model_revision="another-revision")
        record = self.repository.embedding_for(self.scope, "item-foreign")
        self.assertIsNotNone(record)  # Still reported, just not usable.
        summary = self.summary()
        self.assertEqual((summary.ready, summary.stale, summary.excluded_unindexed), (0, 1, 1))
        result = self.service().search(SearchQuery(text="blue", limit=100))
        self.assertEqual(result.results, ())
        assert result.coverage is not None
        self.assertEqual(result.coverage.excluded_unindexed, 1)

    def test_embedding_raw_image_bound_elsewhere_is_stale_and_never_ranked(self) -> None:
        image_sha = self.add_item("item-drifted")
        self.index("item-drifted")
        database = platform_db.Database.open(self.database_path)
        try:
            with database.connection() as connection:
                connection.execute(
                    "UPDATE embeddings SET image_sha256 = ? WHERE store_id = ? AND item_id = ?",
                    ("f" * 64, self.scope.store_id, "item-drifted"),
                )
        finally:
            database.close()
        self.assertNotEqual(image_sha, "f" * 64)
        summary = self.summary()
        self.assertEqual((summary.ready, summary.stale, summary.excluded_unindexed), (0, 1, 1))
        result = self.service().search(SearchQuery(text="blue", limit=100))
        self.assertEqual(result.results, ())

    def test_stored_ready_without_a_valid_binding_is_stale_not_ranked(self) -> None:
        self.add_item("item-mismatch")
        self.index("item-mismatch", dim=8)
        summary = self.summary()
        self.assertEqual((summary.ready, summary.stale), (0, 1))
        self.assertEqual(self.service().search(SearchQuery(text="blue")).results, ())
