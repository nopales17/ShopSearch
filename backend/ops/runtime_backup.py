"""One consistent snapshot of the database plus every referenced media blob.

The database snapshot uses SQLite's online backup API inside the persistence layer, so
a live WAL database is snapshotted transaction-consistently rather than copied. The
content-addressed media tree is then synchronised to the same destination, and the
backed-up database is re-read read-only to prove that every image row resolves to
bytes in the backup. Retention/pruning is deliberately not implemented here.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.catalog.store_repository import CatalogRepository, read_snapshot_manifest
from backend.media.image_store import LocalImageStore
from backend.ops.layout import DATABASE_FILENAME, MEDIA_DIRNAME
from backend.platform import operational_log
from backend.runtime.config import BACKUP_ROOT_VARIABLE, ConfigurationError, RuntimeConfig
from contracts.store import StoreScope


class BackupError(RuntimeError):
    """Raised when a backup cannot be completed or verified."""


@dataclass(frozen=True)
class BackupResult:
    snapshot: Path
    media_root: Path
    stores: int
    image_addresses: int
    media_files_written: int


def backup_runtime(
    *,
    database_path: Path,
    media_root: Path,
    destination_root: Path,
    logger: logging.Logger | None = None,
) -> BackupResult:
    """Snapshot the database, mirror the media tree, and verify every reference."""

    destination = Path(destination_root)
    destination.mkdir(parents=True, exist_ok=True)
    snapshot = destination / DATABASE_FILENAME
    with CatalogRepository.open(database_path) as catalog:
        catalog.backup_database_to(snapshot)
    mirrored_media = destination / MEDIA_DIRNAME
    written = LocalImageStore(media_root).backup_to(mirrored_media)

    manifest = read_snapshot_manifest(snapshot)
    mirror = LocalImageStore(mirrored_media)
    missing = [
        (store_id, sha256, variant)
        for store_id, sha256, variant in manifest.image_addresses
        if not mirror.contains(StoreScope(store_id), sha256, variant)
    ]
    if missing:
        raise BackupError(
            f"backup verification failed: {len(missing)} image rows in the snapshot "
            "do not resolve to backed-up media bytes"
        )
    result = BackupResult(
        snapshot=snapshot,
        media_root=mirrored_media,
        stores=len(manifest.store_ids),
        image_addresses=len(manifest.image_addresses),
        media_files_written=written,
    )
    if logger is not None:
        operational_log.log_event(
            logger,
            "backup",
            outcome="ok",
            stores=result.stores,
            image_addresses=result.image_addresses,
            media_files_written=result.media_files_written,
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.ops.runtime_backup",
        description=(
            "Write a consistent ShopSearch snapshot (database + media) to the backup "
            "destination and verify it."
        ),
    )
    parser.add_argument("--database", type=Path, help="override SHOPSEARCH_DATABASE")
    parser.add_argument("--media-root", type=Path, help="override SHOPSEARCH_MEDIA_ROOT")
    parser.add_argument(
        "--destination",
        type=Path,
        help=f"override {BACKUP_ROOT_VARIABLE} (snapshot destination root)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logger = operational_log.configure_operational_logging()
    try:
        config = RuntimeConfig.from_environment()
    except ValueError as error:
        logger.error("configuration error", extra={"reason": str(error)})
        return 2
    destination = arguments.destination or config.backup_root
    if destination is None:
        logger.error(
            "configuration error",
            extra={"reason": f"{BACKUP_ROOT_VARIABLE} or --destination is required"},
        )
        return 2
    try:
        result = backup_runtime(
            database_path=arguments.database or config.database_path,
            media_root=arguments.media_root or config.media_root,
            destination_root=destination,
            logger=logger,
        )
    except (BackupError, OSError, ConfigurationError) as error:
        logger.error("backup failed", extra={"reason": str(error)})
        return 1
    print(
        f"backup ok: {result.stores} stores, {result.image_addresses} image rows, "
        f"{result.media_files_written} media files written to {result.snapshot.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
