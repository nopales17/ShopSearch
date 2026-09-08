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


@dataclass(frozen=True)
class AvailabilityState:
    item_id: str
    kind: AvailabilityKind
    as_of: datetime
    supported_by: tuple[EvidenceRef, ...] = ()
    note: str | None = None
