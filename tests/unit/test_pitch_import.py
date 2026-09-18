from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from apps.web.server import ROOT
from backend.catalog.pitch import load_pitch_catalog
from backend.catalog.pitch_import import ImportResult, import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform.paths import DEFAULT_DEMO_DATASET_PATH, DEFAULT_DEMO_STORE_PATH
from backend.search.multimodal import MultimodalSearchService
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import CaptureTimeSource, EvidenceRef, ListingState, ObservationSource
from contracts.search import SearchQuery
from tests.unit.test_pitch import StubEncoder, pitch_vector_source

EVALUATION_PATH = ROOT / "experiments/search_v0/pitch_evaluation.json"
CONTROL_QUERIES = [
    "under $1",
    "up to $50",
    "small blue one under $50",
    "cheapest one",
    "most expensive blue one",
]


class PitchImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        database_path = root / "shopsearch.sqlite3"
        self.stores = StoreRepository.open(database_path)
        self.repository = CatalogRepository.open(database_path)
        self.image_store = LocalImageStore(root / "media")
        self.addCleanup(self.repository.close)
        self.addCleanup(self.stores.close)
        self.store = seed_store(self.stores, DEFAULT_DEMO_STORE_PATH)
        self.scope = self.store.scope

    def import_dataset(self) -> ImportResult:
        return import_pitch_dataset(
            self.repository, self.image_store, DEFAULT_DEMO_DATASET_PATH, self.store
        )

    def test_import_is_idempotent(self) -> None:
        first = self.import_dataset()
        self.assertEqual(
            (first.items_created, first.images_created, first.blobs_created), (90, 90, 90)
        )
        counts = (
            self.repository.item_count(self.scope),
            self.repository.image_count(self.scope),
            self.repository.event_count(self.scope),
            self.image_store.blob_count(self.scope),
        )
        self.assertEqual(counts, (90, 90, 90, 90))
        image_ids = {
            item.item_id: self.repository.display_image(self.scope, item.item_id)
            for item in self.repository.published(self.scope)
        }
        second = self.import_dataset()
        self.assertEqual(
            (second.items_created, second.images_created, second.blobs_created), (0, 0, 0)
        )
        self.assertEqual(second.items_unchanged, 90)
        self.assertEqual(
            (
                self.repository.item_count(self.scope),
                self.repository.image_count(self.scope),
                self.repository.event_count(self.scope),
                self.image_store.blob_count(self.scope),
            ),
            counts,
        )
        for item_id, before in image_ids.items():
            after = self.repository.display_image(self.scope, item_id)
            assert before is not None and after is not None
            self.assertEqual(before.created_at, after.created_at)
            self.assertEqual(before.sha256, after.sha256)

    def test_every_imported_image_resolves_to_matching_bytes(self) -> None:
        self.import_dataset()
        images_root = DEFAULT_DEMO_DATASET_PATH.parent / "images"
        for item in self.repository.published(self.scope):
            image = self.repository.display_image(self.scope, item.item_id)
            assert image is not None
            served = self.image_store.read(self.scope, image.sha256, image.variant)
            self.assertEqual(hashlib.sha256(served).hexdigest(), image.sha256)
            source = (images_root / f"{item.item_id}.jpg").read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(), image.source_sha256)
            self.assertEqual(image.source_sha256, item.attributes["image_sha256"])
            self.assertNotEqual(image.sha256, image.source_sha256)

    def test_capture_time_is_unknown_and_import_time_is_never_capture_time(self) -> None:
        self.import_dataset()
        for item in self.repository.published(self.scope):
            image = self.repository.display_image(self.scope, item.item_id)
            assert image is not None
            self.assertIsNone(image.capture_time)
            self.assertIs(image.capture_time_source, CaptureTimeSource.UNKNOWN)
            # The dataset carries a review timestamp; it is not a capture time.
            self.assertIsNone(item.attributes["photo_captured_at"])
            self.assertTrue(item.attributes["source_reviewed_at"])
            self.assertNotEqual(item.attributes["source_reviewed_at"], image.created_at.isoformat())

    def test_read_model_serves_published_items_in_dataset_order(self) -> None:
        self.import_dataset()
        self.repository.create_item(
            self.scope,
            item_id="pitch-draft",
            title="Draft item",
            category="Bowls",
            price=Decimal("10.00"),
            price_kind="known",
            attributes={"source_title": "Draft"},
            provenance=(
                EvidenceRef(ObservationSource.MANUAL, "source-draft", datetime.now(timezone.utc)),
            ),
            catalog_version=self.repository.catalog_version(self.scope),
            sort_order=90,
            listing_state=ListingState.DRAFT,
        )
        catalog = self.repository.loaded_catalog(self.store)
        json_catalog = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        self.assertEqual(
            [item.item_id for item in catalog.items],
            [item.item_id for item in json_catalog.items],
        )
        self.assertNotIn("pitch-draft", [item.item_id for item in catalog.items])
        self.assertEqual(catalog.version, json_catalog.version)
        for item in catalog.items:
            self.assertTrue(item.image_uri is not None)
            self.assertTrue(item.image_uri.startswith(f"/media/{self.scope.store_id}/"))
            self.assertNotIn("images/", item.image_uri)
            self.assertNotIn(str(DEFAULT_DEMO_DATASET_PATH.parent), item.image_uri)
            self.assertTrue(item.evidence)
            self.assertEqual(catalog.public_snapshot(item)["currency"], "USD")

    def test_repository_catalog_matches_json_catalog_search_inputs(self) -> None:
        self.import_dataset()
        repository_catalog = self.repository.loaded_catalog(self.store)
        json_catalog = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        repository_source = pitch_vector_source(repository_catalog)
        json_source = pitch_vector_source(json_catalog)
        self.assertEqual(
            [item.item_id for item in repository_catalog.items],
            [item.item_id for item in json_catalog.items],
        )
        for repository_item, json_item in zip(
            repository_catalog.items, json_catalog.items, strict=True
        ):
            self.assertEqual(repository_item.item_id, json_item.item_id)
            self.assertEqual(repository_item.price, json_item.price)
            self.assertEqual(repository_item.category, json_item.category)
            self.assertEqual(
                repository_source.vector_for(repository_item.item_id),
                json_source.vector_for(json_item.item_id),
            )

    def test_frozen_queries_rank_identically_to_the_json_catalog_path(self) -> None:
        self.import_dataset()
        repository_catalog = self.repository.loaded_catalog(self.store)
        json_catalog = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        repository_service = MultimodalSearchService(
            repository_catalog, pitch_vector_source(repository_catalog), StubEncoder()
        )
        json_service = MultimodalSearchService(
            json_catalog, pitch_vector_source(json_catalog), StubEncoder()
        )
        queries = [
            case["query"] for case in json.loads(EVALUATION_PATH.read_text())["queries"]
        ] + CONTROL_QUERIES
        for query in queries:
            with self.subTest(query=query):
                repository_results = repository_service.search(SearchQuery(text=query, limit=5))
                json_results = json_service.search(SearchQuery(text=query, limit=5))
                self.assertEqual(
                    [(r.item_id, r.rank) for r in repository_results.results],
                    [(r.item_id, r.rank) for r in json_results.results],
                )
