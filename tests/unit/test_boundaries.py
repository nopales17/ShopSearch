from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from apps.web.server import ROOT
from backend.catalog.repository import CatalogValidationError, load_fixture_catalog
from backend.search.placeholder import PlaceholderSearchService
from backend.telemetry.jsonl_store import JsonlTelemetryStore, new_event
from contracts.search import SearchQuery
from contracts.telemetry import EventType


class CatalogBoundaryTest(unittest.TestCase):
    def test_thirty_records_and_resolvable_fixture_observations(self) -> None:
        catalog = load_fixture_catalog(
            ROOT / "data/demo/catalog.json", ROOT / "data/demo/store.json"
        )
        self.assertEqual(len(catalog.items), 30)
        for item in catalog.items:
            self.assertTrue(item.is_fixture)
            self.assertEqual(item.store_id, catalog.store.store_id)
            for ref in item.evidence:
                self.assertEqual(catalog.observation(ref.source_id).observed_at, ref.observed_at)
        self.assertEqual(catalog.items[0].price, Decimal("39.99"))

    def test_rejects_invalid_price_scope_provenance_and_identity(self) -> None:
        changes = [
            {"price": "NaN"},
            {"price": "Infinity"},
            {"price": "-1"},
            {"price": True},
            {"fixture": False},
            {"store_id": "other-store"},
            {"item_id": "../item"},
            {"item_id": "fixture-002"},
            {
                "evidence": {
                    "source_type": "manual",
                    "source_id": "fixture-source-002",
                    "observed_at": "2026-09-01T09:00:00+00:00",
                }
            },
            {
                "evidence": {
                    "source_type": "manual",
                    "source_id": "source",
                    "observed_at": "2026-09-01T09:00:00",
                }
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for change in changes:
                document = json.loads((ROOT / "data/demo/catalog.json").read_text())
                document["items"][0].update(change)
                path.write_text(json.dumps(document))
                with self.subTest(change=change), self.assertRaises(CatalogValidationError):
                    load_fixture_catalog(path, ROOT / "data/demo/store.json")

    def test_version_changes_when_content_changes_and_unknown_price_is_preserved(self) -> None:
        original = load_fixture_catalog(
            ROOT / "data/demo/catalog.json", ROOT / "data/demo/store.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            document = json.loads((ROOT / "data/demo/catalog.json").read_text())
            document["items"][0]["price"] = None
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(document))
            changed = load_fixture_catalog(path, ROOT / "data/demo/store.json")
        self.assertNotEqual(original.version, changed.version)
        self.assertIsNone(changed.items[0].price)

    def test_placeholder_is_typed_deterministic_and_respects_explicit_constraints(self) -> None:
        catalog = load_fixture_catalog(
            ROOT / "data/demo/catalog.json", ROOT / "data/demo/store.json"
        )
        catalog.items[0].price = None
        service = PlaceholderSearchService(catalog)
        query = SearchQuery(text="blue", price_max=Decimal("22"), category="accessory", limit=30)
        response = service.search(query)
        self.assertTrue(response.is_placeholder)
        self.assertEqual(response.results, service.search(query).results)
        self.assertTrue(response.results)
        for result in response.results:
            item = catalog.items_by_result(result.item_id)
            self.assertIsNotNone(item.price)
            self.assertLessEqual(item.price, Decimal("22"))
            self.assertEqual(item.category, "accessory")
        for invalid in [
            SearchQuery(image_uri="image"),
            SearchQuery(limit=-1),
            SearchQuery(price_max=Decimal("NaN")),
        ]:
            with self.assertRaises(ValueError):
                service.search(invalid)


class TelemetryPersistenceTest(unittest.TestCase):
    def test_snapshot_idempotency_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            store = JsonlTelemetryStore(path)
            event = new_event(
                EventType.SESSION_STARTED,
                str(uuid4()),
                "fixture-store",
                {"traffic": "fixture_test"},
            )
            self.assertTrue(store.append(event))
            self.assertFalse(store.append(event))
            event.payload["new_field"] = "changed after append"
            self.assertNotIn("new_field", JsonlTelemetryStore(path).events()[0]["payload"])
            with self.assertRaises(ValueError):
                store.append(event)

    def test_concurrent_writes_are_complete_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlTelemetryStore(Path(directory) / "events.jsonl")
            events = [
                new_event(
                    EventType.SESSION_STARTED,
                    str(uuid4()),
                    "fixture-store",
                    {"traffic": "fixture_test"},
                )
                for _ in range(20)
            ]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(store.append, events + events))
            self.assertEqual(len(store.events()), 20)

    def test_invalid_event_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            store = JsonlTelemetryStore(path)
            event = new_event(
                EventType.SEARCH_SUBMITTED,
                str(uuid4()),
                "fixture-store",
                {"traffic": "fixture_test"},
            )
            for invalid in [event, replace(event, session_id=""), replace(event, store_id="")]:
                with self.assertRaises(ValueError):
                    store.append(invalid)
            self.assertFalse(path.exists())
