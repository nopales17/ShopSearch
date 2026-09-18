from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class ObservationSource(str, Enum):
    MANUAL = "manual"
    STORE_PHOTO = "store_photo"
    CLOSEUP_PHOTO = "closeup_photo"
    INVOICE = "invoice"
    POS = "pos"


class AvailabilityKind(str, Enum):
    RECENTLY_OBSERVED = "recently_observed"
    CONFIRMED_AVAILABLE = "confirmed_available"
    UNCERTAIN = "uncertain"
    UNAVAILABLE = "unavailable"


class ListingState(str, Enum):
    """Merchant assertion about a listing, never an inventory-truth inference."""

    DRAFT = "draft"
    PUBLISHED = "published"
    HIDDEN = "hidden"
    SOLD = "sold"


class IndexState(str, Enum):
    """Derived semantic-index state; never gates publication (ADR-0005 §5)."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


class CaptureTimeSource(str, Enum):
    """Where a photo capture time came from. Import/upload time is never a source."""

    UNKNOWN = "unknown"
    EXIF = "exif"
    MERCHANT_ATTESTATION = "merchant_attestation"


@dataclass(frozen=True)
class EvidenceRef:
    source_type: ObservationSource
    source_id: str
    observed_at: datetime


@dataclass(frozen=True)
class ItemObservation:
    observation_id: str
    source: ObservationSource
    observed_at: datetime
    image_uri: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    model_confidence: float | None = None


@dataclass
class CatalogItem:
    item_id: str
    store_id: str
    title: str | None = None
    category: str | None = None
    price: Decimal | None = None
    image_uri: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    is_fixture: bool = False


@dataclass(frozen=True)
class StoreConfiguration:
    store_id: str
    display_name: str
    currency: str
    timezone: str
    # Catalog-owned public claim wording, supplied by the store record (ADR-0005 §7).
    public_claim: str = "Demo/test fixture; no physical availability asserted"


@dataclass(frozen=True)
class AvailabilityState:
    item_id: str
    kind: AvailabilityKind
    as_of: datetime
    supported_by: tuple[EvidenceRef, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class CatalogImageRecord:
    """Store-scoped metadata for one stored image variant.

    `sha256` addresses the stored bytes for `variant` (content-addressed, ADR-0004);
    `source_sha256` records the reviewed source bytes the derivative came from.
    Capture time is only ever sourced from image metadata or merchant attestation.
    """

    image_id: str
    item_id: str
    variant: str
    sha256: str
    source_sha256: str
    media_type: str
    width: int
    height: int
    byte_size: int
    capture_time: datetime | None
    capture_time_source: CaptureTimeSource
    created_at: datetime
