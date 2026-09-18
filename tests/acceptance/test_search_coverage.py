from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from PIL import Image

from apps.web.wsgi import create_pitch_server
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform.paths import (
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_INDEX_PATH,
    DEFAULT_DEMO_STORE_PATH,
)
from backend.search.embedding_import import import_pitch_embeddings
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.sqlite_store import TelemetryStores
from contracts.catalog import (
    CaptureTimeSource,
    EvidenceRef,
    ObservationSource,
)
from contracts.store import StoreScope
from tests.unit.test_pitch import StubEncoder

PENDING_ITEM = "aaa-pending"


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (8, 8), (10, 20, 30))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class CoverageHttpTestBase(unittest.TestCase):
    """Storefront over the demo store, optionally with unindexed items."""

    extra_pending = False

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        database_path = root / "shopsearch.sqlite3"
        self.database_path = database_path
        self.log = root / "events.jsonl"
        media_root = root / "media"
        development_hosts = root / "development_hosts.json"
        development_hosts.write_text(json.dumps({"127.0.0.1": "pitch-demo"}))
        self.stale_item_id: str | None = None
        image_store = LocalImageStore(media_root)
        with StoreRepository.open(database_path) as stores:
            with CatalogRepository.open(database_path) as catalog:
                store = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
                import_pitch_dataset(catalog, image_store, DEFAULT_DEMO_DATASET_PATH, store)
                import_pitch_embeddings(
                    catalog,
                    DEFAULT_DEMO_INDEX_PATH,
                    store,
                    model_id=MODEL_ID,
                    model_revision=MODEL_REVISION,
                )
                if self.extra_pending:
                    self.add_pending_item(catalog, image_store, store)
        self.server = create_pitch_server(
            port=0,
            encoder=StubEncoder(),
            database_path=database_path,
            media_root=media_root,
            development_hosts_path=development_hosts,
            storefronts={"pitch-demo"},
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def add_pending_item(self, catalog: CatalogRepository, image_store, store) -> None:
        data = jpeg_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        image_store.put(store.scope, sha256, "display", data)
        catalog.create_item(
            store.scope,
            item_id=PENDING_ITEM,
            title="Pending item",
            category="Bowls",
            price=Decimal("1.00"),
            price_kind="known",
            attributes={
                "source_title": "Pending",
                "source_url": "https://example.invalid/pending",
                "accession_number": "pending",
                "materials": "glass",
                "measurements": None,
            },
            provenance=(
                EvidenceRef(ObservationSource.MANUAL, "source-pending", datetime.now(timezone.utc)),
            ),
            catalog_version=catalog.catalog_version(store.scope),
            sort_order=0,
        )
        catalog.add_image(
            store.scope,
            item_id=PENDING_ITEM,
            sha256=sha256,
            source_sha256=sha256,
            media_type="image/jpeg",
            width=8,
            height=8,
            byte_size=len(data),
            capture_time=None,
            capture_time_source=CaptureTimeSource.UNKNOWN,
        )

    def make_binding_stale(self) -> str:
        """Simulate an embedding stored under another model revision."""

        with StoreRepository.open(self.database_path) as stores:
            with CatalogRepository.open(self.database_path) as catalog:
                store = stores.get_store(StoreScope("pitch-demo"))
                item_id = min(item.item_id for item in catalog.published(store.scope))
                image = catalog.display_image(store.scope, item_id)
                assert image is not None
                catalog.put_ready_embedding(
                    store.scope,
                    item_id=item_id,
                    vector=tuple(0.1 for _ in range(512)),
                    model_id=MODEL_ID,
                    model_revision="another-revision",
                    image_sha256=image.sha256,
                )
        return item_id

    def fetch(self, path: str):
        request = Request(self.url + path)
        try:
            with build_opener().open(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            body = error.read()
            error.close()
            return error.code, body

    def search(self, query: str, category: str = "") -> dict[str, Any]:
        status, body = self.fetch(f"/api/search?q={query}&category={category}")
        self.assertEqual(status, 200)
        return json.loads(body)

    def events(self) -> list[dict[str, Any]]:
        with StoreRepository.open(self.database_path) as stores:
            store = stores.get_store(StoreScope("pitch-demo"))
        with TelemetryStores.open(self.database_path) as telemetry:
            return telemetry.for_store(store).events()


class PartiallyIndexedCoverageTest(CoverageHttpTestBase):
    extra_pending = True

    def test_visual_search_discloses_unindexed_items_with_accurate_counts(self) -> None:
        data = self.search("small+blue+one")
        self.assertEqual(
            data["coverage"],
            {
                "published": 91,
                "ready": 90,
                "excluded_unindexed": 1,
                "visual_text": True,
            },
        )
        self.assertIn("1 of 91", data["coverage_html"])
        self.assertIn('href="/catalog"', data["coverage_html"])
        self.assertNotIn(PENDING_ITEM, data["html"])

        returned = [
            event for event in self.events() if event["event_type"] == "search_results_returned"
        ][-1]
        self.assertEqual(returned["payload"]["published_count"], 91)
        self.assertEqual(returned["payload"]["ready_count"], 90)
        self.assertEqual(returned["payload"]["excluded_unindexed_count"], 1)

    def test_pending_item_stays_browsable_and_price_only_searchable(self) -> None:
        status, catalog_html = self.fetch("/catalog")
        self.assertEqual(status, 200)
        self.assertIn(PENDING_ITEM.encode(), catalog_html)
        status, body = self.fetch(f"/items/{PENDING_ITEM}")
        self.assertEqual(status, 200)
        self.assertIn(b"Pending item", body)

        price_bound = self.search("under+%2450")
        self.assertEqual(price_bound["coverage"]["visual_text"], False)
        self.assertEqual(price_bound["coverage_html"], "")
        self.assertIn(PENDING_ITEM, price_bound["html"])

        browse = self.search("", category="Bowls")
        self.assertIn(PENDING_ITEM, browse["html"])

    def test_zero_result_visual_search_still_reports_coverage(self) -> None:
        data = self.search("blue+under+%241")
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["coverage"]["excluded_unindexed"], 1)
        events = self.events()
        zero = [event for event in events if event["event_type"] == "zero_results"][-1]
        returned = [
            event
            for event in events
            if event["event_type"] == "search_results_returned"
            and event["search_id"] == zero["search_id"]
        ][-1]
        self.assertEqual(returned["payload"]["result_count"], 0)
        self.assertEqual(returned["payload"]["excluded_unindexed_count"], 1)


class FullyIndexedCoverageTest(CoverageHttpTestBase):
    extra_pending = False

    def test_full_coverage_reports_no_notice(self) -> None:
        data = self.search("small+blue+one")
        self.assertEqual(
            data["coverage"],
            {
                "published": 90,
                "ready": 90,
                "excluded_unindexed": 0,
                "visual_text": True,
            },
        )
        self.assertEqual(data["coverage_html"], "")

    def test_zero_result_on_a_fully_indexed_store_reports_zero_excluded(self) -> None:
        data = self.search("blue+under+%241")
        self.assertEqual(data["count"], 0)
        events = self.events()
        zero = [event for event in events if event["event_type"] == "zero_results"][-1]
        returned = [
            event
            for event in events
            if event["event_type"] == "search_results_returned"
            and event["search_id"] == zero["search_id"]
        ][-1]
        self.assertEqual(returned["payload"]["excluded_unindexed_count"], 0)
        self.assertEqual(returned["payload"]["published_count"], 90)


class StaleBindingCoverageTest(CoverageHttpTestBase):
    def test_stale_embedding_is_excluded_and_disclosed(self) -> None:
        self.stale_item_id = self.make_binding_stale()
        data = self.search("blue")
        self.assertEqual(
            data["coverage"],
            {
                "published": 90,
                "ready": 89,
                "excluded_unindexed": 1,
                "visual_text": True,
            },
        )
        self.assertIn("1 of 90", data["coverage_html"])
        self.assertNotIn(self.stale_item_id, data["html"])
