"""S10 platform runtime: generic startup, health, logging and demo decoupling."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.web.storefront import open_platform_stack
from apps.web.wsgi import create_pitch_app
from backend.catalog.store_repository import CatalogRepository
from backend.platform.operational_log import LOGGER_NAME, JsonLineFormatter
from backend.platform.paths import DEFAULT_DEMO_INDEX_PATH, REPOSITORY_ROOT
from backend.stores.repository import StoreRepository
from backend.telemetry.sqlite_store import TelemetryStores
from contracts.store import StoreScope
from tests.support.isolation_fixture import (
    ALPHA_STORE_ID,
    SHARED_USERNAME,
    IsolationFixture,
    provision_isolation_stores,
)
from tests.unit.test_pitch import StubEncoder

CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')
DEMO_HOST = "https://form-and-field.example"


class PlatformRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.media_root = root / "media"
        # Two provisioned stores and no demo: the S9 shape served by a generic process.
        self.fixture: IsolationFixture = provision_isolation_stores(
            self.database_path, self.media_root
        )
        self.development_hosts = root / "development_hosts.json"
        self.development_hosts.write_text("{}")
        self.client = None

    def capture_json_logs(self, logger: logging.Logger) -> list[str]:
        """Attach the operational JSON formatter and collect the rendered lines."""

        lines: list[str] = []
        formatter = JsonLineFormatter()

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                lines.append(formatter.format(record))

        handler = _Collector()
        previous_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, previous_level)
        return lines

    def app_for(self, **overrides):
        options = {
            "encoder": StubEncoder(),
            "database_path": self.database_path,
            "media_root": self.media_root,
            "development_hosts_path": self.development_hosts,
            "storefronts": self.fixture.storefronts,
        }
        options.update(overrides)
        return create_pitch_app(**options)

    def test_startup_serves_both_stores_and_never_seeds_the_demo(self) -> None:
        stack = open_platform_stack(self.database_path, self.media_root)
        self.addCleanup(stack.close)
        with StoreRepository.open(self.database_path) as stores:
            self.assertIsNone(stores.find_store(StoreScope("pitch-demo")))
            self.assertEqual(
                {store.store_id for store in stores.list_stores()},
                {
                    ALPHA_STORE_ID,
                    self.fixture.beta.store.store_id,
                    self.fixture.unprovisioned.store_id,
                },
            )
        app = self.app_for()
        client = app.test_client()
        for side in self.fixture.stores:
            with self.subTest(store=side.store.store_id):
                self.assertEqual(client.get("/catalog", base_url=side.url_host).status_code, 200)
        # The demo hostname is not registered and never falls back to another store.
        demo = client.get("/", base_url=DEMO_HOST)
        self.assertEqual(demo.status_code, 404)
        self.assertEqual(demo.data, b"Not found")

    def test_startup_does_not_depend_on_the_pitch_demo_index_artifact(self) -> None:
        real_read_bytes = Path.read_bytes
        reads: list[Path] = []

        def guarded(path: Path) -> bytes:
            if path == DEFAULT_DEMO_INDEX_PATH:
                reads.append(path)
                raise AssertionError("the platform runtime read the pitch-demo index artifact")
            return real_read_bytes(path)

        with mock.patch.object(Path, "read_bytes", guarded):
            app = self.app_for()
            client = app.test_client()
            self.assertEqual(
                client.get("/catalog", base_url=self.fixture.alpha.url_host).status_code, 200
            )
            search = client.get(
                "/api/search?q=shared+fixture+object",
                base_url=self.fixture.alpha.url_host,
            )
            self.assertEqual(search.status_code, 200)
        self.assertEqual(reads, [])
        # Live-store telemetry carries no demo artifact hash.
        with TelemetryStores.open(self.database_path) as telemetry:
            events = telemetry.for_store(self.fixture.alpha.store).events()
        self.assertTrue(events)
        for entry in events:
            with self.subTest(event=entry["event_type"]):
                self.assertNotIn("retrieval_index_sha256", entry["payload"])
                self.assertEqual(
                    entry["payload"]["catalog_version"], self.fixture.alpha.catalog_version
                )

    def test_missing_configuration_fails_startup(self) -> None:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPOSITORY_ROOT),
        }
        cases = {
            "SHOPSEARCH_DATABASE": {},
            "SHOPSEARCH_MEDIA_ROOT": {"SHOPSEARCH_DATABASE": str(self.database_path)},
            "SHOPSEARCH_STORES": {
                "SHOPSEARCH_DATABASE": str(self.database_path),
                "SHOPSEARCH_MEDIA_ROOT": str(self.media_root),
            },
        }
        for expected, extra in cases.items():
            with self.subTest(variable=expected):
                completed = subprocess.run(
                    [sys.executable, "-m", "apps.web.wsgi"],
                    cwd=REPOSITORY_ROOT,
                    env={**environment, **extra},
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2, completed.stderr)
                self.assertIn("configuration error", completed.stderr)
                self.assertIn(expected, completed.stderr)
                # The failure never falls back to the demo or repository defaults.
                self.assertNotIn("127.0.0.1", completed.stderr)

    def test_health_reports_real_database_and_media_reachability(self) -> None:
        app = self.app_for()
        client = app.test_client()
        healthy = client.get("/health", base_url=self.fixture.alpha.url_host)
        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(healthy.data, b"ok")
        self.assertEqual(healthy.headers["Content-Type"], "text/plain")
        self.assertEqual(healthy.headers["Cache-Control"], "no-store")
        self.assertIsNone(healthy.headers.get("Set-Cookie"))
        # Health is answered before hostname resolution, without store data.
        self.assertEqual(client.get("/health", base_url="https://unknown.example").status_code, 200)

        # Real media failure: a file blocks the configured media root.
        blocked = Path(self.directory.name) / "blocked"
        blocked.write_text("not a directory")
        media_failure = self.app_for(media_root=blocked / "media")
        failed = media_failure.test_client().get("/health", base_url=self.fixture.alpha.url_host)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.data, b"media unavailable")

        # Injected database failure through the persistence boundary.
        with mock.patch.object(
            CatalogRepository, "check_health", side_effect=RuntimeError("database is gone")
        ):
            database_failure = self.app_for()
        failed = database_failure.test_client().get("/health", base_url=self.fixture.alpha.url_host)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.data, b"database unavailable")
        for response in (failed,):
            text = response.data.decode()
            self.assertNotIn("/", text)
            self.assertNotIn("sqlite", text.lower())

    def test_operational_logs_are_distinct_from_telemetry_and_hold_no_secrets(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        app = self.app_for(logger=logger)
        client = app.test_client()
        crypto_secrets: list[str] = []
        lines = self.capture_json_logs(logger)
        page = client.get("/manage/login", base_url=self.fixture.alpha.url_host)
        login_csrf = CSRF_FIELD.search(page.data)
        assert login_csrf is not None
        crypto_secrets.append(login_csrf.group(1).decode())
        login = client.post(
            "/manage/login",
            base_url=self.fixture.alpha.url_host,
            data={
                "csrf_token": login_csrf.group(1).decode(),
                "username": SHARED_USERNAME,
                "password": self.fixture.alpha.password,
            },
        )
        self.assertEqual(login.status_code, 303)
        token_header = next(
            (header for header in login.headers.getlist("Set-Cookie") if "merchant" in header),
            "",
        )
        if token_header:
            crypto_secrets.append(token_header.split(";", 1)[0].split("=", 1)[1])
        manage = client.get("/manage", base_url=self.fixture.alpha.url_host)
        session_csrf = CSRF_FIELD.search(manage.data)
        if session_csrf is not None:
            crypto_secrets.append(session_csrf.group(1).decode())
        # A rejected CSRF request and a search exercise the error and success paths.
        client.post(
            "/manage/items/iso-shared-object/listing",
            base_url=self.fixture.alpha.url_host,
            data={"csrf_token": "not-the-token", "action": "hide"},
        )
        client.get(
            "/api/search?q=shared+fixture+object",
            base_url=self.fixture.alpha.url_host,
        )
        payloads = [json.loads(line) for line in lines]
        self.assertTrue(payloads)
        logged_paths = {payload.get("path") for payload in payloads}
        self.assertIn("/manage/login", logged_paths)
        self.assertIn("/manage", logged_paths)
        self.assertIn("/api/search", logged_paths)
        for payload in payloads:
            with self.subTest(event=payload.get("event")):
                self.assertIn("level", payload)
                self.assertNotIn("?", str(payload.get("path", "")))
                self.assertNotIn("query", payload)
                self.assertNotIn("payload", payload)
        logged_text = "\n".join(lines)
        secrets = [
            self.fixture.alpha.password,
            SHARED_USERNAME,
            *crypto_secrets,
        ]
        for secret in secrets:
            if not secret:
                continue
            with self.subTest(secret=secret[:6]):
                self.assertNotIn(secret, logged_text)
        # Telemetry stayed in the database: it is not the log destination.
        with TelemetryStores.open(self.database_path) as telemetry:
            rows = telemetry.for_store(self.fixture.alpha.store).events()
        self.assertTrue(rows)
        self.assertTrue(all("duration_ms" not in row["payload"] for row in rows))

    def test_upload_rejection_and_search_keeps_operational_paths_free_of_queries(self) -> None:
        app = self.app_for()
        client = app.test_client()
        lines = self.capture_json_logs(logging.getLogger(LOGGER_NAME))
        client.post(
            "/manage/login",
            base_url=self.fixture.alpha.url_host,
            data={"csrf_token": "x", "username": "nobody", "password": "wrong"},
        )
        client.post(
            "/manage/publish",
            base_url=self.fixture.alpha.url_host,
            data={
                "csrf_token": "x",
                "price": "1.00",
                "photo": (io.BytesIO(b"not an image"), "photo.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )
        self.assertTrue(lines)
        for line in lines:
            payload = json.loads(line)
            self.assertNotIn("not an image", line)
            self.assertNotIn("photo.jpg", line)
            self.assertNotIn("price", payload)

    def test_committed_deployment_templates_hold_no_secret_or_hostname(self) -> None:
        deploy = REPOSITORY_ROOT / "deploy"
        environment_example = (deploy / "shopsearch.env.example").read_text(encoding="utf-8")
        assignments = [
            line.split("=", 1)[0].strip()
            for line in environment_example.splitlines()
            if "=" in line and not line.strip().startswith("#")
        ]
        self.assertTrue(assignments)
        for name in assignments:
            with self.subTest(variable=name):
                self.assertTrue(name.startswith("SHOPSEARCH_"))
                for forbidden in ("PASSWORD", "SECRET", "TOKEN", "CREDENTIAL", "KEY"):
                    self.assertNotIn(forbidden, name.upper())
        for label, text in (
            ("Caddyfile", (deploy / "Caddyfile").read_text(encoding="utf-8")),
            (
                "shopsearch.service",
                (deploy / "systemd" / "shopsearch.service").read_text(encoding="utf-8"),
            ),
            (
                "shopsearch-backup.timer",
                (deploy / "systemd" / "shopsearch-backup.timer").read_text(encoding="utf-8"),
            ),
        ):
            with self.subTest(file=label):
                # Comments may explain the policy with reserved example names; the
                # effective configuration must carry no literal hostname.
                effective = "\n".join(
                    line for line in text.splitlines() if not line.strip().startswith("#")
                )
                for suffix in (".com", ".org", ".net", ".io", ".dev", ".test"):
                    self.assertNotIn(suffix, effective)
                self.assertNotIn("on_demand", effective)
            with self.subTest(file=label, comment="example names are reserved"):
                self.assertNotIn("shopsearch.example", effective)


if __name__ == "__main__":
    unittest.main()
