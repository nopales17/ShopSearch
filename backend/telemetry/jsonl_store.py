"""Small append-only JSONL telemetry persistence for the local vertical slice."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID

from contracts.telemetry import EventType, TelemetryEvent


class JsonlTelemetryStore:
    def __init__(self, path: Path, traffic: str = "fixture_test") -> None:
        self._path = path
        self._lock = Lock()
        if traffic not in ("fixture_test", "pitch_demo"):
            raise ValueError("only local demo traffic is supported")
        self.traffic = traffic

    def append(self, event: TelemetryEvent) -> bool:
        """Persist an event once. Returns false for a repeated event ID."""

        with self._lock:
            entries = self._events()
            snapshot = _serialize(event)
            _validate(snapshot, entries, self.traffic)
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


def _serialize(event: TelemetryEvent) -> dict[str, Any]:
    value = asdict(event)
    value["event_type"] = event.event_type.value
    value["occurred_at"] = event.occurred_at.isoformat()
    return value


def _validate(
    event: dict[str, Any], entries: list[dict[str, Any]], traffic: str = "fixture_test"
) -> None:
    for field in ("event_id", "session_id"):
        UUID(event[field])
    if not isinstance(event["store_id"], str) or not event["store_id"]:
        raise ValueError("store ID is required")
    if datetime.fromisoformat(event["occurred_at"]).tzinfo is None:
        raise ValueError("event timestamp must include a timezone")
    payload = event["payload"]
    if payload.get("traffic") != traffic:
        raise ValueError("telemetry traffic scope mismatch")
    kind = event["event_type"]
    search_id = event["search_id"]
    if kind in ("search_submitted", "search_results_returned") and not search_id:
        raise ValueError("search events require a search ID")
    if search_id:
        UUID(search_id)
    if kind in ("search_submitted", "search_results_returned", "item_opened"):
        if not payload.get("catalog_version"):
            raise ValueError("catalog version is required")
    if kind == "search_submitted":
        if not isinstance(payload.get("query"), str) or not isinstance(
            payload.get("filters"), dict
        ):
            raise ValueError("search requires original query and filters")
    if kind == "search_results_returned":
        results = payload.get("results")
        if not isinstance(results, list) or payload.get("result_count") != len(results):
            raise ValueError("result count must match results")
        if [result.get("rank") for result in results] != list(range(1, len(results) + 1)):
            raise ValueError("result ranks must be contiguous")
        if any(not result.get("item_id") or not result.get("public_claim") for result in results):
            raise ValueError("result snapshots must include item and public claim")
    if kind == "item_opened" and not payload.get("item_id"):
        raise ValueError("item ID is required")
    if search_id and kind in (
        "search_results_returned",
        "item_opened",
        "call_clicked",
        "directions_clicked",
    ):
        required_kind = (
            "search_submitted" if kind == "search_results_returned" else "search_results_returned"
        )
        parent = next(
            (
                entry
                for entry in entries
                if entry["event_type"] == required_kind
                and entry["search_id"] == search_id
                and entry["session_id"] == event["session_id"]
                and entry["store_id"] == event["store_id"]
                and entry["payload"]["catalog_version"] == payload["catalog_version"]
            ),
            None,
        )
        if parent is None:
            raise ValueError("search attribution does not match session/store/catalog")
        if kind in ("item_opened", "call_clicked", "directions_clicked") and payload[
            "item_id"
        ] not in [r["item_id"] for r in parent["payload"]["results"]]:
            raise ValueError("item was not returned by this search")


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
