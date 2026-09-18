"""Shared telemetry event contract: construction, codec, shape rules and attribution.

S5 moved persistence to SQLite without changing the contract, so the platform sink and
the historical JSONL import path serialize, validate, attribute and construct events
identically through this module.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from contracts.telemetry import EventType, TelemetryEvent, TrafficClass, traffic_class

# Storefront traffic classes must report honest retrieval coverage (S4). The Issue #1
# fixture slice keeps its original payload shape and is not migrated.
COVERAGE_TRAFFIC = frozenset(
    {TrafficClass.PITCH_DEMO, TrafficClass.CUSTOMER, TrafficClass.MERCHANT_SELF}
)

ATTRIBUTED_EVENT_TYPES = (
    "search_results_returned",
    "item_opened",
    "call_clicked",
    "directions_clicked",
)


def new_event(
    event_type: EventType,
    session_id: str,
    store_id: str,
    payload: dict[str, Any],
    search_id: str | None = None,
) -> TelemetryEvent:
    """Build one event with a fresh ID and an explicit local offset."""

    return TelemetryEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        occurred_at=datetime.now().astimezone(),
        session_id=session_id,
        store_id=store_id,
        search_id=search_id,
        payload=payload,
    )


def serialize_event(event: TelemetryEvent) -> dict[str, Any]:
    value = asdict(event)
    value["event_type"] = event.event_type.value
    value["occurred_at"] = event.occurred_at.isoformat()
    return value


def deserialize_event(snapshot: Mapping[str, Any]) -> TelemetryEvent:
    """Rebuild the typed event from a stored snapshot (import and read paths)."""

    search_id = snapshot.get("search_id")
    return TelemetryEvent(
        event_id=str(snapshot["event_id"]),
        event_type=EventType(str(snapshot["event_type"])),
        occurred_at=datetime.fromisoformat(str(snapshot["occurred_at"])),
        session_id=str(snapshot["session_id"]),
        store_id=str(snapshot["store_id"]),
        search_id=str(search_id) if search_id else None,
        payload=dict(snapshot.get("payload") or {}),
    )


def validate_event(event: dict[str, Any]) -> TrafficClass:
    """Validate one serialized snapshot; returns its traffic class."""

    for field in ("event_id", "session_id"):
        UUID(event[field])
    if not isinstance(event["store_id"], str) or not event["store_id"]:
        raise ValueError("store ID is required")
    if datetime.fromisoformat(event["occurred_at"]).tzinfo is None:
        raise ValueError("event timestamp must include a timezone")
    payload = event["payload"]
    traffic = traffic_class(payload.get("traffic"))
    if traffic is None:
        raise ValueError("telemetry traffic class is not supported")
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
        if traffic in COVERAGE_TRAFFIC:
            # The platform storefront must report honest retrieval coverage.
            counts = {
                field: payload.get(field)
                for field in ("published_count", "ready_count", "excluded_unindexed_count")
            }
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in counts.values()
            ):
                raise ValueError("search results must report published/ready/excluded counts")
            if counts["published_count"] != (
                counts["ready_count"] + counts["excluded_unindexed_count"]
            ):
                raise ValueError("search coverage counts must be consistent")
    if kind == "item_opened" and not payload.get("item_id"):
        raise ValueError("item ID is required")
    return traffic


def required_parent_kind(event: dict[str, Any]) -> str | None:
    if not event.get("search_id") or event["event_type"] not in ATTRIBUTED_EVENT_TYPES:
        return None
    return (
        "search_submitted"
        if event["event_type"] == "search_results_returned"
        else "search_results_returned"
    )


def select_parent(
    event: dict[str, Any], candidates: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find the in-store parent event this event must resolve to, if any."""

    required = required_parent_kind(event)
    if required is None:
        return None
    payload = _payload(event)
    return next(
        (
            candidate
            for candidate in candidates
            if candidate["event_type"] == required
            and candidate["search_id"] == event["search_id"]
            and candidate["session_id"] == event["session_id"]
            and candidate["store_id"] == event["store_id"]
            and _payload(candidate).get("catalog_version") == payload.get("catalog_version")
        ),
        None,
    )


def validate_attribution(event: dict[str, Any], parent: dict[str, Any] | None) -> None:
    """Reject foreign session, store or catalog-version attribution."""

    if required_parent_kind(event) is None:
        return
    if parent is None:
        raise ValueError("search attribution does not match session/store/catalog")
    if event["event_type"] not in ("item_opened", "call_clicked", "directions_clicked"):
        return
    results = _payload(parent).get("results")
    returned = [entry.get("item_id") for entry in results] if isinstance(results, list) else []
    if event["payload"]["item_id"] not in returned:
        raise ValueError("item was not returned by this search")


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}
