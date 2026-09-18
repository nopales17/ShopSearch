"""Content-addressed image bytes behind the ADR-0004 adapter boundary.

Bytes are addressed by `(store_id, sha256, variant)`. Callers receive a URL from
`media_url()` or bytes from `read()`; they never see or build a filesystem path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from contracts.store import StoreScope

DISPLAY_VARIANT = "display"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_VARIANT = re.compile(r"[a-z][a-z0-9_-]{0,31}")


class MediaError(ValueError):
    """Raised when media bytes cannot be stored or addressed safely."""


class ImageStore(Protocol):
    """Store-scoped durable image bytes. Implementations never expose paths."""

    def put(self, scope: StoreScope, sha256: str, variant: str, data: bytes) -> bool:
        """Store bytes under their content address; return True if newly stored."""

    def read(self, scope: StoreScope, sha256: str, variant: str) -> bytes: ...

    def exists(self, scope: StoreScope, sha256: str, variant: str) -> bool: ...

    def blob_count(self, scope: StoreScope) -> int: ...


def media_url(scope: StoreScope, sha256: str, variant: str) -> str:
    """Return the store-scoped public URL for stored image bytes."""

    validate_media_address(sha256, variant)
    return f"/media/{scope.store_id}/{sha256}/{variant}"


def validate_media_address(sha256: str, variant: str) -> None:
    """Validate a content address without touching the filesystem."""

    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise MediaError("sha256 must be a lowercase hex content address")
    if not isinstance(variant, str) or not _VARIANT.fullmatch(variant):
        raise MediaError("variant must be a safe identifier")


class LocalImageStore:
    """Content-addressed local filesystem implementation."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def put(self, scope: StoreScope, sha256: str, variant: str, data: bytes) -> bool:
        if not isinstance(data, bytes) or not data:
            raise MediaError("image bytes must be a non-empty byte string")
        path = self._path(scope, sha256, variant)
        if path.exists():
            if path.read_bytes() != data:
                raise MediaError("stored bytes do not match the content address")
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return True

    def read(self, scope: StoreScope, sha256: str, variant: str) -> bytes:
        return self._path(scope, sha256, variant).read_bytes()

    def exists(self, scope: StoreScope, sha256: str, variant: str) -> bool:
        return self._path(scope, sha256, variant).is_file()

    def blob_count(self, scope: StoreScope) -> int:
        root = self._root / scope.store_id
        if not root.exists():
            return 0
        return sum(1 for path in root.rglob("*") if path.is_file())

    def _path(self, scope: StoreScope, sha256: str, variant: str) -> Path:
        validate_media_address(sha256, variant)
        return self._root / scope.store_id / sha256 / variant
