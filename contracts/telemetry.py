from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    HOMEPAGE_VIEWED = "homepage_viewed"
    CATALOG_OPENED = "catalog_opened"
    SEARCH_SUBMITTED = "search_submitted"
    SEARCH_RESULTS_RETURNED = "search_results_returned"
    ZERO_RESULTS = "zero_results"
    ITEM_OPENED = "item_opened"
    SIMILAR_CLICKED = "similar_clicked"
    DIRECTIONS_CLICKED = "directions_clicked"
    CALL_CLICKED = "call_clicked"
    AVAILABILITY_REQUESTED = "availability_requested"


class TrafficClass(str, Enum):
    """Who produced an interaction. Demo/fixture traffic is never live customer traffic."""

    FIXTURE_TEST = "fixture_test"
    PITCH_DEMO = "pitch_demo"
    CUSTOMER = "customer"
    MERCHANT_SELF = "merchant_self"

    @property
    def is_demo(self) -> bool:
        return self in (TrafficClass.FIXTURE_TEST, TrafficClass.PITCH_DEMO)


def traffic_class(value: object) -> TrafficClass | None:
    """Return the traffic class for a stored value, or None when unsupported."""

    try:
        return TrafficClass(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    event_type: EventType
    occurred_at: datetime
    session_id: str
    store_id: str
    search_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class TelemetrySink(Protocol):
    """Append-only telemetry persistence. Concrete sinks are store-scoped."""

    def append(self, event: TelemetryEvent) -> bool:
        """Persist once, or ignore a byte-identical duplicate; reject conflicting reuse."""

    def events(self) -> list[dict[str, Any]]: ...
