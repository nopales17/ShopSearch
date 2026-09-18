from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from apps.web.server import ROOT
from backend.media.derivatives import read_capture_time, render_display
from backend.media.image_store import LocalImageStore, MediaError, media_url
from contracts.catalog import CaptureTimeSource
from contracts.store import StoreScope

PITCH_IMAGE = ROOT / "data/pitch/images/pitch-128096.jpg"
STORE_TIMEZONE = ZoneInfo("America/Los_Angeles")


def exif_jpeg(*, gps: bool = True, offset: str | None = "+02:00") -> bytes:
    image = Image.new("RGB", (12, 8), (10, 20, 30))
    exif = image.getexif()
    values: dict[int, str] = {36867: "2024:05:06 07:08:09"}
    if offset is not None:
        values[36881] = offset
    exif[0x8769] = values
    if gps:
        exif[0x8825] = {1: "N"}
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def has_exif_segment(data: bytes) -> bool:
    """Walk JPEG markers and report an APP1/Exif segment."""

    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            return False
        marker = data[index + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xDA:
            return False
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker == 0xE1 and data[index + 4 : index + 10] == b"Exif\x00\x00":
            return True
        index += 2 + length
    return False


class ImageStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = LocalImageStore(Path(self.directory.name) / "media")
        self.scope = StoreScope("pitch-demo")
        self.data = b"\x01\x02\x03\x04"
        self.sha256 = hashlib.sha256(self.data).hexdigest()

    def test_content_addressed_roundtrip_and_dedupe(self) -> None:
        self.assertTrue(self.store.put(self.scope, self.sha256, "display", self.data))
        self.assertFalse(self.store.put(self.scope, self.sha256, "display", self.data))
        self.assertEqual(self.store.read(self.scope, self.sha256, "display"), self.data)
        self.assertTrue(self.store.exists(self.scope, self.sha256, "display"))
        self.assertEqual(self.store.blob_count(self.scope), 1)

    def test_images_are_store_scoped(self) -> None:
        self.store.put(self.scope, self.sha256, "display", self.data)
        other = StoreScope("second-store")
        self.assertFalse(self.store.exists(other, self.sha256, "display"))
        self.assertEqual(self.store.blob_count(other), 0)
        with self.assertRaises(FileNotFoundError):
            self.store.read(other, self.sha256, "display")

    def test_rejects_unsafe_addresses_and_mismatched_bytes(self) -> None:
        with self.assertRaises(MediaError):
            self.store.put(self.scope, "not-a-hash", "display", self.data)
        with self.assertRaises(MediaError):
            self.store.put(self.scope, self.sha256, "../escape", self.data)
        with self.assertRaises(MediaError):
            media_url(self.scope, self.sha256, "Display")
        with self.assertRaises(MediaError):
            self.store.put(self.scope, self.sha256, "display", b"")
        self.store.put(self.scope, self.sha256, "display", self.data)
        with self.assertRaises(MediaError):
            self.store.put(self.scope, self.sha256, "display", b"different")

    def test_media_url_is_store_scoped_and_content_addressed(self) -> None:
        url = media_url(self.scope, self.sha256, "display")
        self.assertEqual(url, f"/media/pitch-demo/{self.sha256}/display")
        self.assertNotEqual(
            url,
            media_url(StoreScope("second-store"), self.sha256, "display"),
        )
        # Callers receive a URL, never a filesystem location.
        self.assertNotIn(str(Path(self.directory.name)), url)


class DerivativeTest(unittest.TestCase):
    def test_public_derivative_strips_exif_gps_and_datetime_original(self) -> None:
        source = PITCH_IMAGE.read_bytes()
        with Image.open(BytesIO(source)) as original:
            self.assertTrue(dict(original.getexif()))  # The source review artifact has EXIF.
        derivative = render_display(source, store_timezone=STORE_TIMEZONE)
        self.assertFalse(has_exif_segment(derivative.data))
        self.assertNotIn(b"DateTimeOriginal", derivative.data)
        self.assertNotIn(b"GPS", derivative.data)
        with Image.open(BytesIO(derivative.data)) as rendered:
            self.assertEqual(dict(rendered.getexif()), {})
            self.assertEqual(dict(rendered.getexif().get_ifd(0x8825)), {})
            self.assertNotIn("exif", rendered.info)
            self.assertEqual(rendered.format, "JPEG")

    def test_missing_capture_metadata_stays_unknown(self) -> None:
        derivative = render_display(PITCH_IMAGE.read_bytes(), store_timezone=STORE_TIMEZONE)
        self.assertIsNone(derivative.capture_time)
        self.assertIs(derivative.capture_time_source, CaptureTimeSource.UNKNOWN)

    def test_exif_capture_time_is_read_with_its_offset_and_stripped_afterwards(self) -> None:
        source = exif_jpeg()
        with Image.open(BytesIO(source)) as image:
            capture_time = read_capture_time(image, STORE_TIMEZONE)
        self.assertEqual(
            capture_time,
            datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone(timedelta(hours=2))),
        )
        derivative = render_display(source, store_timezone=STORE_TIMEZONE)
        self.assertEqual(derivative.capture_time, capture_time)
        self.assertIs(derivative.capture_time_source, CaptureTimeSource.EXIF)
        self.assertFalse(has_exif_segment(derivative.data))
        with Image.open(BytesIO(derivative.data)) as rendered:
            self.assertEqual(dict(rendered.getexif()), {})
            self.assertEqual(dict(rendered.getexif().get_ifd(0x8825)), {})

    def test_capture_time_without_offset_uses_store_timezone(self) -> None:
        with Image.open(BytesIO(exif_jpeg(offset=None))) as image:
            capture_time = read_capture_time(image, STORE_TIMEZONE)
        self.assertIsNotNone(capture_time)
        assert capture_time is not None
        self.assertEqual(capture_time.utcoffset(), timedelta(hours=-7))  # PDT on 2024-05-06.

    def test_datetime_tag_alone_is_not_a_capture_time(self) -> None:
        image = Image.new("RGB", (8, 8), (0, 0, 0))
        exif = image.getexif()
        exif[306] = "2024:05:06 07:08:09"  # DateTime, not DateTimeOriginal.
        buffer = BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        with Image.open(BytesIO(buffer.getvalue())) as written:
            self.assertEqual(dict(written.getexif()), {306: "2024:05:06 07:08:09"})
            self.assertIsNone(read_capture_time(written, STORE_TIMEZONE))

    def test_derivative_rendering_is_deterministic(self) -> None:
        source = PITCH_IMAGE.read_bytes()
        first = render_display(source, store_timezone=STORE_TIMEZONE)
        second = render_display(source, store_timezone=STORE_TIMEZONE)
        self.assertEqual(first.data, second.data)
        self.assertEqual((first.width, first.height), (second.width, second.height))
