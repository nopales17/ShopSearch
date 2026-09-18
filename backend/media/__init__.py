"""Durable media for the store-scoped platform.

ADR-0004 selects a content-addressed local filesystem store behind an
`ImageStore` protocol and `media_url()` indirection. No module outside this
package composes media filesystem paths.

Implemented in S3: the image store, public derivative generation and EXIF-aware
capture-time reading. Upload handling is S7.
"""

from backend.media.derivatives import Derivative, read_capture_time, render_display
from backend.media.image_store import (
    DISPLAY_VARIANT,
    ImageStore,
    LocalImageStore,
    MediaError,
    media_url,
)

__all__ = [
    "DISPLAY_VARIANT",
    "Derivative",
    "ImageStore",
    "LocalImageStore",
    "MediaError",
    "media_url",
    "read_capture_time",
    "render_display",
]
