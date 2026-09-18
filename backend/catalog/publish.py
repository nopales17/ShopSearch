"""Merchant publication: one validated upload becomes one published item (S7).

Validation and media writing happen before the catalog transaction, and a failed
publication removes the derivative written for it, so a rejection leaves no item,
image, event, generation change, temporary file or orphan blob. Publication never
computes an embedding: the new item is `pending` for the existing indexer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.catalog.store_repository import (
    CatalogError,
    CatalogRepository,
    DuplicateImageError,
    ImageAttachment,
)
from backend.media.image_store import DISPLAY_VARIANT, ImageStore
from backend.media.uploads import validate_upload
from contracts.catalog import CaptureTimeSource, EvidenceRef, ObservationSource
from contracts.store import Store

UNKNOWN_TITLE = "Untitled item"
UNKNOWN_CATEGORY = "Uncategorized"
MAX_PRICE_DECIMALS = 2
MAX_TITLE_LENGTH = 120
MAX_CATEGORY_LENGTH = 60


class PublishError(ValueError):
    """Raised when a merchant submission cannot be published."""


@dataclass(frozen=True)
class PublishedItem:
    item_id: str
    duplicate: bool = False
    capture_time: datetime | None = None
    capture_time_source: CaptureTimeSource = CaptureTimeSource.UNKNOWN


def parse_price_input(value: object) -> Decimal | None:
    """Parse a merchant price with Decimal; blank stays unknown."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        price = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise PublishError("Enter a price like 24.00, or leave it blank.") from error
    if not price.is_finite() or price < 0:
        raise PublishError("Enter a price like 24.00, or leave it blank.")
    exponent = price.as_tuple().exponent
    if not isinstance(exponent, int) or -exponent > MAX_PRICE_DECIMALS:
        raise PublishError("Prices support at most two decimal places.")
    return price.quantize(Decimal("0.01"))


class MerchantPublisher:
    """The narrow S7 publication operation for exactly one store."""

    def __init__(
        self,
        store: Store,
        catalog_repository: CatalogRepository,
        image_store: ImageStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._catalog = catalog_repository
        self._image_store = image_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(
        self,
        *,
        merchant_id: str,
        photo: bytes,
        declared_content_type: object,
        price: object,
        title: object,
        category: object,
        attested_capture: bool,
    ) -> PublishedItem:
        if not merchant_id:
            raise PublishError("A merchant session is required.")
        if self._store.is_demo:
            # The demo store's mandatory CC0/not-for-sale wording must not be mixed
            # with merchant merchandise (ADR-0005 §8).
            raise PublishError("This storefront is an illustrative demo and cannot publish items.")
        scope = self._store.scope
        store_timezone = ZoneInfo(self._store.timezone)
        price_value = parse_price_input(price)
        title_text = _clean_text(title, MAX_TITLE_LENGTH) or UNKNOWN_TITLE
        category_text = _clean_text(category, MAX_CATEGORY_LENGTH) or UNKNOWN_CATEGORY
        upload = validate_upload(
            photo, declared_content_type=declared_content_type, store_timezone=store_timezone
        )
        capture_time, capture_source = self._capture_provenance(
            upload.derivative.capture_time,
            upload.derivative.capture_time_source,
            attested=attested_capture,
            store_timezone=store_timezone,
        )
        item_id = str(uuid4())
        derivative = upload.derivative
        display_sha256 = hashlib.sha256(derivative.data).hexdigest()
        created_blob = self._image_store.put(
            scope, display_sha256, DISPLAY_VARIANT, derivative.data
        )
        try:
            self._catalog.publish_item_with_image(
                scope,
                item_id=item_id,
                title=title_text,
                category=category_text,
                price=price_value,
                price_kind="unknown" if price_value is None else "known",
                attributes={"source_title": title_text, "merchant_upload": True},
                provenance=(
                    EvidenceRef(
                        ObservationSource.MANUAL,
                        f"merchant-upload-{item_id}",
                        self._clock(),
                    ),
                ),
                catalog_version=self._catalog_version(),
                image=ImageAttachment(
                    sha256=display_sha256,
                    source_sha256=upload.source_sha256,
                    media_type=derivative.media_type,
                    width=derivative.width,
                    height=derivative.height,
                    byte_size=len(derivative.data),
                    capture_time=capture_time,
                    capture_time_source=capture_source,
                ),
                actor=merchant_id,
            )
        except DuplicateImageError as duplicate:
            if created_blob:
                self._image_store.delete(scope, display_sha256, DISPLAY_VARIANT)
            return PublishedItem(duplicate.item_id, duplicate=True)
        except Exception:
            if created_blob:
                self._image_store.delete(scope, display_sha256, DISPLAY_VARIANT)
            raise
        return PublishedItem(item_id, capture_time=capture_time, capture_time_source=capture_source)

    def _capture_provenance(
        self,
        metadata_capture: datetime | None,
        metadata_source: CaptureTimeSource,
        *,
        attested: bool,
        store_timezone: ZoneInfo,
    ) -> tuple[datetime | None, CaptureTimeSource]:
        """EXIF capture wins; an explicit attestation is the supported fallback."""

        if metadata_capture is not None:
            return metadata_capture, metadata_source
        if attested:
            return self._clock().astimezone(store_timezone), CaptureTimeSource.MERCHANT_ATTESTATION
        return None, CaptureTimeSource.UNKNOWN

    def _catalog_version(self) -> str:
        """Keep one represented-catalog version per store (S3 invariant)."""

        try:
            return self._catalog.catalog_version(self._store.scope)
        except CatalogError:
            return f"{self._store.store_id}-catalog-v1"


def _clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) > limit:
        raise PublishError(f"Keep that entry under {limit} characters.")
    return text
