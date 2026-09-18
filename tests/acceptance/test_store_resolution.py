from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from apps.web.storefront import open_demo_stack
from apps.web.wsgi import create_pitch_server
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from tests.unit.test_pitch import StubEncoder

REGISTERED_HOST_VARIANTS = [
    "Shop.Example.COM:8443",
    "shop.example.com.",
    "shop.example.com",
]


class HostResolutionHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        development_hosts = root / "development_hosts.json"
        development_hosts.write_text(json.dumps({"127.0.0.1": "pitch-demo"}))
        database_path = root / "store.sqlite3"
        with StoreRepository.open(database_path) as repository:
            store = seed_store(repository, DEFAULT_DEMO_STORE_PATH)
            repository.add_domain(store.scope, "shop.example.com")
        self.stack = open_demo_stack(database_path, root / "media")
        self.server = create_pitch_server(
            port=0,
            encoder=StubEncoder(),
            stack=self.stack,
            development_hosts_path=development_hosts,
            storefronts={self.stack.demo_store.store_id},
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def fetch(self, path: str, host: str = ""):
        headers = {"Host": host} if host else {}
        request = Request(self.url + path, headers=headers)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            body = error.read()
            error.close()
            return error.code, error.headers, body

    def test_registered_hostname_variants_render_the_same_store(self) -> None:
        bodies = []
        for host in REGISTERED_HOST_VARIANTS:
            with self.subTest(host=host):
                status, headers, body = self.fetch("/", host)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("Content-Type"), "text/html; charset=utf-8")
                self.assertIn(b"FORM <span>&</span> FIELD", body)
                bodies.append(body)
        self.assertEqual(len(set(bodies)), 1)

    def test_unknown_host_returns_404_without_any_store_data(self) -> None:
        for path in ["/", "/catalog", "/credits"]:
            with self.subTest(path=path):
                status, headers, body = self.fetch(path, "not-registered.example")
                self.assertEqual(status, 404)
                self.assertEqual(body, b"Not found")
                for leaked in [b"FORM", b"Objects", b"Collection", b"Cleveland"]:
                    self.assertNotIn(leaked, body)
                self.assertIsNone(headers.get("Set-Cookie"))
                self.assertEqual(headers.get("Cache-Control"), "no-store")
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_development_map_resolves_the_local_loopback_host(self) -> None:
        status, _, body = self.fetch("/health", f"127.0.0.1:{self.server.server_port}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")

    def test_health_is_host_independent_and_store_routes_still_404(self) -> None:
        # S10 answers /health at the runtime boundary, before hostname resolution, so
        # an operator can tell a database/media failure from a bad Host header.
        status, _, body = self.fetch("/health", "localhost:1234")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")
        # Every store-scoped route still refuses an unregistered hostname.
        for path in ("/", "/catalog", "/items/pitch-128096"):
            with self.subTest(path=path):
                status, _, body = self.fetch(path, "localhost:1234")
                self.assertEqual(status, 404)
                self.assertEqual(body, b"Not found")
