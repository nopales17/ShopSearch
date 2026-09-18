"""S8 unit tests: amend, hide/unhide, sold/relist and image replacement.

Every real mutation must be one atomic catalog change: exactly one item event and
exactly one catalog-generation bump, with no hard deletes and no change to listing
state from a metadata edit or image replacement.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from backend.catalog.publish import ImageReplacement, MerchantPublisher, PublishError
from backend.catalog.store_repository import (
    CatalogNotFoundError,
    CatalogRepository,
    CatalogStateError,
    DuplicateImageError,
    ImageAttachment,
)
from backend.media.image_store import DISPLAY_VARIANT, LocalImageStore
from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.indexer import EmbeddingIndexer
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import CaptureTimeSource, IndexState, ListingState
from contracts.store import Store
from tests.unit.test_publish import _HookedDatabase, jpeg_bytes

MODEL_ID = "test-model"
MODEL_REVISION = "test-revision"
DIMENSIONS = 8


class StubImageEncoder:
    """Deterministic tiny embedding; transport tests only, never model evidence."""

    def images(self, images: list[object]) -> list[list[float]]:
        return [[0.5] * DIMENSIONS for _ in images]


def live_store_document(store_id: str) -> dict[str, object]:
    document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
    document["store_id"] = store_id
    document["is_demo"] = False
    document["domains"] = []
    return document


class MutationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        with StoreRepository.open(self.database_path) as stores:
            self.store = self.create_store(stores, "live-store")
            self.other = self.create_store(stores, "other-store")
        self.catalog = CatalogRepository.open(self.database_path)
        self.addCleanup(self.catalog.close)
        self.image_store = LocalImageStore(root / "media")
        self.publisher = MerchantPublisher(
            self.store,
            self.catalog,
            self.image_store,
            clock=lambda: datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )

    def create_store(self, stores: StoreRepository, store_id: str) -> Store:
        document, domains = load_store_config_in_memory(live_store_document(store_id))
        return stores.create_store(document, domains)

    # -- helpers -------------------------------------------------------------

    def publisher_for(self, store: Store) -> MerchantPublisher:
        return MerchantPublisher(store, self.catalog, self.image_store)

    def publish(self, store: Store | None = None, *, photo: bytes | None = None, title="Blue bowl"):
        publisher = self.publisher if store is None else self.publisher_for(store)
        return publisher.publish(
            merchant_id="merchant-1",
            photo=photo or jpeg_bytes(),
            declared_content_type="image/jpeg",
            price="24.00",
            title=title,
            category="Bowls",
            attested_capture=False,
        )

    def counts(self, store: Store) -> tuple[int, int, int, int]:
        scope = store.scope
        return (
            self.catalog.item_count(scope),
            self.catalog.image_count(scope),
            self.catalog.event_count(scope),
            self.catalog.generations(scope).catalog,
        )

    def events(self, store: Store, item_id: str) -> list[dict[str, object]]:
        rows = (
            self.catalog._database.connection()
            .execute(
                "SELECT event_type, actor, before_json, after_json FROM item_events "
                "WHERE store_id = ? AND item_id = ? ORDER BY rowid",
                (store.store_id, item_id),
            )
            .fetchall()
        )
        return [
            {
                "event_type": str(row["event_type"]),
                "actor": str(row["actor"]),
                "before": json.loads(row["before_json"]) if row["before_json"] else None,
                "after": json.loads(row["after_json"]),
            }
            for row in rows
        ]

    def test_internal_lookup_sees_hidden_and_sold_images(self) -> None:
        published = self.publish()
        image = self.catalog.current_image(self.store.scope, published.item_id)
        assert image is not None
        for target in (ListingState.HIDDEN, ListingState.SOLD):
            with self.subTest(target=target):
                self.catalog.transition_listing_state(
                    self.store.scope, item_id=published.item_id, target=target, actor="merchant-1"
                )
                self.assertIsNone(self.catalog.display_image(self.store.scope, published.item_id))
                self.assertIsNotNone(
                    self.catalog.current_image(self.store.scope, published.item_id)
                )
                self.assertTrue(
                    self.catalog.image_address_in_use(
                        self.store.scope, image.sha256, DISPLAY_VARIANT
                    )
                )
                self.catalog.transition_listing_state(
                    self.store.scope,
                    item_id=published.item_id,
                    target=ListingState.PUBLISHED,
                    actor="merchant-1",
                )

    def test_duplicate_of_a_hidden_items_bytes_keeps_its_blob(self) -> None:
        photo = jpeg_bytes(size=(40, 30))
        published = self.publish(photo=photo, title="Hidden item")
        image = self.catalog.current_image(self.store.scope, published.item_id)
        assert image is not None
        self.catalog.transition_listing_state(
            self.store.scope, item_id=published.item_id, target=ListingState.HIDDEN, actor="m"
        )
        blobs = self.image_store.blob_count(self.store.scope)
        outcome = self.publish(photo=photo, title="Duplicate attempt")
        self.assertTrue(outcome.duplicate)
        self.assertEqual(self.image_store.blob_count(self.store.scope), blobs)
        kept = self.catalog.current_image(self.store.scope, published.item_id)
        assert kept is not None
        stored = self.image_store.read(self.store.scope, kept.sha256, kept.variant)
        self.assertEqual(hashlib.sha256(stored).hexdigest(), kept.sha256)

    # -- metadata ------------------------------------------------------------

    def test_metadata_edit_records_one_event_and_one_bump(self) -> None:
        published = self.publish()
        before = self.counts(self.store)
        result = self.publisher.edit_item(
            merchant_id="merchant-1",
            item_id=published.item_id,
            title="Green vase",
            category="Vases",
            price="31.50",
        )
        self.assertTrue(result.changed)
        after = self.counts(self.store)
        self.assertEqual((after[2] - before[2], after[3] - before[3]), (1, 1))
        self.assertEqual(len(self.events(self.store, published.item_id)), 2)
        event = self.events(self.store, published.item_id)[-1]
        self.assertEqual(event["event_type"], "metadata_edited")
        self.assertEqual(event["actor"], "merchant-1")
        self.assertEqual(
            event["before"],
            {"title": "Blue bowl", "category": "Bowls", "price": "24.00", "price_kind": "known"},
        )
        self.assertEqual(
            event["after"],
            {"title": "Green vase", "category": "Vases", "price": "31.50", "price_kind": "known"},
        )
        item = self.catalog.get_published(self.store.scope, published.item_id)
        assert item is not None
        self.assertEqual(item.title, "Green vase")
        self.assertEqual(item.price, Decimal("31.50"))
        state = self.catalog.item_state(self.store.scope, published.item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        self.assertIs(state.index_state, IndexState.PENDING)

    def test_unchanged_metadata_is_a_true_no_op(self) -> None:
        published = self.publish()
        before = self.counts(self.store)
        result = self.publisher.edit_item(
            merchant_id="merchant-1",
            item_id=published.item_id,
            title="  Blue   bowl ",  # whitespace-normalizes back to the stored value
            category="Bowls",
            price="24.0",  # numerically identical to the stored 24.00
        )
        self.assertFalse(result.changed)
        self.assertIsNone(result.event_id)
        self.assertEqual(self.counts(self.store), before)
        self.assertEqual(len(self.events(self.store, published.item_id)), 1)

    def test_price_can_move_between_known_and_unknown(self) -> None:
        published = self.publish()
        self.publisher.edit_item(
            merchant_id="m",
            item_id=published.item_id,
            title="Blue bowl",
            category="Bowls",
            price="",
        )
        item = self.catalog.get_published(self.store.scope, published.item_id)
        assert item is not None
        self.assertIsNone(item.price)
        self.publisher.edit_item(
            merchant_id="m",
            item_id=published.item_id,
            title="Blue bowl",
            category="Bowls",
            price="19.99",
        )
        restored = self.catalog.get_published(self.store.scope, published.item_id)
        assert restored is not None
        self.assertEqual(restored.price, Decimal("19.99"))

    def test_editing_a_foreign_or_unknown_item_changes_nothing(self) -> None:
        published = self.publish()
        before = self.counts(self.other)
        with self.assertRaises(CatalogNotFoundError):
            self.publisher_for(self.other).edit_item(
                merchant_id="other-merchant",
                item_id=published.item_id,
                title="Stolen",
                category="",
                price="1.00",
            )
        with self.assertRaises(CatalogNotFoundError):
            self.publisher.edit_item(
                merchant_id="m", item_id="missing-item", title="x", category="", price=""
            )
        self.assertEqual(self.counts(self.other), before)
        item = self.catalog.get_published(self.store.scope, published.item_id)
        assert item is not None
        self.assertEqual(item.title, "Blue bowl")

    def test_demo_stores_cannot_be_mutated(self) -> None:
        with StoreRepository.open(self.database_path) as stores:
            demo = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
        publisher = self.publisher_for(demo)
        calls = (
            lambda: publisher.edit_item(
                merchant_id="m", item_id="pitch-128096", title="x", category="", price=""
            ),
            lambda: publisher.transition_listing(
                merchant_id="m", item_id="pitch-128096", action="hide"
            ),
            lambda: publisher.replace_image(
                merchant_id="m",
                item_id="pitch-128096",
                photo=jpeg_bytes(),
                declared_content_type="image/jpeg",
                attested_capture=False,
            ),
        )
        for call in calls:
            with self.assertRaises(PublishError) as caught:
                call()
            self.assertIn("illustrative demo", str(caught.exception))

    # -- listing state -------------------------------------------------------

    def test_listing_transitions_record_one_event_each(self) -> None:
        published = self.publish()
        cases = [
            ("hide", "hidden", ListingState.PUBLISHED, ListingState.HIDDEN),
            ("unhide", "unhidden", ListingState.HIDDEN, ListingState.PUBLISHED),
            ("sold", "sold", ListingState.PUBLISHED, ListingState.SOLD),
            ("relist", "relisted", ListingState.SOLD, ListingState.PUBLISHED),
        ]
        event_count = 1
        generation = self.counts(self.store)[3]
        for action, event_type, expected_from, expected_to in cases:
            with self.subTest(action=action):
                result = self.publisher.transition_listing(
                    merchant_id="merchant-1", item_id=published.item_id, action=action
                )
                self.assertTrue(result.changed)
                event_count += 1
                generation += 1
                event = self.events(self.store, published.item_id)[-1]
                self.assertEqual(event["event_type"], event_type)
                self.assertEqual(event["before"], {"listing_state": expected_from.value})
                self.assertEqual(event["after"]["listing_state"], expected_to.value)
                self.assertEqual(event["actor"], "merchant-1")
                state = self.catalog.item_state(self.store.scope, published.item_id)
                assert state is not None
                self.assertIs(state.listing_state, expected_to)
        counts = self.counts(self.store)
        self.assertEqual((counts[2], counts[3]), (event_count, generation))
        # Listing state never destroys media or the item's identity.
        self.assertEqual(counts[0], 1)
        self.assertIsNotNone(self.catalog.current_image(self.store.scope, published.item_id))

    def test_repeated_same_state_transition_is_a_no_op(self) -> None:
        published = self.publish()
        self.publisher.transition_listing(merchant_id="m", item_id=published.item_id, action="hide")
        before = self.counts(self.store)
        again = self.publisher.transition_listing(
            merchant_id="m", item_id=published.item_id, action="hide"
        )
        self.assertFalse(again.changed)
        self.assertEqual(self.counts(self.store), before)

    def test_invalid_transitions_are_rejected(self) -> None:
        published = self.publish()
        with self.assertRaises(CatalogStateError):
            self.catalog.transition_listing_state(
                self.store.scope,
                item_id=published.item_id,
                target=ListingState.DRAFT,
                actor="m",
            )
        self.catalog.transition_listing_state(
            self.store.scope, item_id=published.item_id, target=ListingState.HIDDEN, actor="m"
        )
        before = self.counts(self.store)
        with self.assertRaises(CatalogStateError):
            self.catalog.transition_listing_state(
                self.store.scope,
                item_id=published.item_id,
                target=ListingState.SOLD,
                actor="m",
            )
        with self.assertRaises(PublishError):
            self.publisher.transition_listing(
                merchant_id="m", item_id=published.item_id, action="publish"
            )
        self.assertEqual(self.counts(self.store), before)

    def test_listing_a_foreign_item_changes_nothing(self) -> None:
        published = self.publish()
        before = self.counts(self.other)
        with self.assertRaises(CatalogNotFoundError):
            self.publisher_for(self.other).transition_listing(
                merchant_id="other", item_id=published.item_id, action="hide"
            )
        self.assertEqual(self.counts(self.other), before)
        state = self.catalog.item_state(self.store.scope, published.item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)

    # -- image replacement ---------------------------------------------------

    def test_replacement_keeps_identity_and_clears_the_old_vector(self) -> None:
        published = self.publish()
        image = self.catalog.current_image(self.store.scope, published.item_id)
        assert image is not None
        self.catalog.put_ready_embedding(
            self.store.scope,
            item_id=published.item_id,
            vector=[0.1] * DIMENSIONS,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            image_sha256=image.sha256,
        )
        ready = self.catalog.ready_vectors(
            self.store.scope,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            dimensions=DIMENSIONS,
        )
        self.assertIn(published.item_id, ready)
        before = self.counts(self.store)
        replacement = self.publisher.replace_image(
            merchant_id="merchant-1",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(64, 64)),
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        self.assertTrue(replacement.changed)
        after = self.counts(self.store)
        self.assertEqual((after[2] - before[2], after[3] - before[3]), (1, 1))
        events = self.events(self.store, published.item_id)
        self.assertEqual(events[-1]["event_type"], "image_replaced")
        self.assertEqual(events[-1]["actor"], "merchant-1")
        self.assertEqual(events[-1]["before"]["image_sha256"], image.sha256)
        new_image = self.catalog.current_image(self.store.scope, published.item_id)
        assert new_image is not None
        self.assertEqual(events[-1]["after"]["image_sha256"], new_image.sha256)
        # The old embedding row is retained but can never rank again.
        binding = self.catalog.embedding_for(self.store.scope, published.item_id)
        assert binding is not None
        self.assertEqual(binding.image_sha256, image.sha256)
        self.assertNotIn(
            published.item_id,
            self.catalog.ready_vectors(
                self.store.scope,
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
                dimensions=DIMENSIONS,
            ),
        )
        summary = self.catalog.index_summary(
            self.store.scope,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            dimensions=DIMENSIONS,
        )
        self.assertEqual((summary.published, summary.stale, summary.ready), (1, 1, 0))
        # The item stays published and browsable throughout.
        state = self.catalog.item_state(self.store.scope, published.item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        self.assertIsNotNone(self.catalog.get_published(self.store.scope, published.item_id))

    def test_one_indexer_run_rebinds_the_replacement(self) -> None:
        published = self.publish()
        first = self.catalog.current_image(self.store.scope, published.item_id)
        assert first is not None
        self.catalog.put_ready_embedding(
            self.store.scope,
            item_id=published.item_id,
            vector=[0.1] * DIMENSIONS,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            image_sha256=first.sha256,
        )
        self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(52, 52)),
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        indexer = EmbeddingIndexer(
            self.catalog,
            self.image_store,
            StubImageEncoder(),
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            dimensions=DIMENSIONS,
        )
        report = indexer.run(self.store.scope)
        self.assertEqual((report.ready, report.failed), (1, 0))
        binding = self.catalog.embedding_for(self.store.scope, published.item_id)
        assert binding is not None
        current = self.catalog.current_image(self.store.scope, published.item_id)
        assert current is not None
        self.assertEqual(binding.image_sha256, current.sha256)

    def test_resubmitting_the_current_bytes_is_a_no_op(self) -> None:
        photo = jpeg_bytes(size=(44, 44))
        published = self.publish(photo=photo)
        before = self.counts(self.store)
        blobs = self.image_store.blob_count(self.store.scope)
        outcome = self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=photo,
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        self.assertFalse(outcome.changed)
        self.assertEqual(self.counts(self.store), before)
        self.assertEqual(self.image_store.blob_count(self.store.scope), blobs)
        self.assertEqual(len(self.events(self.store, published.item_id)), 1)

    def test_replacement_with_another_items_bytes_is_rejected(self) -> None:
        photo = jpeg_bytes(size=(36, 36))
        first = self.publish(photo=photo, title="First")
        second = self.publish(photo=jpeg_bytes(size=(38, 38)), title="Second")
        second_image = self.catalog.current_image(self.store.scope, second.item_id)
        assert second_image is not None
        before = self.counts(self.store)
        blobs = self.image_store.blob_count(self.store.scope)
        # The repository names the owner; the merchant-facing layer reports it generically.
        with self.assertRaises(DuplicateImageError):
            self.catalog.replace_item_image(
                self.store.scope,
                item_id=second.item_id,
                image=ImageAttachment(
                    sha256=hashlib.sha256(photo).hexdigest(),
                    source_sha256=hashlib.sha256(photo).hexdigest(),
                    media_type="image/jpeg",
                    width=8,
                    height=8,
                    byte_size=len(photo),
                    capture_time=None,
                    capture_time_source=CaptureTimeSource.UNKNOWN,
                ),
                actor="m",
            )
        with self.assertRaises(PublishError):
            self.publisher.replace_image(
                merchant_id="m",
                item_id=second.item_id,
                photo=photo,
                declared_content_type="image/jpeg",
                attested_capture=False,
            )
        self.assertEqual(self.counts(self.store), before)
        self.assertEqual(self.image_store.blob_count(self.store.scope), blobs)
        self.assertEqual(len(self.events(self.store, second.item_id)), 1)
        unchanged = self.catalog.current_image(self.store.scope, second.item_id)
        assert unchanged is not None
        self.assertEqual(unchanged.sha256, second_image.sha256)
        self.assertIsNotNone(self.catalog.current_image(self.store.scope, first.item_id))

    def test_failed_replacement_preserves_state_and_orphans_nothing(self) -> None:
        published = self.publish()
        before = self.counts(self.store)
        blobs = self.image_store.blob_count(self.store.scope)
        with mock.patch.object(
            CatalogRepository, "replace_item_image", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self.publisher.replace_image(
                    merchant_id="m",
                    item_id=published.item_id,
                    photo=jpeg_bytes(size=(60, 60)),
                    declared_content_type="image/jpeg",
                    attested_capture=False,
                )
        self.assertEqual(self.counts(self.store), before)
        self.assertEqual(self.image_store.blob_count(self.store.scope), blobs)
        self.assertEqual(list(Path(self.directory.name, "media").rglob("*.tmp")), [])

    def test_replacing_a_hidden_item_does_not_publish_it(self) -> None:
        published = self.publish()
        self.publisher.transition_listing(merchant_id="m", item_id=published.item_id, action="hide")
        outcome = self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(66, 66)),
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        self.assertTrue(outcome.changed)
        state = self.catalog.item_state(self.store.scope, published.item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.HIDDEN)
        self.assertIsNone(self.catalog.display_image(self.store.scope, published.item_id))
        self.assertEqual(self.counts(self.store)[0], 1)

    def test_replacing_a_foreign_item_changes_nothing(self) -> None:
        published = self.publish()
        before = self.counts(self.other)
        with self.assertRaises(CatalogNotFoundError):
            self.publisher_for(self.other).replace_image(
                merchant_id="other",
                item_id=published.item_id,
                photo=jpeg_bytes(size=(50, 50)),
                declared_content_type="image/jpeg",
                attested_capture=False,
            )
        self.assertEqual(self.counts(self.other), before)
        self.assertIsNotNone(self.catalog.current_image(self.store.scope, published.item_id))
        self.assertEqual(self.image_store.blob_count(self.other.scope), 0)

    def test_replacement_keeps_capture_provenance_rules(self) -> None:
        published = self.publish()
        exif = self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(72, 72), exif_datetime="2025:03:04 05:06:07"),
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        self.assertIs(exif.capture_time_source, CaptureTimeSource.EXIF)
        assert exif.capture_time is not None
        self.assertEqual(exif.capture_time.year, 2025)
        image = self.catalog.current_image(self.store.scope, published.item_id)
        assert image is not None
        self.assertIs(image.capture_time_source, CaptureTimeSource.EXIF)
        attested = self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(74, 74)),
            declared_content_type="image/jpeg",
            attested_capture=True,
        )
        self.assertIs(attested.capture_time_source, CaptureTimeSource.MERCHANT_ATTESTATION)
        unknown = self.publisher.replace_image(
            merchant_id="m",
            item_id=published.item_id,
            photo=jpeg_bytes(size=(76, 76)),
            declared_content_type="image/jpeg",
            attested_capture=False,
        )
        self.assertIs(unknown.capture_time_source, CaptureTimeSource.UNKNOWN)
        self.assertIsNone(unknown.capture_time)


class ReplacementConcurrencyTest(unittest.TestCase):
    """Simultaneous replacements with the same bytes fail closed on the schema rule."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.image_store = LocalImageStore(root / "media")
        with StoreRepository.open(self.database_path) as stores:
            document, domains = load_store_config_in_memory(live_store_document("live-store"))
            self.store = stores.create_store(document, domains)
        with CatalogRepository.open(self.database_path) as catalog:
            publisher = MerchantPublisher(self.store, catalog, self.image_store)
            self.first_id = publisher.publish(
                merchant_id="merchant-1",
                photo=jpeg_bytes(size=(100, 80)),
                declared_content_type="image/jpeg",
                price="10.00",
                title="First",
                category="Bowls",
                attested_capture=False,
            ).item_id
            self.second_id = publisher.publish(
                merchant_id="merchant-1",
                photo=jpeg_bytes(size=(102, 82)),
                declared_content_type="image/jpeg",
                price="11.00",
                title="Second",
                category="Bowls",
                attested_capture=False,
            ).item_id

    def publisher(self, hook) -> MerchantPublisher:
        database = _HookedDatabase(platform_db.Database.open(self.database_path), hook)
        self.addCleanup(database.close)
        return MerchantPublisher(self.store, CatalogRepository(database), self.image_store)

    def test_simultaneous_identical_replacements_apply_once(self) -> None:
        photo = jpeg_bytes(size=(120, 90))
        winner_updated = threading.Event()
        loser_lookup_done = threading.Event()

        def hook_winner(phase: str, statement: str) -> None:
            # Hold the winning write lock until the loser has done its own lookup.
            if phase == "after" and statement.startswith("UPDATE images SET sha256"):
                winner_updated.set()
                if not loser_lookup_done.wait(10):
                    raise AssertionError("the losing replacement never reached its lookup")

        def hook_loser(phase: str, statement: str) -> None:
            if phase == "after" and statement.startswith("SELECT item_id FROM images"):
                loser_lookup_done.set()

        winner = self.publisher(hook_winner)
        loser = self.publisher(hook_loser)
        outcomes: dict[str, object] = {}

        def run(name: str, publisher: MerchantPublisher, item_id: str) -> None:
            try:
                outcomes[name] = publisher.replace_image(
                    merchant_id="merchant-1",
                    item_id=item_id,
                    photo=photo,
                    declared_content_type="image/jpeg",
                    attested_capture=False,
                )
            except Exception as error:  # surfaced through the assertions below
                outcomes[name] = error

        first_thread = threading.Thread(target=run, args=("winner", winner, self.first_id))
        second_thread = threading.Thread(target=run, args=("loser", loser, self.second_id))
        first_thread.start()
        self.assertTrue(winner_updated.wait(10), "the winning replacement never started")
        second_thread.start()
        first_thread.join(30)
        second_thread.join(30)
        self.assertFalse(first_thread.is_alive() or second_thread.is_alive())

        applied = [
            outcome
            for outcome in outcomes.values()
            if isinstance(outcome, ImageReplacement) and outcome.changed
        ]
        rejected = [outcome for outcome in outcomes.values() if isinstance(outcome, PublishError)]
        self.assertEqual(len(applied), 1, outcomes)
        self.assertEqual(len(rejected), 1, outcomes)

        with CatalogRepository.open(self.database_path) as catalog:
            scope = self.store.scope
            self.assertEqual(catalog.item_count(scope), 2)
            self.assertEqual(catalog.image_count(scope), 2)
            self.assertEqual(catalog.event_count(scope), 3, "two publishes and one replacement")
            self.assertEqual(catalog.generations(scope).catalog, 3)
            first = catalog.current_image(scope, self.first_id)
            second = catalog.current_image(scope, self.second_id)
        assert first is not None and second is not None
        sources = {first.source_sha256, second.source_sha256}
        self.assertIn(hashlib.sha256(photo).hexdigest(), sources)
        for image in (first, second):
            self.assertTrue(self.image_store.exists(scope, image.sha256, DISPLAY_VARIANT))


if __name__ == "__main__":
    unittest.main()
