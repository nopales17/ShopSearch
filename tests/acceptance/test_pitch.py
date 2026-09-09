from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, build_opener

from apps.web.pitch_server import create_pitch_server
from backend.telemetry.jsonl_store import JsonlTelemetryStore
from tests.unit.test_pitch import StubEncoder


class PitchHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.log = Path(self.directory.name) / "pitch.jsonl"
        self.server = create_pitch_server(port=0, telemetry_path=self.log, encoder=StubEncoder())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def get(self, path: str) -> bytes:
        with self.client.open(self.url + path, timeout=3) as response:
            return response.read()

    def test_home_search_photo_item_and_simulated_actions(self) -> None:
        self.assertIn(b"See What's In Store", self.get("/"))
        self.assertIn(b"search-form", self.get("/catalog"))
        photo = self.get("/images/pitch-128096.jpg")
        self.assertTrue(photo.startswith(b"\xff\xd8"))
        result = json.loads(self.get("/api/search?q=" + quote("small blue under $50")))
        self.assertIn("Under $50", result["filter_label"])
        events = JsonlTelemetryStore(self.log, "pitch_demo").events()
        returned = next(e for e in events if e["event_type"] == "search_results_returned")
        item_id = returned["payload"]["results"][0]["item_id"]
        self.get(f"/items/{item_id}?" + urlencode({"search_id": result["search_id"]}))
        for kind in ("call", "directions"):
            action = json.loads(
                self.get(
                    "/api/demo-action?"
                    + urlencode(
                        {"kind": kind, "item_id": item_id, "search_id": result["search_id"]}
                    )
                )
            )
            self.assertFalse(action["contacted_business"])
        events = JsonlTelemetryStore(self.log, "pitch_demo").events()
        related = [e for e in events if e["search_id"]]
        self.assertEqual(
            len({(e["session_id"], e["store_id"], e["search_id"]) for e in related}), 1
        )
        self.assertTrue(all(e["payload"]["traffic"] == "pitch_demo" for e in events))
        self.assertEqual(len({e["payload"]["retrieval_index_sha256"] for e in events}), 1)
        self.assertTrue(
            {
                "search_submitted",
                "search_results_returned",
                "item_opened",
                "call_clicked",
                "directions_clicked",
            }
            <= {e["event_type"] for e in events}
        )
        self.assertTrue(events[-1]["payload"]["simulated"])

    def test_zero_results_and_safe_static_routes(self) -> None:
        result = json.loads(self.get("/api/search?q=under%20%241"))
        self.assertEqual(result["count"], 0)
        self.assertIn(
            "zero_results",
            [e["event_type"] for e in JsonlTelemetryStore(self.log, "pitch_demo").events()],
        )
        for path in [
            "/images/../catalog.json",
            "/api/search?category=not-a-category",
            "/api/demo-action?kind=call&item_id=missing",
        ]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.get(path)
            self.assertIn(caught.exception.code, (400, 404))
            caught.exception.close()
