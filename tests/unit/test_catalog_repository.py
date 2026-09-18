from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from backend.catalog.store_repository import (
    CatalogConflictError,
    CatalogError,
    CatalogRepository,
)
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from contracts.catalog import (
    CaptureTimeSource,
    EvidenceRef,
    IndexState,
    ListingState,
    ObservationSource,
)
from contracts.store import Store, StoreScope

SHA_A = "a" * 64
SHA_B = "b" * 64


def _add_store(store_repository: StoreRepository, store_id: str) -> Store:
    document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
    document["store_id"] = store_id
    document["domains"] = []
    store, domains = load_store_config_in_memory(document)
    return store_repository.create_store(store, domains)


class CatalogRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database_path = Path(self.directory.name) / "shopsearch.sqlite3"
        self.stores = StoreRepository.open(database_path)
        self.repository = CatalogRepository.open(database_path)
        self.addCleanup(self.repository.close)
        self.addCleanup(self.stores.close)
        self.store = _add_store(self.stores, "pitch-demo")
        self.scope = self.store.scope

    def create_item(
        self,
        item_id: str,
        scope: StoreScope | None = None,
        *,
        listing_state: ListingState = ListingState.PUBLISHED,
        index_state: IndexState = IndexState.PENDING,
        price: str | None = "10.00",
        price_kind: str | None = None,
        catalog_version: str = "test-v1",
        sort_order: int = 0,
    ) -> bool:
        kinds = {"unknown": "unknown", "known": "known"}
        resolved_kind = price_kind or (kinds["unknown"] if price is None else kinds["known"])
        return self.repository.create_item(
            scope or self.scope,
            item_id=item_id,
            title=f"Item {item_id}",
            category="Bowls",
            price=Decimal(price) if price is not None else None,
            price_kind=resolved_kind,
            attributes={"source_title": item_id},
            provenance=(
                EvidenceRef(
                    ObservationSource.MANUAL,
                    f"source-{item_id}",
                    datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
            ),
            catalog_version=catalog_version,
            sort_order=sort_order,
            listing_state=listing_state,
            index_state=index_state,
        )

    def add_image(self, item_id: str, scope: StoreScope | None = None, sha256: str = SHA_A) -> bool:
        return self.repository.add_image(
            scope or self.scope,
            item_id=item_id,
            sha256=sha256,
            source_sha256=SHA_B,
            media_type="image/jpeg",
            width=100,
            height=100,
            byte_size=10,
            capture_time=None,
            capture_time_source=CaptureTimeSource.UNKNOWN,
        )

    def test_published_excludes_draft_hidden_and_sold(self) -> None:
        for index, state in enumerate(ListingState):
            self.create_item(f"item-{state.value}", listing_state=state, sort_order=index)
        published = [item.item_id for item in self.repository.published(self.scope)]
        self.assertEqual(published, ["item-published"])
        self.assertIsNotNone(self.repository.get_published(self.scope, "item-published"))
        for hidden in ("item-draft", "item-hidden", "item-sold"):
            self.assertIsNone(self.repository.get_published(self.scope, hidden))

    def test_index_state_defaults_to_pending_and_never_gates_publication(self) -> None:
        self.create_item("item-pending", index_state=IndexState.PENDING)
        self.create_item("item-failed", index_state=IndexState.FAILED, sort_order=1)
        state = self.repository.item_state(self.scope, "item-pending")
        assert state is not None
        self.assertIs(state.index_state, IndexState.PENDING)
        self.assertEqual(state.index_attempts, 0)
        self.assertIsNone(state.index_error)
        published = {item.item_id for item in self.repository.published(self.scope)}
        self.assertEqual(published, {"item-pending", "item-failed"})

    def test_composite_foreign_key_rejects_a_cross_store_image(self) -> None:
        second = _add_store(self.stores, "second-store")
        self.create_item("item-a")
        with self.assertRaises(CatalogConflictError):
            self.add_image("item-a", scope=second.scope)
        self.assertEqual(self.repository.image_count(second.scope), 0)

    def test_items_are_store_scoped(self) -> None:
        second = _add_store(self.stores, "second-store")
        self.create_item("item-a")
        self.add_image("item-a")
        self.assertIsNone(self.repository.get_published(second.scope, "item-a"))
        self.assertEqual(self.repository.item_count(second.scope), 0)
        self.assertIsNone(self.repository.display_image(second.scope, "item-a"))

    def test_image_address_lookup_is_store_scoped(self) -> None:
        second = _add_store(self.stores, "second-store")
        self.create_item("item-a")
        self.add_image("item-a")
        self.assertIsNotNone(self.repository.image_by_address(self.scope, SHA_A, "display"))
        self.assertIsNone(self.repository.image_by_address(second.scope, SHA_A, "display"))

    def test_events_append_and_nothing_is_hard_deleted(self) -> None:
        self.create_item("item-a")
        first = self.repository.append_event(
            self.scope,
            item_id="item-a",
            event_type="imported",
            actor="importer",
            after={"listing_state": "published"},
        )
        second = self.repository.append_event(
            self.scope,
            item_id="item-a",
            event_type="corrected",
            actor="curator",
            before={"title": "Item item-a"},
            after={"title": "Corrected"},
        )
        self.assertNotEqual(first, second)
        self.assertEqual(self.repository.event_count(self.scope), 2)
        self.assertIsNotNone(self.repository.item_state(self.scope, "item-a"))
        self.assertFalse(hasattr(self.repository, "delete_item"))

    def test_capture_time_source_and_value_must_agree(self) -> None:
        self.create_item("item-a")
        with self.assertRaises(CatalogError):
            self.repository.add_image(
                self.scope,
                item_id="item-a",
                sha256=SHA_A,
                source_sha256=SHA_B,
                media_type="image/jpeg",
                width=10,
                height=10,
                byte_size=1,
                capture_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
                capture_time_source=CaptureTimeSource.UNKNOWN,
            )
        with self.assertRaises(CatalogError):
            self.repository.add_image(
                self.scope,
                item_id="item-a",
                sha256=SHA_A,
                source_sha256=SHA_B,
                media_type="image/jpeg",
                width=10,
                height=10,
                byte_size=1,
                capture_time=None,
                capture_time_source=CaptureTimeSource.EXIF,
            )

    def test_unknown_price_stays_unknown(self) -> None:
        self.create_item("item-unknown", price=None)
        self.create_item("item-known", price="12.50", sort_order=1)
        published = {item.item_id: item for item in self.repository.published(self.scope)}
        self.assertIsNone(published["item-unknown"].price)
        self.assertEqual(published["item-known"].price, Decimal("12.50"))
        with self.assertRaises(CatalogError):
            self.create_item("item-bad", price=None, price_kind="known")
        with self.assertRaises(CatalogError):
            self.create_item("item-bad-2", price="1.00", price_kind="unknown")

    def test_catalog_version_must_be_single(self) -> None:
        self.create_item("item-a", catalog_version="version-a")
        self.create_item("item-b", catalog_version="version-b", sort_order=1)
        with self.assertRaises(CatalogError):
            self.repository.catalog_version(self.scope)

    def test_import_drift_is_reported_not_silently_rewritten(self) -> None:
        self.create_item("item-a")
        self.assertEqual(self.repository.catalog_version(self.scope), "test-v1")
        with self.assertRaises(CatalogConflictError):
            self.create_item("item-a", price="99.00")
        self.assertFalse(self.create_item("item-a"))
