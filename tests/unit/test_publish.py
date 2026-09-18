from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from PIL import Image

from backend.catalog.publish import MerchantPublisher, PublishError, parse_price_input
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.media.uploads import MAX_UPLOAD_BYTES, UploadError, validate_upload
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from contracts.catalog import CaptureTimeSource

TIMEZONE = ZoneInfo("America/Los_Angeles")


def jpeg_bytes(*, size=(32, 24), exif_datetime: str | None = None) -> bytes:
    image = Image.new("RGB", size, (30, 60, 120))
    buffer = BytesIO()
    if exif_datetime:
        exif = image.getexif()
        exif[0x8769] = {36867: exif_datetime}
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), (200, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


class PriceInputTest(unittest.TestCase):
    def test_blank_prices_stay_unknown(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIsNone(parse_price_input(value))

    def test_prices_are_decimal_with_at_most_two_places(self) -> None:
        self.assertEqual(parse_price_input("24"), Decimal("24.00"))
        self.assertEqual(parse_price_input(" 24.5 "), Decimal("24.50"))
        self.assertEqual(parse_price_input("0"), Decimal("0.00"))
        for invalid in ("abc", "-1", "1.234", "nan", "Infinity", "12,50"):
            with self.subTest(invalid=invalid), self.assertRaises(PublishError):
                parse_price_input(invalid)


class UploadValidationTest(unittest.TestCase):
    def test_accepts_supported_formats_and_ignores_octet_stream(self) -> None:
        upload = validate_upload(
            jpeg_bytes(), declared_content_type="image/jpeg", store_timezone=TIMEZONE
        )
        self.assertEqual(upload.detected_format, "JPEG")
        self.assertEqual(upload.derivative.media_type, "image/jpeg")
        self.assertEqual(upload.declared_content_type, "image/jpeg")
        ignored = validate_upload(
            png_bytes(), declared_content_type="application/octet-stream", store_timezone=TIMEZONE
        )
        self.assertEqual(ignored.detected_format, "PNG")
        self.assertEqual(ignored.declared_content_type, "application/octet-stream")

    def test_rejects_empty_non_image_mismatched_and_unsupported_payloads(self) -> None:
        cases = [
            (b"", "image/jpeg"),
            (b"not an image at all", "image/jpeg"),
            (png_bytes(), "image/jpeg"),
        ]
        for data, declared in cases:
            with self.subTest(declared=declared, size=len(data)):
                with self.assertRaises(UploadError):
                    validate_upload(data, declared_content_type=declared, store_timezone=TIMEZONE)
        gif = BytesIO()
        Image.new("RGB", (8, 8), (0, 0, 0)).save(gif, format="GIF")
        with self.assertRaises(UploadError):
            validate_upload(
                gif.getvalue(), declared_content_type="image/gif", store_timezone=TIMEZONE
            )

    def test_rejects_bytes_above_the_upload_cap(self) -> None:
        with self.assertRaises(UploadError):
            validate_upload(
                b"x" * (MAX_UPLOAD_BYTES + 1),
                declared_content_type="image/jpeg",
                store_timezone=TIMEZONE,
            )


class PublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
        document["store_id"] = "live-store"
        document["is_demo"] = False
        document["domains"] = []
        live_document, domains = load_store_config_in_memory(document)
        with StoreRepository.open(self.database_path) as stores:
            self.store = stores.create_store(live_document, domains)
        self.catalog = CatalogRepository.open(self.database_path)
        self.addCleanup(self.catalog.close)
        self.image_store = LocalImageStore(root / "media")
        self.publisher = MerchantPublisher(
            self.store,
            self.catalog,
            self.image_store,
            clock=lambda: datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )

    def publish(self, **overrides):
        options = {
            "merchant_id": "merchant-1",
            "photo": jpeg_bytes(),
            "declared_content_type": "image/jpeg",
            "price": "24.00",
            "title": "Blue bowl",
            "category": "Bowls",
            "attested_capture": False,
        }
        options.update(overrides)
        return self.publisher.publish(**options)

    def test_publication_bumps_once_and_records_capture_provenance(self) -> None:
        generation = self.catalog.generations(self.store.scope).catalog
        published = self.publish(attested_capture=True)
        self.assertFalse(published.duplicate)
        self.assertIs(published.capture_time_source, CaptureTimeSource.MERCHANT_ATTESTATION)
        self.assertEqual(self.catalog.item_count(self.store.scope), 1)
        self.assertEqual(self.catalog.image_count(self.store.scope), 1)
        self.assertEqual(self.catalog.event_count(self.store.scope), 1)
        self.assertEqual(self.catalog.generations(self.store.scope).catalog, generation + 1)
        self.assertIsNone(self.catalog.embedding_for(self.store.scope, published.item_id))

    def test_exif_capture_wins_and_unknown_stays_unknown(self) -> None:
        exif = self.publish(photo=jpeg_bytes(exif_datetime="2024:05:06 07:08:09"))
        self.assertIs(exif.capture_time_source, CaptureTimeSource.EXIF)
        self.assertEqual(exif.capture_time, datetime(2024, 5, 6, 7, 8, 9, tzinfo=TIMEZONE))
        unknown = self.publish(photo=jpeg_bytes(size=(20, 20)))
        self.assertIs(unknown.capture_time_source, CaptureTimeSource.UNKNOWN)
        self.assertIsNone(unknown.capture_time)

    def test_duplicate_source_bytes_reuse_the_blob_without_a_second_item(self) -> None:
        first = self.publish()
        blob_count = self.image_store.blob_count(self.store.scope)
        generation = self.catalog.generations(self.store.scope).catalog
        second = self.publish(price="99.00", title="Something else")
        self.assertTrue(second.duplicate)
        self.assertEqual(second.item_id, first.item_id)
        self.assertEqual(self.catalog.item_count(self.store.scope), 1)
        self.assertEqual(self.catalog.image_count(self.store.scope), 1)
        self.assertEqual(self.catalog.event_count(self.store.scope), 1)
        self.assertEqual(self.catalog.generations(self.store.scope).catalog, generation)
        self.assertEqual(self.image_store.blob_count(self.store.scope), blob_count)
        item = self.catalog.get_published(self.store.scope, first.item_id)
        assert item is not None
        self.assertEqual(item.title, "Blue bowl")
        self.assertEqual(item.price, Decimal("24.00"))

    def test_a_failed_publication_leaves_no_orphan_blob(self) -> None:
        with mock.patch.object(
            CatalogRepository,
            "publish_item_with_image",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertEqual(self.image_store.blob_count(self.store.scope), 0)
        self.assertEqual(self.catalog.item_count(self.store.scope), 0)
        self.assertEqual(list(Path(self.directory.name, "media").rglob("*.tmp")), [])

    def test_demo_stores_are_not_publish_targets(self) -> None:
        with StoreRepository.open(self.database_path) as stores:
            from backend.stores.seed import seed_store

            demo = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
        publisher = MerchantPublisher(demo, self.catalog, self.image_store)
        with self.assertRaises(PublishError):
            publisher.publish(
                merchant_id="merchant-1",
                photo=jpeg_bytes(),
                declared_content_type="image/jpeg",
                price="1.00",
                title="",
                category="",
                attested_capture=False,
            )
