"""Bounded, sniffed image uploads normalized through the existing derivative path.

S7 accepts only formats already available through the pinned Pillow dependency
(JPEG, PNG, WebP); HEIC is not supported and no new dependency is added. The
declared content type is never trusted: format comes from decoding the bytes, and a
declared type that contradicts the decoded bytes is rejected.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError

from backend.media.derivatives import Derivative, DerivativeError, render_display

# 12 MiB covers normal phone photos without leaving uploads effectively unlimited.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_IGNORED_DECLARED_TYPES = frozenset({"", "application/octet-stream"})


class UploadError(ValueError):
    """Raised when an uploaded photo cannot become a stored representation."""


@dataclass(frozen=True)
class ValidatedUpload:
    source_bytes: bytes
    source_sha256: str
    derivative: Derivative
    detected_format: str
    declared_content_type: str | None


def validate_upload(
    data: object,
    *,
    declared_content_type: object,
    store_timezone: ZoneInfo,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> ValidatedUpload:
    """Validate bytes before any persistent catalog or media state is created."""

    if not isinstance(data, bytes) or not data:
        raise UploadError("Choose a photo to upload.")
    if len(data) > max_bytes:
        raise UploadError(f"That photo is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(BytesIO(data)) as image:
            detected_format = str(image.format or "")
    except (UnidentifiedImageError, OSError) as error:
        raise UploadError("That file is not a supported image.") from error
    media_type = SUPPORTED_FORMATS.get(detected_format)
    if media_type is None:
        raise UploadError("Unsupported image format; use JPEG, PNG or WebP.")
    declared = _normalized_content_type(declared_content_type)
    if declared not in _IGNORED_DECLARED_TYPES and declared != media_type:
        raise UploadError("The file's declared type does not match its contents.")
    try:
        derivative = render_display(data, store_timezone=store_timezone)
    except DerivativeError as error:
        raise UploadError("That image could not be processed.") from error
    return ValidatedUpload(
        source_bytes=data,
        source_sha256=hashlib.sha256(data).hexdigest(),
        derivative=derivative,
        detected_format=detected_format,
        declared_content_type=declared or None,
    )


def _normalized_content_type(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.split(";", 1)[0].strip().lower()
