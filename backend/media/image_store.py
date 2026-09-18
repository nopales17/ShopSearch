"""Content-addressed image bytes behind the ADR-0004 adapter boundary.

Bytes are addressed by `(store_id, sha256, variant)`. Callers receive a URL from
`media_url()` or bytes from `read()`; they never see or build a filesystem path.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
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

    def delete(self, scope: StoreScope, sha256: str, variant: str) -> bool: ...

    def blob_count(self, scope: StoreScope) -> int: ...

    def check_health(self) -> None:
        """Raise when the configured media root is not a usable directory."""

    def backup_to(self, destination_root: Path) -> int:
        """Synchronise the whole content-addressed tree; return files written."""

    def contains(self, scope: StoreScope, sha256: str, variant: str) -> bool:
        """True when this store (or a backup mirror) holds the addressed bytes."""


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
        validate_media_address(sha256, variant)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise MediaError("bytes do not match the supplied content address")
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

    def delete(self, scope: StoreScope, sha256: str, variant: str) -> bool:
        """Remove stored bytes; used to unwind a failed publication."""

        path = self._path(scope, sha256, variant)
        if not path.is_file():
            return False
        path.unlink()
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break
        return True

    def blob_count(self, scope: StoreScope) -> int:
        root = self._root / scope.store_id
        if not root.exists():
            return 0
        return sum(1 for path in root.rglob("*") if path.is_file())

    def check_health(self) -> None:
        """Create the root if needed, then verify it is a readable, writable directory."""

        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise MediaError("media root is not usable") from error
        if not self._root.is_dir():
            raise MediaError("media root is not a directory")
        if not os.access(self._root, os.R_OK | os.W_OK | os.X_OK):
            raise MediaError("media root is not readable and writable")

    def backup_to(self, destination_root: Path) -> int:
        """Copy the store-scoped tree to a backup root, skipping identical files."""

        destination = Path(destination_root)
        destination.mkdir(parents=True, exist_ok=True)
        written = 0
        if not self._root.exists():
            return written
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            target = destination / path.relative_to(self._root)
            if target.is_file() and target.stat().st_size == path.stat().st_size:
                if target.read_bytes() == path.read_bytes():
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            written += 1
        return written

    def contains(self, scope: StoreScope, sha256: str, variant: str) -> bool:
        return self.exists(scope, sha256, variant)

    def _path(self, scope: StoreScope, sha256: str, variant: str) -> Path:
        validate_media_address(sha256, variant)
        return self._root / scope.store_id / sha256 / variant
