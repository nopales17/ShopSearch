"""Read-only aggregate report for validated local demo telemetry JSONL.

Counts describe recorded local demo interactions only. They are not people,
purchases, availability, demand or customer-value evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from contracts.telemetry import EventType

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TELEMETRY_PATH = ROOT / "data/local/pitch-telemetry.jsonl"
KNOWN_EVENT_TYPES = {kind.value for kind in EventType}


def load_events(path: Path) -> list[dict[str, Any]]:
    """Load stored event snapshots, rejecting malformed lines with their location."""

    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} must contain a JSON object")
        events.append(value)
    return events


def summarize(events: Iterable[dict[str, Any]]) -> dict[str, object]:
    """Count recorded demo events with explicit, documented denominators."""

    entries = list(events)
    event_counts = Counter(str(entry.get("event_type", "missing")) for entry in entries)
    traffic_counts = Counter(_traffic(entry) for entry in entries)
    unknown_event_types = sum(
        count
        for kind, count in event_counts.items()
        if kind not in KNOWN_EVENT_TYPES and kind != "missing"
    ) + event_counts.get("missing", 0)
    session_ids = _session_ids(entries)
    homepage_sessions = _sessions_with(entries, EventType.HOMEPAGE_VIEWED)
    catalog_sessions = _sessions_with(entries, EventType.CATALOG_OPENED)
    search_sessions = _sessions_with(entries, EventType.SEARCH_SUBMITTED)
    item_sessions = _sessions_with(entries, EventType.ITEM_OPENED)
    store_action_sessions = _sessions_with(entries, EventType.CALL_CLICKED) | _sessions_with(
        entries, EventType.DIRECTIONS_CLICKED
    )
    submitted_searches = _search_pairs(entries, EventType.SEARCH_SUBMITTED)
    returned_searches = _search_pairs(entries, EventType.SEARCH_RESULTS_RETURNED)
    query_counts: Counter[str] = Counter()
    for entry in entries:
        if entry.get("event_type") != EventType.SEARCH_SUBMITTED.value:
            continue
        normalized = _normalized_query(_payload(entry).get("query"))
        if normalized:
            query_counts[normalized] += 1
    timestamps = sorted(
        entry["occurred_at"]
        for entry in entries
        if isinstance(entry.get("occurred_at"), str) and entry["occurred_at"]
    )
    counts = {
        "homepage_views": _count(entries, EventType.HOMEPAGE_VIEWED),
        "catalog_opens": _count(entries, EventType.CATALOG_OPENED),
        "searches": _count(entries, EventType.SEARCH_SUBMITTED),
        "search_responses": _count(entries, EventType.SEARCH_RESULTS_RETURNED),
        "zero_result_searches": _count(entries, EventType.ZERO_RESULTS),
        "item_opens": _count(entries, EventType.ITEM_OPENED),
        "call_clicks": _count(entries, EventType.CALL_CLICKED),
        "direction_clicks": _count(entries, EventType.DIRECTIONS_CLICKED),
        "searches_missing_response": len(submitted_searches - returned_searches),
    }
    return {
        "counts": counts,
        "event_counts": {kind: event_counts[kind] for kind in sorted(event_counts)},
        "traffic": {name: traffic_counts[name] for name in sorted(traffic_counts)},
        "unknown_event_types": unknown_event_types,
        "sessions": {
            "total": len(session_ids),
            "homepage": len(homepage_sessions),
            "catalog": len(catalog_sessions),
            "search": len(search_sessions),
            "item": len(item_sessions),
            "store_action": len(store_action_sessions),
        },
        "local_demo_rates": {
            "catalog_open": _rate(
                len(catalog_sessions & homepage_sessions), len(homepage_sessions)
            ),
            "search_session": _rate(len(search_sessions & catalog_sessions), len(catalog_sessions)),
            "item_open_session": _rate(len(item_sessions & search_sessions), len(search_sessions)),
            "store_action_session": _rate(
                len(store_action_sessions & catalog_sessions), len(catalog_sessions)
            ),
            "zero_result_search": _rate(counts["zero_result_searches"], counts["search_responses"]),
        },
        "denominators": {
            "catalog_open": "unique homepage sessions that also opened the catalog / homepage sessions",
            "search_session": "unique catalog sessions that also searched / catalog sessions",
            "item_open_session": "unique search sessions that also opened an item / search sessions",
            "store_action_session": "unique catalog sessions with a call/direction click / catalog sessions",
            "zero_result_search": "zero_results events / search_results_returned events",
        },
        "normalized_queries": [
            {"query": query, "count": count}
            for query, count in sorted(query_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "window": {
            "first_event": timestamps[0] if timestamps else None,
            "last_event": timestamps[-1] if timestamps else None,
        },
        "notes": [
            "Counts describe recorded local demo interactions, not people or purchases.",
            "Call/direction clicks do not establish completed calls or visits.",
            "Searches without a returned event are reported separately per session/search ID, "
            "not as zero results.",
            "Result counts and query strings do not establish physical availability or demand.",
        ],
    }


def _count(entries: list[dict[str, Any]], kind: EventType) -> int:
    return sum(1 for entry in entries if entry.get("event_type") == kind.value)


def _search_pairs(entries: list[dict[str, Any]], kind: EventType) -> set[tuple[str, str]]:
    return {
        (str(entry["session_id"]), str(entry["search_id"]))
        for entry in entries
        if entry.get("event_type") == kind.value
        and isinstance(entry.get("session_id"), str)
        and entry["session_id"]
        and isinstance(entry.get("search_id"), str)
        and entry["search_id"]
    }


def _session_ids(entries: list[dict[str, Any]]) -> set[str]:
    return {
        str(entry["session_id"])
        for entry in entries
        if isinstance(entry.get("session_id"), str) and entry["session_id"]
    }


def _sessions_with(entries: list[dict[str, Any]], kind: EventType) -> set[str]:
    return {
        str(entry["session_id"])
        for entry in entries
        if entry.get("event_type") == kind.value
        and isinstance(entry.get("session_id"), str)
        and entry["session_id"]
    }


def _payload(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("payload")
    return value if isinstance(value, dict) else {}


def _traffic(entry: dict[str, Any]) -> str:
    value = _payload(entry).get("traffic")
    return value if isinstance(value, str) and value else "unknown"


def _normalized_query(value: object) -> str:
    return " ".join(value.lower().split()) if isinstance(value, str) else ""


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize local ShopSearch demo telemetry. Counts are not customer-value evidence."
    )
    parser.add_argument("--telemetry-path", type=Path, default=DEFAULT_TELEMETRY_PATH)
    arguments = parser.parse_args()
    try:
        events = load_events(arguments.telemetry_path)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summarize(events), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
