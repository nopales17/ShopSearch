from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.sqlite_store import SqliteTelemetryStore, TelemetryStores
from contracts.store import Store
from contracts.telemetry import EventType, TelemetryEvent

SESSION = "11111111-1111-4111-8111-111111111111"
SEARCH = "33333333-3333-4333-8333-333333333333"
CATALOG_VERSION = "catalog-v1"


def add_store(store_repository: StoreRepository, store_id: str, *, is_demo: bool) -> Store:
    document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
    document["store_id"] = store_id
    document["is_demo"] = is_demo
    document["domains"] = []
    store, domains = load_store_config_in_memory(document)
    return store_repository.create_store(store, domains)


def make_event(
    event_type: EventType,
    *,
    store_id: str,
    traffic: str,
    search_id: str | None = None,
    session_id: str = SESSION,
    payload: dict[str, object] | None = None,
    event_id: str | None = None,
) -> TelemetryEvent:
    from datetime import datetime, timezone
    from uuid import uuid4

    return TelemetryEvent(
        event_id=event_id or str(uuid4()),
        event_type=event_type,
        occurred_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        session_id=session_id,
        store_id=store_id,
        search_id=search_id,
        payload={"traffic": traffic, **(payload or {})},
    )


def append_search_journey(
    sink: SqliteTelemetryStore,
    *,
    store_id: str,
    traffic: str,
    session_id: str = SESSION,
    search_id: str = SEARCH,
) -> None:
    sink.append(
        make_event(
            EventType.SEARCH_SUBMITTED,
            store_id=store_id,
            traffic=traffic,
            search_id=search_id,
            session_id=session_id,
            payload={"query": "blue", "filters": {}, "catalog_version": CATALOG_VERSION},
        )
    )
    sink.append(
        make_event(
            EventType.SEARCH_RESULTS_RETURNED,
            store_id=store_id,
            traffic=traffic,
            search_id=search_id,
            session_id=session_id,
            payload={
                "catalog_version": CATALOG_VERSION,
                "result_count": 1,
                "published_count": 1,
                "ready_count": 1,
                "excluded_unindexed_count": 0,
                "results": [{"item_id": "item-1", "public_claim": "demo only", "rank": 1}],
            },
        )
    )


class SqliteTelemetrySinkTest(unittest.TestCase):
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

    def sink(self, store: Store) -> SqliteTelemetryStore:
        return self.telemetry.for_store(store)

    def test_append_is_append_only_and_ignores_identical_duplicates(self) -> None:
        sink = self.sink(self.demo)
        event = make_event(EventType.SESSION_STARTED, store_id="pitch-demo", traffic="pitch_demo")
        self.assertTrue(sink.append(event))
        self.assertFalse(sink.append(event))
        self.assertEqual(sink.count(), 1)
        stored = sink.events()
        self.assertEqual(len(stored), 1)
        self.assertEqual(
            set(stored[0]),
            {
                "event_id",
                "event_type",
                "occurred_at",
                "session_id",
                "store_id",
                "search_id",
                "payload",
            },
        )
        self.assertEqual(stored[0]["payload"]["traffic"], "pitch_demo")

    def test_conflicting_event_id_reuse_is_rejected(self) -> None:
        sink = self.sink(self.demo)
        event = make_event(EventType.SESSION_STARTED, store_id="pitch-demo", traffic="pitch_demo")
        sink.append(event)
        conflicting = make_event(
            EventType.CATALOG_OPENED,
            store_id="pitch-demo",
            traffic="pitch_demo",
            event_id=event.event_id,
        )
        with self.assertRaisesRegex(ValueError, "reused for different content"):
            sink.append(conflicting)
        self.assertEqual([entry["event_type"] for entry in sink.events()], ["session_started"])

    def test_store_scope_and_traffic_class_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "store scope mismatch"):
            self.sink(self.demo).append(
                make_event(EventType.SESSION_STARTED, store_id="live-store", traffic="pitch_demo")
            )
        with self.assertRaisesRegex(ValueError, "traffic class does not match the store"):
            self.sink(self.demo).append(
                make_event(EventType.SESSION_STARTED, store_id="pitch-demo", traffic="customer")
            )
        with self.assertRaisesRegex(ValueError, "traffic class does not match the store"):
            self.sink(self.live).append(
                make_event(EventType.SESSION_STARTED, store_id="live-store", traffic="pitch_demo")
            )
        with self.assertRaisesRegex(ValueError, "traffic class is not supported"):
            self.sink(self.live).append(
                make_event(EventType.SESSION_STARTED, store_id="live-store", traffic="unlisted")
            )

    def test_foreign_session_and_catalog_attribution_are_rejected(self) -> None:
        sink = self.sink(self.live)
        append_search_journey(sink, store_id="live-store", traffic="customer")
        foreign_session = make_event(
            EventType.ITEM_OPENED,
            store_id="live-store",
            traffic="customer",
            search_id=SEARCH,
            session_id="22222222-2222-4222-8222-222222222222",
            payload={"catalog_version": CATALOG_VERSION, "item_id": "item-1"},
        )
        with self.assertRaisesRegex(ValueError, "attribution"):
            sink.append(foreign_session)
        foreign_catalog = make_event(
            EventType.ITEM_OPENED,
            store_id="live-store",
            traffic="customer",
            search_id=SEARCH,
            payload={"catalog_version": "other-catalog", "item_id": "item-1"},
        )
        with self.assertRaisesRegex(ValueError, "attribution"):
            sink.append(foreign_catalog)
        absent_item = make_event(
            EventType.ITEM_OPENED,
            store_id="live-store",
            traffic="customer",
            search_id=SEARCH,
            payload={"catalog_version": CATALOG_VERSION, "item_id": "item-9"},
        )
        with self.assertRaisesRegex(ValueError, "not returned by this search"):
            sink.append(absent_item)
        sink.append(
            make_event(
                EventType.ITEM_OPENED,
                store_id="live-store",
                traffic="customer",
                search_id=SEARCH,
                payload={"catalog_version": CATALOG_VERSION, "item_id": "item-1"},
            )
        )
        self.assertEqual(sink.count(), 3)

    def test_cross_store_attribution_never_resolves(self) -> None:
        append_search_journey(self.sink(self.live), store_id="live-store", traffic="customer")
        demo_sink = self.sink(self.demo)
        with self.assertRaisesRegex(ValueError, "store scope mismatch"):
            demo_sink.append(
                make_event(
                    EventType.ITEM_OPENED,
                    store_id="live-store",
                    traffic="customer",
                    search_id=SEARCH,
                    payload={"catalog_version": CATALOG_VERSION, "item_id": "item-1"},
                )
            )

    def test_s4_search_coverage_validation_is_preserved(self) -> None:
        sink = self.sink(self.demo)
        base = make_event(
            EventType.SEARCH_SUBMITTED,
            store_id="pitch-demo",
            traffic="pitch_demo",
            search_id=SEARCH,
            payload={"query": "blue", "filters": {}, "catalog_version": CATALOG_VERSION},
        )
        sink.append(base)
        missing_coverage = make_event(
            EventType.SEARCH_RESULTS_RETURNED,
            store_id="pitch-demo",
            traffic="pitch_demo",
            search_id=SEARCH,
            payload={
                "catalog_version": CATALOG_VERSION,
                "result_count": 0,
                "results": [],
            },
        )
        with self.assertRaisesRegex(ValueError, "published/ready/excluded counts"):
            sink.append(missing_coverage)
        inconsistent = make_event(
            EventType.SEARCH_RESULTS_RETURNED,
            store_id="pitch-demo",
            traffic="pitch_demo",
            search_id=SEARCH,
            payload={
                "catalog_version": CATALOG_VERSION,
                "result_count": 0,
                "published_count": 3,
                "ready_count": 1,
                "excluded_unindexed_count": 1,
                "results": [],
            },
        )
        with self.assertRaisesRegex(ValueError, "counts must be consistent"):
            sink.append(inconsistent)

    def test_event_contract_shape_rules_still_apply(self) -> None:
        sink = self.sink(self.demo)
        with self.assertRaisesRegex(ValueError, "search ID"):
            sink.append(
                make_event(
                    EventType.SEARCH_SUBMITTED,
                    store_id="pitch-demo",
                    traffic="pitch_demo",
                    payload={"query": "blue", "filters": {}, "catalog_version": CATALOG_VERSION},
                )
            )
        with self.assertRaisesRegex(ValueError, "catalog version"):
            sink.append(
                make_event(
                    EventType.ITEM_OPENED,
                    store_id="pitch-demo",
                    traffic="pitch_demo",
                    payload={"item_id": "item-1"},
                )
            )

    def test_required_indexes_exist(self) -> None:
        connection = platform_db.connect(self.database_path)
        try:
            names = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
            }
        finally:
            connection.close()
        self.assertIn("telemetry_events_search_idx", names)
        self.assertIn("telemetry_events_time_idx", names)
