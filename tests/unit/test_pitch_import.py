from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from apps.web.server import ROOT
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.pitch import load_pitch_catalog
from backend.catalog.pitch_import import ImportResult, import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform.paths import (
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_INDEX_PATH,
    DEFAULT_DEMO_STORE_PATH,
)
from backend.search.embedding_import import EmbeddingImportResult, import_pitch_embeddings
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

    def import_embeddings(self) -> EmbeddingImportResult:
        return import_pitch_embeddings(
            self.repository,
            DEFAULT_DEMO_INDEX_PATH,
            self.store,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
        )

    def database_vector_source(self) -> DatabaseVectorSource:
        cache = VectorCache(self.repository, model_id=MODEL_ID, model_revision=MODEL_REVISION)
        return DatabaseVectorSource(cache, self.scope)

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
            self.assertNotEqual(image.sha256, item.attributes["image_sha256"])

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

    def test_embedding_import_stores_exact_vectors_bound_to_images(self) -> None:
        self.import_dataset()
        result = self.import_embeddings()
        self.assertEqual((result.embeddings_created, result.embeddings_unchanged), (90, 0))
        self.assertEqual(result.published_without_vectors, 0)
        committed = pitch_vector_source(self.repository.loaded_catalog(self.store)).current()
        for item in self.repository.published(self.scope):
            record = self.repository.embedding_for(self.scope, item.item_id)
            assert record is not None
            image = self.repository.display_image(self.scope, item.item_id)
            assert image is not None
            self.assertEqual(record.dim, 512)
            self.assertEqual(record.model_id, MODEL_ID)
            self.assertEqual(record.model_revision, MODEL_REVISION)
            self.assertEqual(record.image_sha256, image.sha256)
            # Numeric values are written unchanged, so ranking is bit-identical.
            self.assertEqual(record.vector, committed.vector_for(item.item_id))
            state = self.repository.item_state(self.scope, item.item_id)
            assert state is not None
            self.assertIs(state.index_state, IndexState.READY)
            self.assertEqual(state.index_attempts, 0)
            self.assertIsNone(state.index_error)

    def test_embedding_import_is_idempotent(self) -> None:
        self.import_dataset()
        first = self.import_embeddings()
        generation = self.repository.generations(self.scope)
        second = self.import_embeddings()
        self.assertEqual((first.embeddings_created, first.embeddings_unchanged), (90, 0))
        self.assertEqual((second.embeddings_created, second.embeddings_unchanged), (0, 90))
        self.assertEqual(self.repository.generations(self.scope), generation)
        summary = self.repository.index_summary(
            self.scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=512
        )
        self.assertEqual(
            (summary.published, summary.ready, summary.excluded_unindexed), (90, 90, 0)
        )

    def test_repository_vectors_match_the_committed_index_exactly(self) -> None:
        self.import_dataset()
        self.import_embeddings()
        json_catalog = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        committed = pitch_vector_source(json_catalog).current()
        database = self.database_vector_source().current()
        for item in json_catalog.items:
            self.assertEqual(database.vector_for(item.item_id), committed.vector_for(item.item_id))
        self.assertEqual(len(database.vectors), 90)

    def test_frozen_queries_rank_identically_to_the_committed_index_path(self) -> None:
        self.import_dataset()
        self.import_embeddings()
        repository_catalog = self.repository.loaded_catalog(self.store)
        json_catalog = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        database_service = MultimodalSearchService(
            repository_catalog, self.database_vector_source(), StubEncoder()
        )
        committed_service = MultimodalSearchService(
            json_catalog, pitch_vector_source(json_catalog), StubEncoder()
        )
        queries = [
            case["query"] for case in json.loads(EVALUATION_PATH.read_text())["queries"]
        ] + CONTROL_QUERIES
        for query in queries:
            with self.subTest(query=query):
                for limit in (5, 100):
                    database_results = database_service.search(SearchQuery(text=query, limit=limit))
                    committed_results = committed_service.search(
                        SearchQuery(text=query, limit=limit)
                    )
                    self.assertEqual(
                        [(r.item_id, r.rank, r.semantic_score) for r in database_results.results],
                        [(r.item_id, r.rank, r.semantic_score) for r in committed_results.results],
                    )
                    assert database_results.coverage is not None
                    assert committed_results.coverage is not None
                    self.assertEqual(database_results.coverage, committed_results.coverage)
