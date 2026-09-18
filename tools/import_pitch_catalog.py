"""Import the committed Form & Field demo dataset into a store-scoped catalog.

    python -m tools.import_pitch_catalog --database data/local/shopsearch.sqlite3

Idempotent: an unchanged dataset creates no new item, image or blob.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform.paths import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_MEDIA_ROOT,
)
from backend.stores.repository import StoreRepository
from contracts.store import StoreScope

DEMO_STORE_ID = "pitch-demo"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.import_pitch_catalog",
        description="Import the committed demo dataset into a store catalog.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DEMO_DATASET_PATH)
    parser.add_argument("--store-id", default=DEMO_STORE_ID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    with StoreRepository.open(arguments.database) as stores:
        store = stores.get_store(StoreScope(arguments.store_id))
        with CatalogRepository.open(arguments.database) as catalog:
            result = import_pitch_dataset(
                catalog, LocalImageStore(arguments.media_root), arguments.dataset, store
            )
    print(
        f"imported {result.store_id}: {result.items_created} items, "
        f"{result.images_created} images, {result.blobs_created} blobs created; "
        f"{result.items_unchanged} items unchanged"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
