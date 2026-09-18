from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.report import summarize_store
from backend.telemetry.sqlite_store import TelemetryStores
from tests.unit.test_telemetry_sink import (
    SEARCH,
    SESSION,
    add_store,
    append_search_journey,
)

MERCHANT_SESSION = "44444444-4444-4444-8444-444444444444"
MERCHANT_SEARCH = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class TelemetryIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "shopsearch.sqlite3"
        self.stores = StoreRepository.open(self.database_path)
        self.addCleanup(self.stores.close)
        self.demo = seed_store(self.stores, DEFAULT_DEMO_STORE_PATH)
        self.live = add_store(self.stores, "live-store", is_demo=False)
        self.telemetry = TelemetryStores.open(self.database_path)
        self.addCleanup(self.telemetry.close)

    def test_demo_and_live_traffic_never_share_a_report(self) -> None:
        demo_sink = self.telemetry.for_store(self.demo)
        live_sink = self.telemetry.for_store(self.live)
        append_search_journey(demo_sink, store_id="pitch-demo", traffic="pitch_demo")
        append_search_journey(live_sink, store_id="live-store", traffic="customer")

        demo_report = summarize_store(demo_sink, "pitch-demo")
        live_report = summarize_store(live_sink, "live-store")

        self.assertEqual(demo_report["traffic"], {"pitch_demo": 2})
        self.assertEqual(live_report["traffic"], {"customer": 2})
        self.assertEqual(demo_report["customer"]["counts"]["searches"], 0)  # type: ignore[index]
        self.assertEqual(demo_report["demo"]["counts"]["searches"], 1)  # type: ignore[index]
        self.assertEqual(live_report["customer"]["counts"]["searches"], 1)  # type: ignore[index]
        self.assertEqual(live_report["demo"]["counts"]["searches"], 0)  # type: ignore[index]
        demo_ids = {entry["event_id"] for entry in demo_sink.events()}
        live_ids = {entry["event_id"] for entry in live_sink.events()}
        self.assertEqual(demo_ids & live_ids, set())
        self.assertTrue(all(e["store_id"] == "pitch-demo" for e in demo_sink.events()))
        self.assertTrue(all(e["store_id"] == "live-store" for e in live_sink.events()))

    def test_merchant_self_traffic_is_excluded_from_customer_denominators(self) -> None:
        live_sink = self.telemetry.for_store(self.live)
        append_search_journey(
            live_sink,
            store_id="live-store",
            traffic="customer",
            session_id=SESSION,
            search_id=SEARCH,
        )
        append_search_journey(
            live_sink,
            store_id="live-store",
            traffic="merchant_self",
            session_id=MERCHANT_SESSION,
            search_id=MERCHANT_SEARCH,
        )
        report = summarize_store(live_sink, "live-store")

        self.assertEqual(report["traffic"], {"customer": 2, "merchant_self": 2})
        customer = report["customer"]
        assert isinstance(customer, dict)
        self.assertEqual(customer["counts"]["searches"], 1)  # type: ignore[index]
        self.assertEqual(customer["sessions"]["total"], 1)  # type: ignore[index]
        self.assertEqual(report["merchant_self_events"], 2)
        self.assertIn("customer denominators", str(report["denominators"]))

    def test_report_notes_make_no_customer_value_claims(self) -> None:
        report = summarize_store(self.telemetry.for_store(self.live), "live-store")
        notes = " ".join(str(note) for note in report["notes"])  # type: ignore[union-attr]
        self.assertIn("not people", notes)
        self.assertIn("Merchant-self traffic is excluded", notes)
        for claim in ("demand", "availability", "customer value"):
            with self.subTest(claim=claim):
                self.assertIn(claim, notes)
