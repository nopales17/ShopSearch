"""Idempotent import of the committed Form & Field demo dataset.

The importer reads the reviewed JSON dataset (validated for scope, license,
price kind and source-image hash), renders an EXIF-free public derivative through
the media layer, and persists store-scoped items, images and an import event.
Re-running is a no-op when the dataset content already matches the stored rows;
drift is reported rather than silently rewritten.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.catalog.pitch import load_pitch_catalog
from backend.catalog.store_repository import CatalogRepository
from backend.media.derivatives import render_display
from backend.media.image_store import DISPLAY_VARIANT, ImageStore
from contracts.store import Store

IMPORT_ACTOR = "importer"
IMPORT_EVENT = "imported"


@dataclass(frozen=True)
class ImportResult:
    store_id: str
    items_created: int
    items_unchanged: int
    images_created: int
    images_unchanged: int
    blobs_created: int


def import_pitch_dataset(
    repository: CatalogRepository,
    image_store: ImageStore,
    catalog_path: Path,
    store: Store,
) -> ImportResult:
    """Import every dataset record into one store, idempotently."""

    catalog = load_pitch_catalog(catalog_path, store.configuration())
    scope = store.scope
    store_timezone = ZoneInfo(store.timezone)
    images_root = catalog_path.parent / "images"
    items_created = items_unchanged = 0
    images_created = images_unchanged = 0
    blobs_created = 0

    for sort_order, item in enumerate(catalog.items):
        source_bytes = (images_root / f"{item.item_id}.jpg").read_bytes()
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if source_sha256 != item.attributes["image_sha256"]:
            raise ImportError(f"source bytes for {item.item_id} do not match the reviewed hash")
        existing_image = repository.display_image(scope, item.item_id)
        if existing_image is not None and existing_image.source_sha256 == source_sha256:
            items_unchanged += 1
            images_unchanged += 1
            continue

        derivative = render_display(source_bytes, store_timezone=store_timezone)
        derivative_sha256 = hashlib.sha256(derivative.data).hexdigest()
        if image_store.put(scope, derivative_sha256, DISPLAY_VARIANT, derivative.data):
            blobs_created += 1
        if repository.create_item(
            scope,
            item_id=item.item_id,
            title=item.title or item.item_id,
            category=item.category or "Uncategorised",
            price=item.price,
            price_kind=item.attributes["price_kind"],
            attributes=item.attributes,
            provenance=item.evidence,
            catalog_version=catalog.version,
            sort_order=sort_order,
        ):
            items_created += 1
        else:
            items_unchanged += 1
        if repository.add_image(
            scope,
            item_id=item.item_id,
            sha256=derivative_sha256,
            source_sha256=source_sha256,
            media_type=derivative.media_type,
            width=derivative.width,
            height=derivative.height,
            byte_size=len(derivative.data),
            capture_time=derivative.capture_time,
            capture_time_source=derivative.capture_time_source,
            variant=DISPLAY_VARIANT,
        ):
            images_created += 1
        else:
            images_unchanged += 1
        repository.append_event(
            scope,
            item_id=item.item_id,
            event_type=IMPORT_EVENT,
            actor=IMPORT_ACTOR,
            after={
                "item_id": item.item_id,
                "listing_state": "published",
                "index_state": "pending",
                "source_sha256": source_sha256,
                "catalog_version": catalog.version,
            },
            occurred_at=_source_reviewed_at(item.attributes),
        )

    return ImportResult(
        store_id=scope.store_id,
        items_created=items_created,
        items_unchanged=items_unchanged,
        images_created=images_created,
        images_unchanged=images_unchanged,
        blobs_created=blobs_created,
    )


def _source_reviewed_at(attributes: dict[str, object]) -> datetime | None:
    value = attributes.get("source_reviewed_at")
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)
