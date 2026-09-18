from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.import_jsonl import import_jsonl_events
from backend.telemetry.report import summarize
from backend.telemetry.sqlite_store import TelemetryStores
from tests.unit.test_telemetry_report import demo_events


class TelemetryImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.log_path = root / "pitch-telemetry.jsonl"
        self.events = demo_events()
        self.log_path.write_text(
            "\n".join(json.dumps(entry, sort_keys=True) for entry in self.events) + "\n",
            encoding="utf-8",
        )

    def test_imported_events_reproduce_the_committed_demo_report(self) -> None:
        with StoreRepository.open(self.database_path) as stores:
            store = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
        with TelemetryStores.open(self.database_path) as telemetry:
            sink = telemetry.for_store(store)
            result = import_jsonl_events(sink, self.log_path, store_id=store.store_id)
            imported = sink.events()
            second = import_jsonl_events(sink, self.log_path, store_id=store.store_id)
            count = sink.count()
        self.assertEqual((result.imported, result.duplicates_ignored), (len(self.events), 0))
        self.assertEqual((second.imported, second.duplicates_ignored), (0, len(self.events)))
        self.assertEqual(count, len(self.events))
        # Read order is recorded time then event ID; the same events are present.
        self.assertEqual(
            sorted(imported, key=lambda entry: str(entry["event_id"])),
            sorted(self.events, key=lambda entry: str(entry["event_id"])),
        )
        self.assertEqual(
            [entry["occurred_at"] for entry in imported],
            sorted(str(entry["occurred_at"]) for entry in imported),
        )
        # Exact parity with the committed report tests' expectations.
        self.assertEqual(summarize(imported), summarize(self.events))
        self.assertEqual(
            summarize(imported)["counts"],
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
            summarize(imported)["sessions"],
            {"total": 3, "homepage": 2, "catalog": 2, "search": 2, "item": 2, "store_action": 1},
        )

    def test_conflicting_duplicate_in_the_log_is_rejected(self) -> None:
        conflicting = dict(self.events[0])
        conflicting["event_type"] = "catalog_opened"
        self.log_path.write_text(
            json.dumps(self.events[0], sort_keys=True)
            + "\n"
            + json.dumps(conflicting, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        with StoreRepository.open(self.database_path) as stores:
            store = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
        with TelemetryStores.open(self.database_path) as telemetry:
            sink = telemetry.for_store(store)
            with self.assertRaisesRegex(ValueError, "reused for different content"):
                import_jsonl_events(sink, self.log_path, store_id=store.store_id)
            self.assertEqual(sink.count(), 1)

    def test_pre_s4_events_without_coverage_are_reported_by_position(self) -> None:
        historical = dict(self.events[4])
        historical["payload"] = {
            key: value
            for key, value in historical["payload"].items()
            if key not in ("published_count", "ready_count", "excluded_unindexed_count")
        }
        self.log_path.write_text(json.dumps(historical, sort_keys=True) + "\n", encoding="utf-8")
        with StoreRepository.open(self.database_path) as stores:
            store = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
        with TelemetryStores.open(self.database_path) as telemetry:
            sink = telemetry.for_store(store)
            with self.assertRaisesRegex(ValueError, "entry 1.*published/ready/excluded"):
                import_jsonl_events(sink, self.log_path, store_id=store.store_id)
            self.assertEqual(sink.count(), 0)
