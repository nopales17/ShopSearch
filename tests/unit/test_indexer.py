from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.indexer import EmbeddingIndexer, IndexerConfig
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import (
    CaptureTimeSource,
    EvidenceRef,
    IndexState,
    ListingState,
    ObservationSource,
)

DIMENSIONS = 512


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (8, 8), (10, 20, 30))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class FlakyEncoder:
    """Fails a fixed number of times, then returns a usable embedding."""

    def __init__(self, failures: int = 0, dimensions: int = DIMENSIONS) -> None:
        self.failures = failures
        self.calls = 0
        self.dimensions = dimensions

    def images(self, images: list[Any]) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("model unavailable")
        return [[0.25] * self.dimensions for _ in images]


class IndexerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.stores = StoreRepository.open(root / "shopsearch.sqlite3")
        self.repository = CatalogRepository.open(root / "shopsearch.sqlite3")
        self.image_store = LocalImageStore(root / "media")
        self.addCleanup(self.repository.close)
        self.addCleanup(self.stores.close)
        self.store = seed_store(self.stores, DEFAULT_DEMO_STORE_PATH)
        self.scope = self.store.scope
        self.sleeps: list[float] = []

    def add_item(
        self,
        item_id: str = "item-a",
        *,
        index_state=IndexState.PENDING,
        listing_state=ListingState.PUBLISHED,
    ) -> str:
        data = jpeg_bytes()
        image_sha = hashlib.sha256(data).hexdigest()
        self.repository.create_item(
            self.scope,
            item_id=item_id,
            title=item_id,
            category="Bowls",
            price=Decimal("10.00"),
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
            sort_order=0,
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
            byte_size=len(data),
            capture_time=None,
            capture_time_source=CaptureTimeSource.UNKNOWN,
        )
        self.image_store.put(self.scope, image_sha, "display", data)
        return image_sha

    def indexer(self, encoder: FlakyEncoder, **config: Any) -> EmbeddingIndexer:
        settings = IndexerConfig(
            max_attempts=config.get("max_attempts", 3),
            backoff_seconds=config.get("backoff_seconds", 0.5),
            max_backoff_seconds=config.get("max_backoff_seconds", 4.0),
            batch_limit=config.get("batch_limit", 100),
        )
        return EmbeddingIndexer(
            self.repository,
            self.image_store,
            encoder,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            config=settings,
            dimensions=DIMENSIONS,
            sleep=self.sleeps.append,
        )

    def test_retries_with_backoff_then_records_ready(self) -> None:
        image_sha = self.add_item()
        encoder = FlakyEncoder(failures=1)
        report = self.indexer(encoder, max_attempts=3, backoff_seconds=0.25).run(self.scope)
        self.assertEqual(
            (report.candidates, report.attempted, report.ready, report.failed), (1, 1, 1, 0)
        )
        self.assertEqual(encoder.calls, 2)
        self.assertEqual(self.sleeps, [0.25])
        state = self.repository.item_state(self.scope, "item-a")
        assert state is not None
        self.assertIs(state.index_state, IndexState.READY)
        self.assertEqual(state.index_attempts, 0)
        self.assertIsNone(state.index_error)
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        record = self.repository.embedding_for(self.scope, "item-a")
        assert record is not None
        self.assertEqual(record.image_sha256, image_sha)
        self.assertEqual(record.model_revision, MODEL_REVISION)
        self.assertEqual(len(record.vector), DIMENSIONS)

    def test_stops_at_the_attempt_cap_and_records_the_last_error(self) -> None:
        self.add_item()
        encoder = FlakyEncoder(failures=99)
        report = self.indexer(encoder, max_attempts=3, backoff_seconds=0.5).run(self.scope)
        self.assertEqual((report.attempted, report.ready, report.failed), (1, 0, 1))
        self.assertEqual(encoder.calls, 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])
        state = self.repository.item_state(self.scope, "item-a")
        assert state is not None
        self.assertIs(state.index_state, IndexState.FAILED)
        self.assertEqual(state.index_attempts, 3)
        self.assertIn("RuntimeError: model unavailable", state.index_error or "")
        self.assertIs(state.listing_state, ListingState.PUBLISHED)  # Never gated by indexing.

        # A later run does not exceed the cap, and a reset makes it retryable.
        self.sleeps.clear()
        second = self.indexer(encoder, max_attempts=3).run(self.scope)
        self.assertEqual((second.candidates, second.attempted, encoder.calls), (0, 0, 3))
        self.assertEqual(self.repository.reset_index_failures(self.scope), 1)
        third = self.indexer(encoder, max_attempts=3).run(self.scope)
        self.assertEqual((third.attempted, third.failed, encoder.calls), (1, 1, 6))

    def test_stale_input_gets_a_fresh_retry_budget(self) -> None:
        self.add_item()
        image = self.repository.display_image(self.scope, "item-a")
        assert image is not None
        self.repository.put_ready_embedding(
            self.scope,
            item_id="item-a",
            vector=tuple(0.1 for _ in range(DIMENSIONS)),
            model_id=MODEL_ID,
            model_revision="another-revision",
            image_sha256=image.sha256,
        )
        self.repository.mark_index_failed(
            self.scope, item_id="item-a", attempts=3, error="old failure"
        )
        candidates = self.repository.index_candidates(
            self.scope,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            dimensions=DIMENSIONS,
            max_attempts=3,
            limit=10,
        )
        self.assertEqual(
            [(c.item_id, c.state, c.attempts) for c in candidates],
            [("item-a", IndexState.STALE, 3)],
        )
        report = self.indexer(FlakyEncoder(), max_attempts=3).run(self.scope)
        self.assertEqual((report.ready, report.failed), (1, 0))
        state = self.repository.item_state(self.scope, "item-a")
        assert state is not None
        self.assertIs(state.index_state, IndexState.READY)

    def test_indexing_never_changes_listing_state(self) -> None:
        self.add_item("item-published", index_state=IndexState.PENDING)
        self.repository.create_item(
            self.scope,
            item_id="item-draft",
            title="draft",
            category="Bowls",
            price=Decimal("10.00"),
            price_kind="known",
            attributes={"source_title": "draft"},
            provenance=(
                EvidenceRef(
                    ObservationSource.MANUAL,
                    "source-draft",
                    datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
            ),
            catalog_version="test-v1",
            sort_order=1,
            listing_state=ListingState.DRAFT,
        )
        report = self.indexer(FlakyEncoder()).run(self.scope)
        self.assertEqual((report.candidates, report.ready), (1, 1))
        published = self.repository.item_state(self.scope, "item-published")
        draft = self.repository.item_state(self.scope, "item-draft")
        assert published is not None and draft is not None
        self.assertIs(published.listing_state, ListingState.PUBLISHED)
        self.assertIs(published.index_state, IndexState.READY)
        self.assertIs(draft.listing_state, ListingState.DRAFT)
        self.assertIs(draft.index_state, IndexState.PENDING)
