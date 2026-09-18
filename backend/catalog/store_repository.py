"""Store-scoped mutable catalog persistence: items, images and item events.

S3 replaces the immutable JSON catalog at runtime. All SQL for catalog and image
metadata lives here; the web adapter receives this repository, never a connection
(ADR-0005 §2). Every method takes a `StoreScope`, and child rows reference their
parent by the composite `(store_id, item_id)` key, so a row cannot cross stores.

Listing state (`draft`/`published`/`hidden`/`sold`) and `index_state` are
independent columns: publication never depends on semantic indexing (ADR-0005 §5).
Nothing is hard-deleted; mutations append `item_events`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from uuid import uuid4

from backend.catalog.read_model import LoadedCatalog
from backend.media.image_store import DISPLAY_VARIANT, media_url, validate_media_address
from backend.platform import db as platform_db
from backend.platform.db import utc_now
from contracts.catalog import (
    CaptureTimeSource,
    CatalogImageRecord,
    CatalogItem,
    EvidenceRef,
    IndexState,
    ItemObservation,
    ListingState,
    ObservationSource,
)
from contracts.store import Store, StoreScope

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")
_PRICE_KINDS = ("unknown", "known", "illustrative_demo")


class CatalogError(ValueError):
    """Raised when a catalog record or address cannot be used safely."""


class CatalogConflictError(CatalogError):
    """Raised when the schema rejects a store-scoped catalog write."""


@dataclass(frozen=True)
class ItemState:
    item_id: str
    listing_state: ListingState
    index_state: IndexState
    index_attempts: int
    index_error: str | None


class CatalogRepository:
    """Typed, store-scoped access to `items`, `images` and `item_events`."""

    @classmethod
    def open(cls, database_path: Any) -> "CatalogRepository":
        return cls(platform_db.Database.open(database_path))

    def __init__(self, database: platform_db.Database) -> None:
        self._database = database

    def close(self) -> None:
        self._database.close()

    def __enter__(self) -> "CatalogRepository":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- writes -------------------------------------------------------------

    def create_item(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        title: str,
        category: str,
        price: Decimal | None,
        price_kind: str,
        attributes: Mapping[str, Any],
        provenance: Sequence[EvidenceRef],
        catalog_version: str,
        sort_order: int,
        listing_state: ListingState = ListingState.PUBLISHED,
        index_state: IndexState = IndexState.PENDING,
    ) -> bool:
        """Insert an item. Returns False when an identical row already exists."""

        _validate_item(item_id, title, category, price, price_kind, catalog_version, sort_order)
        provenance_json = json.dumps(
            [
                {
                    "source_id": ref.source_id,
                    "source_type": ref.source_type.value,
                    "observed_at": ref.observed_at.isoformat(),
                }
                for ref in provenance
            ],
            sort_keys=True,
        )
        attributes_json = json.dumps(dict(attributes), sort_keys=True)
        connection = self._database.connection()
        existing = connection.execute(
            "SELECT attributes_json, provenance_json, catalog_version, price, price_kind, "
            "title, category, sort_order, listing_state, index_state "
            "FROM items WHERE store_id = ? AND item_id = ?",
            (scope.store_id, item_id),
        ).fetchone()
        payload = (
            attributes_json,
            provenance_json,
            catalog_version,
            str(price) if price is not None else None,
            price_kind,
            title,
            category,
            sort_order,
            listing_state.value,
            index_state.value,
        )
        if existing is not None:
            if tuple(existing) == payload:
                return False
            raise CatalogConflictError(
                f"item {item_id} already exists with different content; import drift is not silent"
            )
        now = utc_now()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO items (
                        store_id, item_id, title, category, price, price_kind,
                        listing_state, index_state, index_attempts, index_error,
                        sort_order, attributes_json, provenance_json, catalog_version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope.store_id,
                        item_id,
                        title,
                        category,
                        str(price) if price is not None else None,
                        price_kind,
                        listing_state.value,
                        index_state.value,
                        sort_order,
                        attributes_json,
                        provenance_json,
                        catalog_version,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise CatalogConflictError(f"item {item_id} violates catalog constraints") from error
        return True

    def add_image(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        sha256: str,
        source_sha256: str,
        media_type: str,
        width: int,
        height: int,
        byte_size: int,
        capture_time: datetime | None,
        capture_time_source: CaptureTimeSource,
        variant: str = DISPLAY_VARIANT,
    ) -> bool:
        """Attach a stored image address to an item in the same store."""

        validate_media_address(sha256, variant)
        validate_media_address(source_sha256, variant)
        _validate_capture_time(capture_time, capture_time_source)
        if not media_type or not media_type.startswith("image/"):
            raise CatalogError("media_type must be an image media type")
        if width <= 0 or height <= 0 or byte_size <= 0:
            raise CatalogError("image dimensions and byte size must be positive")
        connection = self._database.connection()
        existing = connection.execute(
            "SELECT image_id, sha256, source_sha256, media_type, width, height, byte_size, "
            "capture_time, capture_time_source FROM images "
            "WHERE store_id = ? AND item_id = ? AND variant = ?",
            (scope.store_id, item_id, variant),
        ).fetchone()
        capture_text = capture_time.isoformat() if capture_time is not None else None
        if existing is not None:
            payload = (
                sha256,
                source_sha256,
                media_type,
                width,
                height,
                byte_size,
                capture_text,
                capture_time_source.value,
            )
            if tuple(existing)[1:] == payload:
                return False
            raise CatalogConflictError(
                f"image for item {item_id} already exists with different content"
            )
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO images (
                        store_id, image_id, item_id, variant, sha256, source_sha256,
                        media_type, width, height, byte_size, capture_time,
                        capture_time_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope.store_id,
                        str(uuid4()),
                        item_id,
                        variant,
                        sha256,
                        source_sha256,
                        media_type,
                        width,
                        height,
                        byte_size,
                        capture_text,
                        capture_time_source.value,
                        utc_now(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise CatalogConflictError(
                f"image for item {item_id} violates store-scoped catalog constraints"
            ) from error
        return True

    def append_event(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        event_type: str,
        actor: str,
        after: Mapping[str, Any],
        before: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> str:
        """Append one immutable item event; nothing in the catalog is deleted."""

        if not event_type or not actor:
            raise CatalogError("item events require an event type and actor")
        event_id = str(uuid4())
        try:
            with self._database.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO item_events (
                        store_id, event_id, item_id, event_type, actor, occurred_at,
                        before_json, after_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope.store_id,
                        event_id,
                        item_id,
                        event_type,
                        actor,
                        (occurred_at or datetime.now().astimezone()).isoformat(),
                        json.dumps(dict(before), sort_keys=True) if before is not None else None,
                        json.dumps(dict(after), sort_keys=True),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise CatalogConflictError(
                f"event for item {item_id} violates store-scoped catalog constraints"
            ) from error
        return event_id

    # -- reads --------------------------------------------------------------

    def has_items(self, scope: StoreScope) -> bool:
        return self.item_count(scope) > 0

    def item_count(self, scope: StoreScope, listing_state: ListingState | None = None) -> int:
        if listing_state is None:
            row = (
                self._database.connection()
                .execute(
                    "SELECT COUNT(*) AS count FROM items WHERE store_id = ?", (scope.store_id,)
                )
                .fetchone()
            )
        else:
            row = (
                self._database.connection()
                .execute(
                    "SELECT COUNT(*) AS count FROM items WHERE store_id = ? AND listing_state = ?",
                    (scope.store_id, listing_state.value),
                )
                .fetchone()
            )
        return int(row["count"])

    def image_count(self, scope: StoreScope) -> int:
        row = (
            self._database.connection()
            .execute("SELECT COUNT(*) AS count FROM images WHERE store_id = ?", (scope.store_id,))
            .fetchone()
        )
        return int(row["count"])

    def event_count(self, scope: StoreScope) -> int:
        row = (
            self._database.connection()
            .execute(
                "SELECT COUNT(*) AS count FROM item_events WHERE store_id = ?", (scope.store_id,)
            )
            .fetchone()
        )
        return int(row["count"])

    def catalog_version(self, scope: StoreScope) -> str:
        rows = (
            self._database.connection()
            .execute(
                "SELECT DISTINCT catalog_version FROM items WHERE store_id = ?", (scope.store_id,)
            )
            .fetchall()
        )
        if len(rows) != 1:
            raise CatalogError(
                f"store {scope.store_id} has {len(rows)} catalog versions; expected exactly one"
            )
        return str(rows[0]["catalog_version"])

    def item_state(self, scope: StoreScope, item_id: str) -> ItemState | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT item_id, listing_state, index_state, index_attempts, index_error "
                "FROM items WHERE store_id = ? AND item_id = ?",
                (scope.store_id, item_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        return ItemState(
            item_id=str(row["item_id"]),
            listing_state=ListingState(row["listing_state"]),
            index_state=IndexState(row["index_state"]),
            index_attempts=int(row["index_attempts"]),
            index_error=row["index_error"],
        )

    def published(self, scope: StoreScope) -> tuple[CatalogItem, ...]:
        return self._items(scope, (ListingState.PUBLISHED,))

    def get_published(self, scope: StoreScope, item_id: str) -> CatalogItem | None:
        return next((item for item in self.published(scope) if item.item_id == item_id), None)

    def display_image(
        self, scope: StoreScope, item_id: str, variant: str = DISPLAY_VARIANT
    ) -> CatalogImageRecord | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT images.* FROM images JOIN items "
                "ON items.store_id = images.store_id AND items.item_id = images.item_id "
                "WHERE images.store_id = ? AND images.item_id = ? AND images.variant = ? "
                "AND items.listing_state = ?",
                (scope.store_id, item_id, variant, ListingState.PUBLISHED.value),
            )
            .fetchone()
        )
        return None if row is None else _image_record(row)

    def image_by_address(
        self, scope: StoreScope, sha256: str, variant: str
    ) -> CatalogImageRecord | None:
        validate_media_address(sha256, variant)
        row = (
            self._database.connection()
            .execute(
                "SELECT images.* FROM images JOIN items "
                "ON items.store_id = images.store_id AND items.item_id = images.item_id "
                "WHERE images.store_id = ? AND images.sha256 = ? AND images.variant = ? "
                "AND items.listing_state = ?",
                (scope.store_id, sha256, variant, ListingState.PUBLISHED.value),
            )
            .fetchone()
        )
        return None if row is None else _image_record(row)

    def loaded_catalog(self, store: Store) -> LoadedCatalog:
        """Build the read model handed to views, search and telemetry."""

        scope = store.scope
        version = self.catalog_version(scope)
        items: list[CatalogItem] = []
        observations: list[ItemObservation] = []
        for row in self._item_rows(scope, (ListingState.PUBLISHED,)):
            item_id = str(row["item_id"])
            image = self.display_image(scope, item_id)
            evidence = _evidence(row["provenance_json"])
            observations.extend(
                ItemObservation(ref.source_id, ref.source_type, ref.observed_at) for ref in evidence
            )
            items.append(
                CatalogItem(
                    item_id=item_id,
                    store_id=scope.store_id,
                    title=row["title"],
                    category=row["category"],
                    price=_decimal_or_error(row["price"]),
                    image_uri=media_url(scope, image.sha256, image.variant) if image else None,
                    attributes=json.loads(row["attributes_json"]),
                    evidence=list(evidence),
                )
            )
        return LoadedCatalog(
            store.configuration(), version, tuple(items), tuple(observations), "store_catalog"
        )

    # -- internals ----------------------------------------------------------

    def _items(self, scope: StoreScope, states: Sequence[ListingState]) -> tuple[CatalogItem, ...]:
        rows = self._item_rows(scope, states)
        items = []
        for row in rows:
            item_id = str(row["item_id"])
            image = self.display_image(scope, item_id)
            items.append(
                CatalogItem(
                    item_id=item_id,
                    store_id=scope.store_id,
                    title=row["title"],
                    category=row["category"],
                    price=_decimal_or_error(row["price"]),
                    image_uri=media_url(scope, image.sha256, image.variant) if image else None,
                    attributes=json.loads(row["attributes_json"]),
                    evidence=list(_evidence(row["provenance_json"])),
                )
            )
        return tuple(items)

    def _item_rows(self, scope: StoreScope, states: Sequence[ListingState]) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in states)
        return (
            self._database.connection()
            .execute(
                f"SELECT * FROM items WHERE store_id = ? AND listing_state IN ({placeholders}) "
                "ORDER BY sort_order, item_id",
                (scope.store_id, *(state.value for state in states)),
            )
            .fetchall()
        )


def _image_record(row: sqlite3.Row) -> CatalogImageRecord:
    return CatalogImageRecord(
        image_id=str(row["image_id"]),
        item_id=str(row["item_id"]),
        variant=str(row["variant"]),
        sha256=str(row["sha256"]),
        source_sha256=str(row["source_sha256"]),
        media_type=str(row["media_type"]),
        width=int(row["width"]),
        height=int(row["height"]),
        byte_size=int(row["byte_size"]),
        capture_time=(
            datetime.fromisoformat(row["capture_time"]) if row["capture_time"] is not None else None
        ),
        capture_time_source=CaptureTimeSource(row["capture_time_source"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _evidence(value: str) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            source_type=ObservationSource(entry["source_type"]),
            source_id=entry["source_id"],
            observed_at=datetime.fromisoformat(entry["observed_at"]),
        )
        for entry in json.loads(value)
    )


def _validate_item(
    item_id: str,
    title: str,
    category: str,
    price: Decimal | None,
    price_kind: str,
    catalog_version: str,
    sort_order: int,
) -> None:
    if not isinstance(item_id, str) or not _IDENTIFIER.fullmatch(item_id):
        raise CatalogError("item_id must be a safe identifier")
    if not isinstance(title, str) or not title.strip():
        raise CatalogError("title must be a non-empty string")
    if not isinstance(category, str) or not category.strip():
        raise CatalogError("category must be a non-empty string")
    if price_kind not in _PRICE_KINDS:
        raise CatalogError("price_kind must be unknown, known or illustrative_demo")
    if price is None:
        if price_kind != "unknown":
            raise CatalogError("unknown price must use price_kind=unknown")
    else:
        if not isinstance(price, Decimal) or not price.is_finite() or price < 0:
            raise CatalogError("price must be a finite nonnegative Decimal")
        if price_kind == "unknown":
            raise CatalogError("a known price cannot use price_kind=unknown")
    if not isinstance(catalog_version, str) or not catalog_version:
        raise CatalogError("catalog_version is required")
    if isinstance(sort_order, bool) or not isinstance(sort_order, int) or sort_order < 0:
        raise CatalogError("sort_order must be a nonnegative integer")


def _validate_capture_time(
    capture_time: datetime | None, capture_time_source: CaptureTimeSource
) -> None:
    if capture_time_source is CaptureTimeSource.UNKNOWN:
        if capture_time is not None:
            raise CatalogError("unknown capture time cannot carry a timestamp")
        return
    if capture_time is None or capture_time.tzinfo is None:
        raise CatalogError("a known capture time needs an explicit UTC offset")
    if not isinstance(capture_time_source, CaptureTimeSource):
        raise CatalogError("capture_time_source must be a CaptureTimeSource")


def _decimal_or_error(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CatalogError("stored price is not decimal-compatible") from error
