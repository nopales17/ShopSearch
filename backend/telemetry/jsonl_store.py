"""Append-only JSONL telemetry for the retired Issue #1 fixture slice.

The platform storefront writes through `sqlite_store.SqliteTelemetryStore`; this
store remains for the local fixture slice (retired in S10) and for reading the
historical local pitch log. It shares the event contract rules in `validation.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from backend.telemetry.validation import (
    select_parent,
    serialize_event,
    validate_attribution,
    validate_event,
)
from contracts.telemetry import EventType, TelemetryEvent, traffic_class


class JsonlTelemetryStore:
    def __init__(self, path: Path, traffic: str = "fixture_test") -> None:
        self._path = path
        self._lock = Lock()
        parsed = traffic_class(traffic)
        if parsed is None or not parsed.is_demo:
            raise ValueError("only local demo traffic is supported")
        self.traffic = traffic

    def append(self, event: TelemetryEvent) -> bool:
        """Persist an event once. Returns false for a repeated event ID."""

        with self._lock:
            entries = self._events()
            snapshot = serialize_event(event)
            validate_event(snapshot)
            if snapshot["payload"].get("traffic") != self.traffic:
                raise ValueError("telemetry traffic scope mismatch")
            validate_attribution(snapshot, select_parent(snapshot, entries))
            for entry in entries:
                if entry["event_id"] == event.event_id:
                    if entry != snapshot:
                        raise ValueError("event ID reused for different content")
                    return False
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(snapshot, sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return True

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._events()

    def _events(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        return [
            json.loads(line) for line in self._path.read_text(encoding="utf-8").splitlines() if line
        ]


def new_event(
    event_type: EventType,
    session_id: str,
    store_id: str,
    payload: dict[str, Any],
    search_id: str | None = None,
) -> TelemetryEvent:
    from uuid import uuid4

    return TelemetryEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        occurred_at=datetime.now().astimezone(),
        session_id=session_id,
        store_id=store_id,
        search_id=search_id,
        payload=payload,
    )
