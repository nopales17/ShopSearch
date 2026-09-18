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
import math
import re
import sqlite3
import struct
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


class DuplicateImageError(CatalogError):
    """Raised when this store already represents the submitted source bytes."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"source image already published as {item_id}")
        self.item_id = item_id


class CatalogNotFoundError(CatalogError):
    """Raised when the resolved store has no such item; never says whether others do."""


class CatalogStateError(CatalogError):
    """Raised when a listing-state transition is not one of the allowed ones."""


@dataclass(frozen=True)
class ItemState:
    item_id: str
    listing_state: ListingState
    index_state: IndexState
    index_attempts: int
    index_error: str | None


@dataclass(frozen=True)
class StoreGenerations:
    """Per-store catalog and index counters (ADR-0005 §5)."""

    catalog: int
    index: int


@dataclass(frozen=True)
class EmbeddingRecord:
    item_id: str
    dim: int
    model_id: str
    model_revision: str
    image_sha256: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class IndexCandidate:
    item_id: str
    state: IndexState
    attempts: int


@dataclass(frozen=True)
class IndexSummary:
    published: int
    ready: int
    pending: int
    failed: int
    stale: int

    @property
    def excluded_unindexed(self) -> int:
        return self.published - self.ready


@dataclass(frozen=True)
class ManagedItem:
    """One item as a merchant sees it: listing state plus effective index state."""

    item_id: str
    title: str
    category: str
    price: Decimal | None
    listing_state: ListingState
    index_state: IndexState


@dataclass(frozen=True)
class ImageAttachment:
    """One stored image variant attached to an item."""

    sha256: str
    source_sha256: str
    media_type: str
    width: int
    height: int
    byte_size: int
    capture_time: datetime | None
    capture_time_source: CaptureTimeSource
    variant: str = DISPLAY_VARIANT


@dataclass(frozen=True)
class MutationResult:
    """Outcome of one merchant catalog mutation."""

    item_id: str
    changed: bool
    event_id: str | None = None


# The only listing transitions S8 exposes (ADR-0005 §6). Each maps to its event name.
LISTING_TRANSITIONS: dict[tuple[ListingState, ListingState], str] = {
    (ListingState.PUBLISHED, ListingState.HIDDEN): "hidden",
    (ListingState.HIDDEN, ListingState.PUBLISHED): "unhidden",
    (ListingState.PUBLISHED, ListingState.SOLD): "sold",
    (ListingState.SOLD, ListingState.PUBLISHED): "relisted",
}

_CATALOG_BUMP = (
    "UPDATE store_generations SET catalog_generation = catalog_generation + 1, "
    "updated_at = ? WHERE store_id = ?"
)


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
        self.bump_catalog_generation(scope)
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
        self.bump_catalog_generation(scope)
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

    def current_image(
        self, scope: StoreScope, item_id: str, variant: str = DISPLAY_VARIANT
    ) -> CatalogImageRecord | None:
        """Return the item's stored image whatever its listing state.

        Internal catalog/merchant lookups use this: `display_image()` stays the
        customer-facing lookup that only ever returns published items, so hiding or
        selling an item never hides its referenced bytes from cleanup and mutation.
        """

        row = (
            self._database.connection()
            .execute(
                "SELECT * FROM images WHERE store_id = ? AND item_id = ? AND variant = ?",
                (scope.store_id, item_id, variant),
            )
            .fetchone()
        )
        return None if row is None else _image_record(row)

    def image_address_in_use(self, scope: StoreScope, sha256: str, variant: str) -> bool:
        """True when any image row in this store references the address, in any state."""

        validate_media_address(sha256, variant)
        row = (
            self._database.connection()
            .execute(
                "SELECT 1 FROM images WHERE store_id = ? AND sha256 = ? AND variant = ? LIMIT 1",
                (scope.store_id, sha256, variant),
            )
            .fetchone()
        )
        return row is not None

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

    def managed_items(
        self,
        scope: StoreScope,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int,
    ) -> tuple[ManagedItem, ...]:
        """Every item in the store with its listing state and effective index state."""

        managed = []
        for row in self._index_rows(scope, None):
            managed.append(
                ManagedItem(
                    item_id=str(row["item_id"]),
                    title=str(row["title"]),
                    category=str(row["category"]),
                    price=_decimal_or_error(row["price"]),
                    listing_state=ListingState(row["listing_state"]),
                    index_state=_effective_index_state(
                        row,
                        model_id=model_id,
                        model_revision=model_revision,
                        dimensions=dimensions,
                    ),
                )
            )
        return tuple(managed)

    def managed_item(
        self,
        scope: StoreScope,
        item_id: str,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int,
    ) -> ManagedItem | None:
        """One item for the merchant shell, or None when this store has no such item."""

        rows = self._index_rows(scope, None, item_id=item_id)
        if not rows:
            return None
        row = rows[0]
        return ManagedItem(
            item_id=str(row["item_id"]),
            title=str(row["title"]),
            category=str(row["category"]),
            price=_decimal_or_error(row["price"]),
            listing_state=ListingState(row["listing_state"]),
            index_state=_effective_index_state(
                row, model_id=model_id, model_revision=model_revision, dimensions=dimensions
            ),
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

    # -- generations ---------------------------------------------------------

    def generations(self, scope: StoreScope) -> StoreGenerations:
        row = (
            self._database.connection()
            .execute(
                "SELECT catalog_generation, index_generation FROM store_generations "
                "WHERE store_id = ?",
                (scope.store_id,),
            )
            .fetchone()
        )
        if row is None:
            return StoreGenerations(0, 0)
        return StoreGenerations(int(row["catalog_generation"]), int(row["index_generation"]))

    def bump_catalog_generation(self, scope: StoreScope) -> StoreGenerations:
        """Bump the content/listing generation; index-state changes never do this."""

        return self._bump_generation(
            scope,
            "UPDATE store_generations SET catalog_generation = catalog_generation + 1, "
            "updated_at = ? WHERE store_id = ?",
        )

    def bump_index_generation(self, scope: StoreScope) -> StoreGenerations:
        """Bump the embedding generation; index-state changes alone never do this."""

        return self._bump_generation(
            scope,
            "UPDATE store_generations SET index_generation = index_generation + 1, "
            "updated_at = ? WHERE store_id = ?",
        )

    def _bump_generation(self, scope: StoreScope, statement: str) -> StoreGenerations:
        connection = self._database.connection()
        now = utc_now()
        with connection:
            self._bump_generation_on(connection, scope, statement, now)
        return self.generations(scope)

    def _bump_generation_on(
        self,
        connection: sqlite3.Connection,
        scope: StoreScope,
        statement: str,
        now: str,
    ) -> None:
        """Bump one counter inside an existing transaction."""

        cursor = connection.execute(statement, (now, scope.store_id))
        if cursor.rowcount == 0:
            try:
                connection.execute(
                    "INSERT INTO store_generations "
                    "(store_id, catalog_generation, index_generation, updated_at) "
                    "VALUES (?, 0, 0, ?)",
                    (scope.store_id, now),
                )
            except sqlite3.IntegrityError:
                pass  # Another writer created the row; the statement below re-applies.
            connection.execute(statement, (now, scope.store_id))

    # -- merchant publication ------------------------------------------------

    def publish_item_with_image(
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
        image: ImageAttachment,
        actor: str,
    ) -> str:
        """Publish one item, its image and its event in a single transaction.

        Also bumps the catalog generation exactly once. Raises `DuplicateImageError`
        when this store already represents the submitted source bytes, so a
        re-submission never creates a second item or image row.
        """

        _validate_item(item_id, title, category, price, price_kind, catalog_version, 0)
        _validate_capture_time(image.capture_time, image.capture_time_source)
        validate_media_address(image.sha256, image.variant)
        validate_media_address(image.source_sha256, image.variant)
        if not image.media_type.startswith("image/"):
            raise CatalogError("media_type must be an image media type")
        if image.width <= 0 or image.height <= 0 or image.byte_size <= 0:
            raise CatalogError("image dimensions and byte size must be positive")
        if not actor:
            raise CatalogError("item events require an actor")

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
        capture_text = image.capture_time.isoformat() if image.capture_time is not None else None
        event_id = str(uuid4())
        now = utc_now()
        connection = self._database.connection()
        try:
            with connection:
                existing = connection.execute(
                    "SELECT item_id FROM images WHERE store_id = ? AND source_sha256 = ?",
                    (scope.store_id, image.source_sha256),
                ).fetchone()
                if existing is not None:
                    raise DuplicateImageError(str(existing["item_id"]))
                next_order = connection.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
                    "FROM items WHERE store_id = ?",
                    (scope.store_id,),
                ).fetchone()
                connection.execute(
                    "INSERT INTO items ("
                    "store_id, item_id, title, category, price, price_kind, listing_state, "
                    "index_state, index_attempts, index_error, sort_order, attributes_json, "
                    "provenance_json, catalog_version, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?)",
                    (
                        scope.store_id,
                        item_id,
                        title,
                        category,
                        str(price) if price is not None else None,
                        price_kind,
                        ListingState.PUBLISHED.value,
                        IndexState.PENDING.value,
                        int(next_order["next_order"]),
                        attributes_json,
                        provenance_json,
                        catalog_version,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO images ("
                    "store_id, image_id, item_id, variant, sha256, source_sha256, media_type, "
                    "width, height, byte_size, capture_time, capture_time_source, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        scope.store_id,
                        str(uuid4()),
                        item_id,
                        image.variant,
                        image.sha256,
                        image.source_sha256,
                        image.media_type,
                        image.width,
                        image.height,
                        image.byte_size,
                        capture_text,
                        image.capture_time_source.value,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO item_events ("
                    "store_id, event_id, item_id, event_type, actor, occurred_at, "
                    "before_json, after_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                    (
                        scope.store_id,
                        event_id,
                        item_id,
                        "published",
                        actor,
                        now,
                        json.dumps(
                            {
                                "item_id": item_id,
                                "listing_state": ListingState.PUBLISHED.value,
                                "index_state": IndexState.PENDING.value,
                                "price": str(price) if price is not None else None,
                                "price_kind": price_kind,
                                "image_sha256": image.sha256,
                                "source_sha256": image.source_sha256,
                                "capture_time": capture_text,
                                "capture_time_source": image.capture_time_source.value,
                                "catalog_version": catalog_version,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
                self._bump_generation_on(
                    connection,
                    scope,
                    "UPDATE store_generations "
                    "SET catalog_generation = catalog_generation + 1, updated_at = ? "
                    "WHERE store_id = ?",
                    now,
                )
        except DuplicateImageError:
            raise
        except sqlite3.IntegrityError as error:
            # The early lookup above is a fast path; this is the race-safe backstop.
            # A concurrent identical publication committed first, so report the
            # existing item exactly like the sequential duplicate case.
            duplicate = connection.execute(
                "SELECT item_id FROM images WHERE store_id = ? AND source_sha256 = ? "
                "AND variant = ?",
                (scope.store_id, image.source_sha256, image.variant),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateImageError(str(duplicate["item_id"])) from error
            raise CatalogConflictError(f"could not publish item {item_id}") from error
        return event_id

    # -- merchant mutations (S8) ---------------------------------------------

    def update_item_metadata(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        title: str,
        category: str,
        price: Decimal | None,
        price_kind: str,
        actor: str,
    ) -> MutationResult:
        """Amend an item's title, category and price in one transaction.

        Listing state, `index_state` and the item's identity are untouched. An
        unchanged submission is a true no-op: no event and no generation bump.
        """

        if not actor:
            raise CatalogError("item events require an actor")
        _validate_metadata(title, category, price, price_kind)
        subtuple_after = (title, category, price, price_kind)
        connection = self._database.connection()
        now = utc_now()
        with connection:
            row = connection.execute(
                "SELECT title, category, price, price_kind FROM items "
                "WHERE store_id = ? AND item_id = ?",
                (scope.store_id, item_id),
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(item_id)
            subtuple_before = (
                str(row["title"]),
                str(row["category"]),
                _decimal_or_error(row["price"]),
                str(row["price_kind"]),
            )
            if subtuple_before == subtuple_after:
                return MutationResult(item_id, changed=False)
            before = _metadata_payload(*subtuple_before)
            after = _metadata_payload(*subtuple_after)
            event_id = str(uuid4())
            connection.execute(
                "UPDATE items SET title = ?, category = ?, price = ?, price_kind = ?, "
                "updated_at = ? WHERE store_id = ? AND item_id = ?",
                (
                    after["title"],
                    after["category"],
                    _price_text(price),
                    after["price_kind"],
                    now,
                    scope.store_id,
                    item_id,
                ),
            )
            connection.execute(
                "INSERT INTO item_events ("
                "store_id, event_id, item_id, event_type, actor, occurred_at, "
                "before_json, after_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    scope.store_id,
                    event_id,
                    item_id,
                    "metadata_edited",
                    actor,
                    now,
                    json.dumps(before, sort_keys=True),
                    json.dumps(after, sort_keys=True),
                ),
            )
            self._bump_generation_on(connection, scope, _CATALOG_BUMP, now)
        return MutationResult(item_id, changed=True, event_id=event_id)

    def transition_listing_state(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        target: ListingState,
        actor: str,
    ) -> MutationResult:
        """Apply one allowed listing transition, appending exactly one event.

        An already-satisfied target is a no-op; any other transition is rejected.
        """

        if not actor:
            raise CatalogError("item events require an actor")
        if not isinstance(target, ListingState):
            raise CatalogStateError("listing target must be a ListingState")
        connection = self._database.connection()
        now = utc_now()
        with connection:
            row = connection.execute(
                "SELECT listing_state FROM items WHERE store_id = ? AND item_id = ?",
                (scope.store_id, item_id),
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(item_id)
            current = ListingState(str(row["listing_state"]))
            if current is target:
                return MutationResult(item_id, changed=False)
            event_type = LISTING_TRANSITIONS.get((current, target))
            if event_type is None:
                raise CatalogStateError(f"cannot move item from {current.value} to {target.value}")
            event_id = str(uuid4())
            connection.execute(
                "UPDATE items SET listing_state = ?, updated_at = ? "
                "WHERE store_id = ? AND item_id = ?",
                (target.value, now, scope.store_id, item_id),
            )
            connection.execute(
                "INSERT INTO item_events ("
                "store_id, event_id, item_id, event_type, actor, occurred_at, "
                "before_json, after_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    scope.store_id,
                    event_id,
                    item_id,
                    event_type,
                    actor,
                    now,
                    json.dumps({"listing_state": current.value}, sort_keys=True),
                    json.dumps({"listing_state": target.value, "occurred_at": now}, sort_keys=True),
                ),
            )
            self._bump_generation_on(connection, scope, _CATALOG_BUMP, now)
        return MutationResult(item_id, changed=True, event_id=event_id)

    def replace_item_image(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        image: ImageAttachment,
        actor: str,
    ) -> MutationResult:
        """Point an item's current display image at new stored bytes.

        The item keeps its identity and listing state. The index is left pending for
        the existing indexer, and any previous embedding row stays in place but no
        longer matches the item's stored image, so it is never ranked. Re-submitting
        the item's current source bytes is a true no-op; source bytes already owned by
        another item in this store are rejected.
        """

        _validate_capture_time(image.capture_time, image.capture_time_source)
        validate_media_address(image.sha256, image.variant)
        validate_media_address(image.source_sha256, image.variant)
        if not image.media_type.startswith("image/"):
            raise CatalogError("media_type must be an image media type")
        if image.width <= 0 or image.height <= 0 or image.byte_size <= 0:
            raise CatalogError("image dimensions and byte size must be positive")
        if not actor:
            raise CatalogError("item events require an actor")

        capture_text = image.capture_time.isoformat() if image.capture_time is not None else None
        connection = self._database.connection()
        now = utc_now()
        try:
            with connection:
                item = connection.execute(
                    "SELECT listing_state FROM items WHERE store_id = ? AND item_id = ?",
                    (scope.store_id, item_id),
                ).fetchone()
                if item is None:
                    raise CatalogNotFoundError(item_id)
                current = connection.execute(
                    "SELECT sha256, source_sha256, capture_time, capture_time_source FROM images "
                    "WHERE store_id = ? AND item_id = ? AND variant = ?",
                    (scope.store_id, item_id, image.variant),
                ).fetchone()
                if current is None:
                    raise CatalogError(f"item {item_id} has no stored display image to replace")
                if str(current["source_sha256"]) == image.source_sha256:
                    return MutationResult(item_id, changed=False)
                owner = connection.execute(
                    "SELECT item_id FROM images WHERE store_id = ? AND source_sha256 = ? "
                    "AND variant = ?",
                    (scope.store_id, image.source_sha256, image.variant),
                ).fetchone()
                if owner is not None:
                    raise DuplicateImageError(str(owner["item_id"]))
                event_id = str(uuid4())
                connection.execute(
                    "UPDATE images SET sha256 = ?, source_sha256 = ?, media_type = ?, "
                    "width = ?, height = ?, byte_size = ?, capture_time = ?, "
                    "capture_time_source = ? "
                    "WHERE store_id = ? AND item_id = ? AND variant = ?",
                    (
                        image.sha256,
                        image.source_sha256,
                        image.media_type,
                        image.width,
                        image.height,
                        image.byte_size,
                        capture_text,
                        image.capture_time_source.value,
                        scope.store_id,
                        item_id,
                        image.variant,
                    ),
                )
                connection.execute(
                    "UPDATE items SET index_state = ?, index_attempts = 0, index_error = NULL, "
                    "updated_at = ? WHERE store_id = ? AND item_id = ?",
                    (IndexState.PENDING.value, now, scope.store_id, item_id),
                )
                connection.execute(
                    "INSERT INTO item_events ("
                    "store_id, event_id, item_id, event_type, actor, occurred_at, "
                    "before_json, after_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        scope.store_id,
                        event_id,
                        item_id,
                        "image_replaced",
                        actor,
                        now,
                        json.dumps(
                            {
                                "image_sha256": str(current["sha256"]),
                                "source_sha256": str(current["source_sha256"]),
                                "capture_time": current["capture_time"],
                                "capture_time_source": str(current["capture_time_source"]),
                            },
                            sort_keys=True,
                        ),
                        json.dumps(
                            {
                                "image_sha256": image.sha256,
                                "source_sha256": image.source_sha256,
                                "capture_time": capture_text,
                                "capture_time_source": image.capture_time_source.value,
                                "index_state": IndexState.PENDING.value,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
                self._bump_generation_on(connection, scope, _CATALOG_BUMP, now)
        except DuplicateImageError:
            raise
        except sqlite3.IntegrityError as error:
            # The unique `(store_id, source_sha256, variant)` index is the race-safe
            # backstop: a concurrent replacement claimed these bytes first.
            duplicate = connection.execute(
                "SELECT item_id FROM images WHERE store_id = ? AND source_sha256 = ? "
                "AND variant = ?",
                (scope.store_id, image.source_sha256, image.variant),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateImageError(str(duplicate["item_id"])) from error
            raise CatalogConflictError(f"could not replace the image for {item_id}") from error
        return MutationResult(item_id, changed=True, event_id=event_id)

    # -- embeddings ----------------------------------------------------------

    def put_ready_embedding(
        self,
        scope: StoreScope,
        *,
        item_id: str,
        vector: Sequence[float],
        model_id: str,
        model_revision: str,
        image_sha256: str,
    ) -> bool:
        """Store one item embedding and mark the item ready.

        The binding is verified against the item's current stored image, so a row
        can never claim a relation the catalog does not have. Returns False when an
        identical row already exists.
        """

        values = _validate_vector(vector)
        if not model_id or not model_revision:
            raise CatalogError("embedding model identity is required")
        validate_media_address(image_sha256, DISPLAY_VARIANT)
        connection = self._database.connection()
        image = connection.execute(
            "SELECT sha256 FROM images WHERE store_id = ? AND item_id = ? AND variant = ?",
            (scope.store_id, item_id, DISPLAY_VARIANT),
        ).fetchone()
        if image is None:
            raise CatalogError(f"item {item_id} has no stored display image to bind an embedding")
        if str(image["sha256"]) != image_sha256:
            raise CatalogConflictError(
                f"embedding for {item_id} does not match the item's stored image"
            )
        blob = struct.pack(f"<{len(values)}f", *values)
        existing = connection.execute(
            "SELECT dim, model_id, model_revision, image_sha256, vector FROM embeddings "
            "WHERE store_id = ? AND item_id = ?",
            (scope.store_id, item_id),
        ).fetchone()
        if existing is not None and (
            int(existing["dim"]),
            str(existing["model_id"]),
            str(existing["model_revision"]),
            str(existing["image_sha256"]),
            bytes(existing["vector"]),
        ) == (len(values), model_id, model_revision, image_sha256, blob):
            return False
        now = utc_now()
        try:
            with connection:
                cursor = connection.execute(
                    "UPDATE embeddings SET dim = ?, model_id = ?, model_revision = ?, "
                    "image_sha256 = ?, vector = ?, updated_at = ? "
                    "WHERE store_id = ? AND item_id = ?",
                    (
                        len(values),
                        model_id,
                        model_revision,
                        image_sha256,
                        blob,
                        now,
                        scope.store_id,
                        item_id,
                    ),
                )
                if cursor.rowcount == 0:
                    connection.execute(
                        "INSERT INTO embeddings (store_id, item_id, dim, model_id, "
                        "model_revision, image_sha256, vector, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            scope.store_id,
                            item_id,
                            len(values),
                            model_id,
                            model_revision,
                            image_sha256,
                            blob,
                            now,
                            now,
                        ),
                    )
                connection.execute(
                    "UPDATE items SET index_state = ?, index_attempts = 0, index_error = NULL "
                    "WHERE store_id = ? AND item_id = ?",
                    (IndexState.READY.value, scope.store_id, item_id),
                )
        except sqlite3.IntegrityError as error:
            raise CatalogConflictError(
                f"embedding for {item_id} violates store-scoped catalog constraints"
            ) from error
        self.bump_index_generation(scope)
        return True

    def mark_index_failed(
        self, scope: StoreScope, *, item_id: str, attempts: int, error: str
    ) -> None:
        """Record one failed indexing attempt; listing state is never touched."""

        with self._database.connection() as connection:
            connection.execute(
                "UPDATE items SET index_state = ?, index_attempts = ?, index_error = ? "
                "WHERE store_id = ? AND item_id = ?",
                (IndexState.FAILED.value, attempts, error[:500], scope.store_id, item_id),
            )

    def reset_index_failures(self, scope: StoreScope) -> int:
        """Return failed items to pending so an operator can retry after a fix."""

        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE items SET index_state = ?, index_attempts = 0, index_error = NULL "
                "WHERE store_id = ? AND index_state = ?",
                (IndexState.PENDING.value, scope.store_id, IndexState.FAILED.value),
            )
        return int(cursor.rowcount)

    def embedding_for(self, scope: StoreScope, item_id: str) -> EmbeddingRecord | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT * FROM embeddings WHERE store_id = ? AND item_id = ?",
                (scope.store_id, item_id),
            )
            .fetchone()
        )
        return None if row is None else _embedding_record(row)

    def ready_vectors(
        self,
        scope: StoreScope,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int,
    ) -> dict[str, tuple[float, ...]]:
        """Published, ready, validly bound vectors keyed by item ID."""

        vectors: dict[str, tuple[float, ...]] = {}
        for row in self._published_index_rows(scope):
            if (
                _effective_index_state(
                    row, model_id=model_id, model_revision=model_revision, dimensions=dimensions
                )
                is not IndexState.READY
            ):
                continue
            vectors[str(row["item_id"])] = _unpack_vector(bytes(row["vector"]), int(row["dim"]))
        return vectors

    def index_summary(
        self, scope: StoreScope, *, model_id: str, model_revision: str, dimensions: int
    ) -> IndexSummary:
        counts = {state: 0 for state in IndexState}
        published = 0
        for row in self._published_index_rows(scope):
            published += 1
            counts[
                _effective_index_state(
                    row, model_id=model_id, model_revision=model_revision, dimensions=dimensions
                )
            ] += 1
        return IndexSummary(
            published=published,
            ready=counts[IndexState.READY],
            pending=counts[IndexState.PENDING],
            failed=counts[IndexState.FAILED],
            stale=counts[IndexState.STALE],
        )

    def index_candidates(
        self,
        scope: StoreScope,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int,
        max_attempts: int,
        limit: int,
    ) -> tuple[IndexCandidate, ...]:
        """Published items that need indexing, excluding failures already at the cap."""

        if max_attempts < 1 or limit < 1:
            raise CatalogError("index candidate limits must be positive")
        candidates: list[IndexCandidate] = []
        for row in self._published_index_rows(scope):
            state = _effective_index_state(
                row, model_id=model_id, model_revision=model_revision, dimensions=dimensions
            )
            attempts = int(row["index_attempts"])
            if state is IndexState.READY:
                continue
            if state is IndexState.FAILED and attempts >= max_attempts:
                continue
            candidates.append(IndexCandidate(str(row["item_id"]), state, attempts))
            if len(candidates) >= limit:
                break
        return tuple(candidates)

    def _published_index_rows(self, scope: StoreScope) -> list[sqlite3.Row]:
        return self._index_rows(scope, (ListingState.PUBLISHED,))

    def _index_rows(
        self,
        scope: StoreScope,
        states: Sequence[ListingState] | None,
        *,
        item_id: str | None = None,
    ) -> list[sqlite3.Row]:
        listing_filter = ""
        parameters: tuple[Any, ...] = (DISPLAY_VARIANT, scope.store_id)
        if states is not None:
            placeholders = ", ".join("?" for _ in states)
            listing_filter = f" AND items.listing_state IN ({placeholders})"
            parameters = (*parameters, *(state.value for state in states))
        if item_id is not None:
            listing_filter += " AND items.item_id = ?"
            parameters = (*parameters, item_id)
        return (
            self._database.connection()
            .execute(
                f"""
                SELECT items.item_id AS item_id,
                       items.title AS title,
                       items.category AS category,
                       items.price AS price,
                       items.listing_state AS listing_state,
                       items.index_state AS index_state,
                       items.index_attempts AS index_attempts,
                       images.sha256 AS image_sha256,
                       embeddings.dim AS dim,
                       embeddings.model_id AS model_id,
                       embeddings.model_revision AS model_revision,
                       embeddings.image_sha256 AS embedding_image_sha256,
                       embeddings.vector AS vector
                FROM items
                LEFT JOIN images
                  ON images.store_id = items.store_id
                 AND images.item_id = items.item_id
                 AND images.variant = ?
                LEFT JOIN embeddings
                  ON embeddings.store_id = items.store_id
                 AND embeddings.item_id = items.item_id
                WHERE items.store_id = ?{listing_filter}
                ORDER BY items.sort_order, items.item_id
                """,
                parameters,
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
    _validate_metadata(title, category, price, price_kind)
    if not isinstance(catalog_version, str) or not catalog_version:
        raise CatalogError("catalog_version is required")
    if isinstance(sort_order, bool) or not isinstance(sort_order, int) or sort_order < 0:
        raise CatalogError("sort_order must be a nonnegative integer")


def _validate_metadata(title: str, category: str, price: Decimal | None, price_kind: str) -> None:
    """Validate the merchant-amendable fields shared by insert and update."""

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


def _metadata_payload(
    title: str, category: str, price: Decimal | None, price_kind: str
) -> dict[str, Any]:
    """Serializable before/after payload for one metadata change."""

    return {
        "title": title,
        "category": category,
        "price": _price_text(price),
        "price_kind": price_kind,
    }


def _price_text(price: Decimal | None) -> str | None:
    return None if price is None else str(price)


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


def _validate_vector(vector: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if not values:
        raise CatalogError("embedding vector must not be empty")
    if any(not math.isfinite(value) for value in values):
        raise CatalogError("embedding vector must contain finite values")
    return values


def _unpack_vector(blob: bytes, dim: int) -> tuple[float, ...]:
    if dim < 1 or len(blob) != dim * 4:
        raise CatalogError("stored embedding blob does not match its dimension")
    return struct.unpack(f"<{dim}f", blob)


def _embedding_record(row: sqlite3.Row) -> EmbeddingRecord:
    return EmbeddingRecord(
        item_id=str(row["item_id"]),
        dim=int(row["dim"]),
        model_id=str(row["model_id"]),
        model_revision=str(row["model_revision"]),
        image_sha256=str(row["image_sha256"]),
        vector=_unpack_vector(bytes(row["vector"]), int(row["dim"])),
    )


def _effective_index_state(
    row: sqlite3.Row, *, model_id: str, model_revision: str, dimensions: int
) -> IndexState:
    """Read-time index state: a mismatched binding is stale, never ready."""

    stored = IndexState(row["index_state"])
    has_row = row["vector"] is not None
    bound = (
        has_row
        and int(row["dim"]) == dimensions
        and str(row["model_id"]) == model_id
        and str(row["model_revision"]) == model_revision
        and row["image_sha256"] is not None
        and str(row["embedding_image_sha256"]) == str(row["image_sha256"])
    )
    if bound:
        return IndexState.READY if stored is IndexState.READY else IndexState.STALE
    if has_row or stored in (IndexState.READY, IndexState.STALE):
        return IndexState.STALE
    return stored
