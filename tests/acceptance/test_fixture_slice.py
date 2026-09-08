from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections import Counter
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener

from apps.web.server import ROOT, create_server
from backend.catalog.repository import CatalogValidationError, load_fixture_catalog
from backend.telemetry.jsonl_store import JsonlTelemetryStore


class ItemLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag == "a" and href and href.startswith("/items/"):
            self.links.append(href)


class FixtureSliceAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.telemetry_path = Path(self.temporary_directory.name) / "telemetry.jsonl"
        self.server = create_server(
            ROOT / "data/demo/catalog.json",
            ROOT / "data/demo/store.json",
            self.telemetry_path,
            port=0,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def test_browser_journey_persists_correlated_search_and_item_events(self) -> None:
        home = self._get("/")
        self.assertIn("DEMO / TEST FIXTURE", home)
        self.assertIn("semantic retrieval is not implemented", home)

        results = self._get("/?q=blue")
        self.assertIn("Results for “blue”", results)
        self.assertIn("Blue Prism Demo Fixture", results)
        links = ItemLinks()
        links.feed(results)
        self.assertTrue(links.links)
        detail = self._get(links.links[0])
        self.assertIn("Blue Prism Demo Fixture", detail)
        self.assertIn("not Customer Zero inventory", detail)

        events = [json.loads(line) for line in self.telemetry_path.read_text().splitlines()]
        counts = Counter(event["event_type"] for event in events)
        self.assertEqual(counts["search_submitted"], 1)
        self.assertEqual(counts["search_results_returned"], 1)
        self.assertEqual(counts["item_opened"], 1)
        self.assertEqual(counts["session_started"], 1)
        self.assertEqual(counts["catalog_opened"], 2)

        submitted = next(event for event in events if event["event_type"] == "search_submitted")
        returned = next(
            event for event in events if event["event_type"] == "search_results_returned"
        )
        opened = next(event for event in events if event["event_type"] == "item_opened")
        self.assertEqual(submitted["session_id"], returned["session_id"])
        self.assertEqual(submitted["session_id"], opened["session_id"])
        self.assertEqual(submitted["store_id"], "fixture-store")
        self.assertEqual(submitted["search_id"], returned["search_id"])
        self.assertEqual(submitted["search_id"], opened["search_id"])
        self.assertEqual(returned["payload"]["results"][0]["item_id"], "fixture-001")
        self.assertEqual(opened["payload"]["item_id"], "fixture-001")
        self.assertEqual(len({event["event_id"] for event in events}), len(events))
        self.assertEqual(events, JsonlTelemetryStore(self.telemetry_path).events())
        self.assertIn("observations", returned["payload"]["results"][0])
        self.assertIn("no physical availability asserted", opened["payload"]["public_claim"])

    def test_browsing_item_has_no_search_attribution(self) -> None:
        self._get("/")
        self._get("/items/fixture-030")
        event = JsonlTelemetryStore(self.telemetry_path).events()[-1]
        self.assertEqual(event["event_type"], "item_opened")
        self.assertIsNone(event["search_id"])

    def test_forged_or_other_session_search_is_rejected(self) -> None:
        self._get("/?q=blue")
        search_id = self._search_id()
        other_client = build_opener(HTTPCookieProcessor(CookieJar()))
        for client, path in [
            (self.client, "/items/fixture-001?search_id=made-up"),
            (other_client, "/items/fixture-001?search_id=" + search_id),
            (self.client, "/items/fixture-030?search_id=" + search_id),
        ]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                client.open(self.base_url + path, timeout=3)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        self.assertFalse(
            any(
                e["event_type"] == "item_opened"
                for e in JsonlTelemetryStore(self.telemetry_path).events()
            )
        )

    def test_search_attribution_survives_server_restart(self) -> None:
        self._get("/?q=blue")
        search_id = self._search_id()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = create_server(
            ROOT / "data/demo/catalog.json",
            ROOT / "data/demo/store.json",
            self.telemetry_path,
            port=0,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self._get("/items/fixture-001?search_id=" + search_id)
        self.assertEqual(
            JsonlTelemetryStore(self.telemetry_path).events()[-1]["search_id"], search_id
        )

    def test_escaped_query_static_css_and_unknown_item(self) -> None:
        self.assertIn(".fixture-banner", self._get("/static/style.css"))
        response = self._get("/?q=%3Cscript%3E")
        self.assertNotIn("<script>", response)
        self.assertIn("&lt;script&gt;", response)
        with self.assertRaises(HTTPError) as caught:
            self._get("/items/absent")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_fixture_loader_requires_explicit_non_production_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_path = Path(temporary_directory) / "catalog.json"
            document = json.loads((ROOT / "data/demo/catalog.json").read_text())
            document["not_customer_zero_inventory"] = False
            invalid_path.write_text(json.dumps(document))
            with self.assertRaises(CatalogValidationError):
                load_fixture_catalog(invalid_path, ROOT / "data/demo/store.json")

    def _search_id(self) -> str:
        events = [json.loads(line) for line in self.telemetry_path.read_text().splitlines()]
        return next(
            event["search_id"] for event in events if event["event_type"] == "search_submitted"
        )

    def _get(self, path: str) -> str:
        with self.client.open(self.base_url + path, timeout=3) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode("utf-8")
