from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    CATALOG_OPENED = "catalog_opened"
    SEARCH_SUBMITTED = "search_submitted"
    SEARCH_RESULTS_RETURNED = "search_results_returned"
    ZERO_RESULTS = "zero_results"
    ITEM_OPENED = "item_opened"
    SIMILAR_CLICKED = "similar_clicked"
    DIRECTIONS_CLICKED = "directions_clicked"
    CALL_CLICKED = "call_clicked"
    AVAILABILITY_REQUESTED = "availability_requested"


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    event_type: EventType
    occurred_at: datetime
    session_id: str
    store_id: str
    search_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
