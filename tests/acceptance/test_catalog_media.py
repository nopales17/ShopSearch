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
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from PIL import Image

from apps.web.wsgi import create_pitch_server
from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.derivatives import render_display
from backend.media.image_store import LocalImageStore, media_url
from backend.platform.paths import (
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_INDEX_PATH,
    DEFAULT_DEMO_STORE_PATH,
)
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import EvidenceRef, ListingState, ObservationSource
from tests.unit.test_media import has_exif_segment
from tests.unit.test_pitch import StubEncoder

DATASET_IMAGES = DEFAULT_DEMO_DATASET_PATH.parent / "images"


def synthetic_jpeg() -> bytes:
    image = Image.new("RGB", (24, 24), (200, 40, 90))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class CatalogMediaHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        database_path = root / "shopsearch.sqlite3"
        self.media_root = root / "media"
        development_hosts = root / "development_hosts.json"
        development_hosts.write_text(json.dumps({"127.0.0.1": "pitch-demo"}))
        image_store = LocalImageStore(self.media_root)
        with StoreRepository.open(database_path) as stores:
            with CatalogRepository.open(database_path) as catalog:
                demo = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
                import_pitch_dataset(catalog, image_store, DEFAULT_DEMO_DATASET_PATH, demo)
                document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
                document["store_id"] = "second-store"
                document["domains"] = ["second.example"]
                second_document, domains = load_store_config_in_memory(document)
                second = stores.create_store(second_document, domains)
                self.second_media_url = self.add_item(
                    catalog,
                    image_store,
                    second,
                    "pitch-127475",
                    ListingState.PUBLISHED,
                    (DATASET_IMAGES / "pitch-127475.jpg").read_bytes(),
                )
                self.draft_media_url = self.add_item(
                    catalog,
                    image_store,
                    demo,
                    "pitch-draft",
                    ListingState.DRAFT,
                    synthetic_jpeg(),
                )
                catalog_document = catalog.loaded_catalog(demo)
                demo_item = catalog_document.get("pitch-128096")
                assert demo_item is not None and demo_item.image_uri is not None
                self.demo_media_url = demo_item.image_uri
        self.server = create_pitch_server(
            port=0,
            encoder=StubEncoder(),
            database_path=database_path,
            media_root=self.media_root,
            development_hosts_path=development_hosts,
            storefronts={
                "pitch-demo": DEFAULT_DEMO_INDEX_PATH,
                "second-store": DEFAULT_DEMO_INDEX_PATH,
            },
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def add_item(
        self,
        catalog: CatalogRepository,
        image_store: LocalImageStore,
        store,
        item_id: str,
        listing_state: ListingState,
        source_bytes: bytes,
    ) -> str:
        derivative = render_display(source_bytes, store_timezone=ZoneInfo(store.timezone))
        sha256 = hashlib.sha256(derivative.data).hexdigest()
        image_store.put(store.scope, sha256, "display", derivative.data)
        index_version = json.loads(DEFAULT_DEMO_INDEX_PATH.read_text())["catalog_version"]
        catalog.create_item(
            store.scope,
            item_id=item_id,
            title=f"Item {item_id}",
            category="Bowls",
            price=Decimal("20.00"),
            price_kind="illustrative_demo",
            attributes={
                "source_title": item_id,
                "source_url": "https://example.invalid/object",
                "accession_number": item_id,
                "materials": "glass",
                "photo_captured_at": None,
            },
            provenance=(
                EvidenceRef(
                    ObservationSource.MANUAL,
                    f"source-{item_id}",
                    datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
            ),
            catalog_version=index_version,
            sort_order=100,
            listing_state=listing_state,
        )
        catalog.add_image(
            store.scope,
            item_id=item_id,
            sha256=sha256,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            media_type=derivative.media_type,
            width=derivative.width,
            height=derivative.height,
            byte_size=len(derivative.data),
            capture_time=derivative.capture_time,
            capture_time_source=derivative.capture_time_source,
        )
        return media_url(store.scope, sha256, "display")

    def fetch(self, path: str, host: str = ""):
        headers = {"Host": host} if host else {}
        request = Request(self.url + path, headers=headers)
        opener = build_opener()
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            body = error.read()
            error.close()
            return error.code, error.headers, body

    def assert_no_exif(self, data: bytes) -> None:
        self.assertFalse(has_exif_segment(data))
        self.assertNotIn(b"DateTimeOriginal", data)
        self.assertNotIn(b"GPS", data)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(dict(image.getexif()), {})
            self.assertEqual(dict(image.getexif().get_ifd(0x8825)), {})
            self.assertNotIn("exif", image.info)

    def test_browse_and_detail_are_served_from_the_repository(self) -> None:
        status, _, catalog_body = self.fetch("/catalog", "form-and-field.example")
        self.assertEqual(status, 200)
        self.assertIn(b"/media/pitch-demo/", catalog_body)
        self.assertNotIn(b"pitch-draft", catalog_body)
        status, _, detail = self.fetch("/items/pitch-128096", "form-and-field.example")
        self.assertEqual(status, 200)
        self.assertIn(self.demo_media_url.encode(), detail)
        status, headers, media = self.fetch(self.demo_media_url, "form-and-field.example")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assert_no_exif(media)

    def test_legacy_image_route_serves_the_stored_derivative(self) -> None:
        status, headers, media = self.fetch("/images/pitch-128096.jpg", "form-and-field.example")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assert_no_exif(media)

    def test_draft_items_and_their_media_are_not_served(self) -> None:
        status, _, body = self.fetch("/items/pitch-draft", "form-and-field.example")
        self.assertEqual(status, 404)
        self.assertNotIn(b"pitch-draft", body)
        status, _, _ = self.fetch(self.draft_media_url, "form-and-field.example")
        self.assertEqual(status, 404)

    def test_second_store_serves_its_own_catalog_only(self) -> None:
        status, _, second_catalog = self.fetch("/catalog", "second.example")
        self.assertEqual(status, 200)
        self.assertIn(b"pitch-127475", second_catalog)
        self.assertNotIn(b"pitch-128096", second_catalog)
        status, _, _ = self.fetch("/items/pitch-127475", "second.example")
        self.assertEqual(status, 200)

    def test_cross_store_item_and_media_reads_return_404(self) -> None:
        status, _, body = self.fetch("/items/pitch-128096", "second.example")
        self.assertEqual(status, 404)
        self.assertNotIn(b"pitch-128096", body)
        status, _, _ = self.fetch(self.demo_media_url, "second.example")
        self.assertEqual(status, 404)
        status, _, _ = self.fetch(self.second_media_url, "form-and-field.example")
        self.assertEqual(status, 404)
        status, headers, media = self.fetch(self.second_media_url, "second.example")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assert_no_exif(media)
