from __future__ import annotations

import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener
from uuid import UUID

from apps.web.pitch_server import create_pitch_server as create_legacy_server
from apps.web.wsgi import create_pitch_server
from tests.unit.test_pitch import StubEncoder

ROUTES = [
    ("/", 200, "text/html; charset=utf-8", True),
    ("/catalog", 200, "text/html; charset=utf-8", True),
    ("/credits", 200, "text/html; charset=utf-8", True),
    ("/items/pitch-128096", 200, "text/html; charset=utf-8", True),
    ("/api/search?q=blue", 200, "application/json", True),
    ("/api/demo-action?kind=call&item_id=pitch-128096", 200, "application/json", True),
    ("/health", 200, "text/plain", False),
    ("/static/pitch.css", 200, "text/css", False),
    ("/static/pitch.js", 200, "text/javascript", False),
    ("/images/pitch-128096.jpg", 200, "image/jpeg", False),
    ("/missing", 404, "text/html; charset=utf-8", True),
    ("/items/absent", 404, "text/html; charset=utf-8", True),
    ("/images/../catalog.json", 404, "text/html; charset=utf-8", True),
    ("/api/search?category=not-a-category", 400, "text/plain; charset=utf-8", False),
    (
        "/api/demo-action?kind=call&item_id=missing",
        400,
        "text/plain; charset=utf-8",
        False,
    ),
    ("/?q=" + "a" * 501, 400, "text/plain; charset=utf-8", False),
]

DETERMINISTIC_ROUTES = [
    "/",
    "/catalog",
    "/credits",
    "/items/pitch-128096",
    "/health",
    "/static/pitch.css",
    "/static/pitch.js",
    "/images/pitch-128096.jpg",
    "/missing",
    "/items/absent",
    "/images/../catalog.json",
    "/api/search?category=not-a-category",
    "/api/demo-action?kind=call&item_id=missing",
    "/?q=" + "a" * 501,
]


def fetch(url: str, client=None):
    opener = client or build_opener()
    try:
        with opener.open(url, timeout=5) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        body = error.read()
        error.close()
        return error.code, error.headers, body


class WsgiRouteContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.server = create_pitch_server(
            port=0,
            telemetry_path=Path(self.directory.name) / "events.jsonl",
            encoder=StubEncoder(),
            database_path=Path(self.directory.name) / "store.sqlite3",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def test_routes_keep_status_content_type_headers_and_cookie_contract(self) -> None:
        for path, status, content_type, sets_cookie in ROUTES:
            with self.subTest(path=path):
                actual_status, headers, _ = fetch(self.url + path)
                self.assertEqual(actual_status, status)
                self.assertEqual(headers.get("Content-Type"), content_type)
                self.assertEqual(headers.get("Cache-Control"), "no-store")
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                cookie = headers.get("Set-Cookie")
                if not sets_cookie:
                    self.assertIsNone(cookie)
                    continue
                self.assertIsNotNone(cookie)
                assert cookie is not None
                parts = cookie.split("; ")
                name, _, value = parts[0].partition("=")
                self.assertEqual(name, "shopsearch_session")
                UUID(value)
                self.assertEqual(parts[1:], ["Path=/", "SameSite=Lax", "HttpOnly"])

    def test_session_cookie_is_reused_and_health_stays_session_free(self) -> None:
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        _, health_headers, _ = fetch(self.url + "/health", client)
        self.assertIsNone(health_headers.get("Set-Cookie"))
        _, first_headers, _ = fetch(self.url + "/", client)
        self.assertIsNotNone(first_headers.get("Set-Cookie"))
        _, second_headers, _ = fetch(self.url + "/catalog", client)
        self.assertIsNone(second_headers.get("Set-Cookie"))

    def test_legacy_error_bodies_are_preserved(self) -> None:
        status, _, body = fetch(self.url + "/api/search?category=not-a-category")
        self.assertEqual(status, 400)
        self.assertEqual(body, b"Invalid request or search attribution")
        status, _, body = fetch(self.url + "/images/../catalog.json")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"Not found")


class LegacyParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.legacy = create_legacy_server(
            port=0,
            telemetry_path=root / "legacy.jsonl",
            encoder=StubEncoder(),
            database_path=root / "legacy-store.sqlite3",
        )
        self.wsgi = create_pitch_server(
            port=0,
            telemetry_path=root / "wsgi.jsonl",
            encoder=StubEncoder(),
            database_path=root / "wsgi-store.sqlite3",
        )
        self.legacy_thread = threading.Thread(target=self.legacy.serve_forever, daemon=True)
        self.wsgi_thread = threading.Thread(target=self.wsgi.serve_forever, daemon=True)
        self.legacy_thread.start()
        self.wsgi_thread.start()
        self.legacy_url = f"http://127.0.0.1:{self.legacy.server_port}"
        self.wsgi_url = f"http://127.0.0.1:{self.wsgi.server_port}"

    def tearDown(self) -> None:
        self.legacy.shutdown()
        self.legacy.server_close()
        self.wsgi.shutdown()
        self.wsgi.server_close()
        self.legacy_thread.join(timeout=2)
        self.wsgi_thread.join(timeout=2)
        self.directory.cleanup()

    def test_deterministic_routes_are_byte_identical(self) -> None:
        for path in DETERMINISTIC_ROUTES:
            with self.subTest(path=path):
                legacy_status, legacy_headers, legacy_body = fetch(self.legacy_url + path)
                wsgi_status, wsgi_headers, wsgi_body = fetch(self.wsgi_url + path)
                self.assertEqual(legacy_status, wsgi_status)
                self.assertEqual(
                    legacy_headers.get("Content-Type"), wsgi_headers.get("Content-Type")
                )
                self.assertEqual(
                    legacy_headers.get("Cache-Control"), wsgi_headers.get("Cache-Control")
                )
                self.assertEqual(
                    legacy_headers.get("X-Content-Type-Options"),
                    wsgi_headers.get("X-Content-Type-Options"),
                )
                self.assertEqual(legacy_body, wsgi_body)
