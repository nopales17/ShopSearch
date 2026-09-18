"""Normalized public image derivatives with capture-time provenance.

The public derivative is re-encoded from pixel data only, so it carries no EXIF
(including GPS and DateTimeOriginal). Capture time is read from image metadata
only; when metadata carries none it stays unknown. Import time is never a capture
time (ADR-0005 §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps

from contracts.catalog import CaptureTimeSource

JPEG_MEDIA_TYPE = "image/jpeg"
MAX_DISPLAY_DIMENSION = 1600
DISPLAY_QUALITY = 85

_EXIF_IFD = 0x8769
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_OFFSET_TIME_ORIGINAL = 36881


class DerivativeError(ValueError):
    """Raised when source bytes cannot be decoded into a public derivative."""


@dataclass(frozen=True)
class Derivative:
    data: bytes
    media_type: str
    width: int
    height: int
    capture_time: datetime | None
    capture_time_source: CaptureTimeSource


def read_capture_time(image: Image.Image, store_timezone: ZoneInfo) -> datetime | None:
    """Return DateTimeOriginal with an explicit offset, or None when absent.

    EXIF DateTimeOriginal carries no zone. When the OffsetTimeOriginal tag is
    absent, the value is interpreted as store-local time, which is what PRODUCT's
    supported-capture-date wording allows.
    """

    exif = image.getexif()
    if not exif:
        return None
    exif_ifd = exif.get_ifd(_EXIF_IFD)
    raw = exif.get(_EXIF_DATETIME_ORIGINAL) or exif_ifd.get(_EXIF_DATETIME_ORIGINAL)
    if not raw:
        return None
    try:
        naive = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    zone = _parse_offset(exif_ifd.get(_EXIF_OFFSET_TIME_ORIGINAL)) or store_timezone
    return naive.replace(tzinfo=zone)


def render_display(
    source: bytes,
    *,
    store_timezone: ZoneInfo,
    max_dimension: int = MAX_DISPLAY_DIMENSION,
    quality: int = DISPLAY_QUALITY,
) -> Derivative:
    """Decode source bytes and render an EXIF-free JPEG public derivative."""

    try:
        with Image.open(BytesIO(source)) as image:
            capture_time = read_capture_time(image, store_timezone)
            oriented = ImageOps.exif_transpose(image)
            try:
                rgb = oriented.convert("RGB")
            finally:
                oriented.close()
            try:
                if max(rgb.size) > max_dimension:
                    rgb.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
                width, height = rgb.size
            finally:
                rgb.close()
    except OSError as error:
        raise DerivativeError(f"could not decode source image: {error}") from error
    if capture_time is None:
        return Derivative(
            buffer.getvalue(),
            JPEG_MEDIA_TYPE,
            width,
            height,
            None,
            CaptureTimeSource.UNKNOWN,
        )
    return Derivative(
        buffer.getvalue(),
        JPEG_MEDIA_TYPE,
        width,
        height,
        capture_time,
        CaptureTimeSource.EXIF,
    )


def _parse_offset(value: object) -> timezone | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text in ("", "Z"):
        return timezone.utc if text == "Z" else None
    sign = 1 if text.startswith("+") else -1 if text.startswith("-") else 0
    if not sign:
        return None
    body = text[1:].replace(":", "")
    if len(body) == 4 and body.isdigit():
        hours, minutes = int(body[:2]), int(body[2:])
    elif len(body) == 2 and body.isdigit():
        hours, minutes = int(body), 0
    else:
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))
