"""Restore an operator snapshot onto a clean destination.

Restores are deliberately conservative: an existing destination database, or a
non-empty destination media root, is refused unless the operator explicitly passes
`--allow-existing` (documented as destructive, for reviving a known-dead target). The
restored state is verified against the snapshot's own manifest before the command
reports success, so a partially copied media tree cannot pass as a restore.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.catalog.store_repository import read_snapshot_manifest
from backend.media.image_store import LocalImageStore
from backend.ops.layout import DATABASE_FILENAME, MEDIA_DIRNAME
from backend.platform import operational_log
from backend.runtime.config import RuntimeConfig
from contracts.store import StoreScope


class RestoreError(RuntimeError):
    """Raised when a restore would overwrite data or cannot be verified."""


@dataclass(frozen=True)
class RestoreResult:
    database_path: Path
    media_root: Path
    stores: int
    image_addresses: int


def restore_runtime(
    *,
    backup_root: Path,
    database_path: Path,
    media_root: Path,
    allow_existing: bool = False,
    logger: logging.Logger | None = None,
) -> RestoreResult:
    """Copy a snapshot onto a clean destination and verify every reference."""

    snapshot_root = Path(backup_root)
    snapshot = snapshot_root / DATABASE_FILENAME
    snapshot_media = snapshot_root / MEDIA_DIRNAME
    if not snapshot.is_file():
        raise RestoreError(f"no snapshot database at {snapshot}")
    target_database = Path(database_path)
    target_media = Path(media_root)
    if not allow_existing:
        if target_database.exists():
            raise RestoreError(
                f"{target_database} already exists; restore onto a clean destination "
                "or pass --allow-existing to overwrite it deliberately"
            )
        if target_media.exists() and any(target_media.iterdir()):
            raise RestoreError(
                f"{target_media} is not empty; restore onto a clean destination "
                "or pass --allow-existing to overwrite it deliberately"
            )
    target_database.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot, target_database)
    LocalImageStore(snapshot_media).backup_to(target_media)

    manifest = read_snapshot_manifest(target_database)
    restored = LocalImageStore(target_media)
    missing = [
        (store_id, sha256, variant)
        for store_id, sha256, variant in manifest.image_addresses
        if not restored.contains(StoreScope(store_id), sha256, variant)
    ]
    if missing:
        raise RestoreError(
            f"restore verification failed: {len(missing)} image rows do not resolve "
            "to restored media bytes"
        )
    result = RestoreResult(
        database_path=target_database,
        media_root=target_media,
        stores=len(manifest.store_ids),
        image_addresses=len(manifest.image_addresses),
    )
    if logger is not None:
        operational_log.log_event(
            logger,
            "restore",
            outcome="ok",
            stores=result.stores,
            image_addresses=result.image_addresses,
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.ops.runtime_restore",
        description="Restore a ShopSearch backup snapshot onto a clean destination.",
    )
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, help="override SHOPSEARCH_DATABASE")
    parser.add_argument("--media-root", type=Path, help="override SHOPSEARCH_MEDIA_ROOT")
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="overwrite an existing destination database/media root (destructive)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logger = operational_log.configure_operational_logging()
    try:
        config = RuntimeConfig.from_environment()
        database_path = arguments.database or config.database_path
        media_root = arguments.media_root or config.media_root
    except ValueError as error:
        logger.error("configuration error", extra={"reason": str(error)})
        return 2
    try:
        result = restore_runtime(
            backup_root=arguments.backup_root,
            database_path=database_path,
            media_root=media_root,
            allow_existing=arguments.allow_existing,
            logger=logger,
        )
    except (RestoreError, OSError) as error:
        logger.error("restore failed", extra={"reason": str(error)})
        return 1
    print(
        f"restore ok: {result.stores} stores, {result.image_addresses} image rows "
        f"into {result.database_path.parent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
