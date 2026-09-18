from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.telemetry.jsonl_store import JsonlTelemetryStore, new_event
from backend.telemetry.report import load_events, summarize
from contracts.telemetry import EventType


def _event(
    event_type: str,
    session_id: str,
    *,
    search_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"{event_type}-{session_id}-{search_id or 'none'}",
        "event_type": event_type,
        "occurred_at": "2026-09-17T12:00:00+00:00",
        "session_id": session_id,
        "store_id": "pitch-demo",
        "search_id": search_id,
        "payload": {"traffic": "pitch_demo", **(payload or {})},
    }


class TelemetryReportTest(unittest.TestCase):
    def test_counts_defined_denominators_and_normalized_queries(self) -> None:
        events = [
            _event("session_started", "s1"),
            _event("homepage_viewed", "s1"),
            _event("catalog_opened", "s1"),
            _event(
                "search_submitted", "s1", search_id="a", payload={"query": " Small   Blue One "}
            ),
            _event("search_results_returned", "s1", search_id="a"),
            _event("item_opened", "s1", search_id="a"),
            _event("call_clicked", "s1", search_id="a"),
            _event("session_started", "s2"),
            _event("homepage_viewed", "s2"),
            _event("catalog_opened", "s2"),
            _event("search_submitted", "s2", search_id="b", payload={"query": "under $1"}),
            _event("search_results_returned", "s2", search_id="b"),
            _event("zero_results", "s2", search_id="b"),
            _event("item_opened", "s3"),
        ]
        report = summarize(events)
        self.assertEqual(
            report["counts"],
            {
                "homepage_views": 2,
                "catalog_opens": 2,
                "searches": 2,
                "search_responses": 2,
                "zero_result_searches": 1,
                "item_opens": 2,
                "call_clicks": 1,
                "direction_clicks": 0,
                "searches_missing_response": 0,
            },
        )
        self.assertEqual(
            report["sessions"],
            {"total": 3, "homepage": 2, "catalog": 2, "search": 2, "item": 2, "store_action": 1},
        )
        self.assertEqual(
            report["normalized_queries"],
            [{"query": "small blue one", "count": 1}, {"query": "under $1", "count": 1}],
        )
        self.assertEqual(
            report["local_demo_rates"],
            {
                "catalog_open": 1.0,
                "search_session": 1.0,
                "item_open_session": 0.5,
                "store_action_session": 0.5,
                "zero_result_search": 0.5,
            },
        )
        self.assertEqual(report["unknown_event_types"], 0)
        self.assertIn("not people or purchases", report["notes"][0])

    def test_incomplete_search_trace_is_not_a_zero_result_event(self) -> None:
        report = summarize(
            [_event("search_submitted", "s1", search_id="unfinished", payload={"query": "blue"})]
        )
        self.assertEqual(report["counts"]["searches"], 1)
        self.assertEqual(report["counts"]["searches_missing_response"], 1)
        self.assertEqual(report["counts"]["zero_result_searches"], 0)
        self.assertIsNone(report["local_demo_rates"]["zero_result_search"])

    def test_same_search_id_in_two_sessions_is_correlated_per_session(self) -> None:
        session_a = "11111111-1111-4111-8111-111111111111"
        session_b = "22222222-2222-4222-8222-222222222222"
        search_id = "33333333-3333-4333-8333-333333333333"
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlTelemetryStore(Path(directory) / "events.jsonl", traffic="pitch_demo")
            submitted = {
                "traffic": "pitch_demo",
                "query": "blue",
                "filters": {},
                "catalog_version": "catalog-v1",
            }
            for session_id in (session_a, session_b):
                store.append(
                    new_event(
                        EventType.SEARCH_SUBMITTED,
                        session_id,
                        "pitch-demo",
                        submitted,
                        search_id,
                    )
                )
            store.append(
                new_event(
                    EventType.SEARCH_RESULTS_RETURNED,
                    session_b,
                    "pitch-demo",
                    {
                        "traffic": "pitch_demo",
                        "catalog_version": "catalog-v1",
                        "result_count": 1,
                        "published_count": 1,
                        "ready_count": 1,
                        "excluded_unindexed_count": 0,
                        "results": [{"item_id": "item-1", "public_claim": "demo only", "rank": 1}],
                    },
                    search_id,
                )
            )
            report = summarize(store.events())
        self.assertEqual(report["counts"]["searches"], 2)
        self.assertEqual(report["counts"]["search_responses"], 1)
        self.assertEqual(report["counts"]["searches_missing_response"], 1)

    def test_load_events_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"event_type": "session_started"}\nnot-json\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2"):
                load_events(path)

    def test_load_events_rejects_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("[1, 2, 3]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                load_events(path)


if __name__ == "__main__":
    unittest.main()
