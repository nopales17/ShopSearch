from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from apps.web.wsgi import create_pitch_app, create_pitch_server
from backend.auth.repository import MerchantRepository
from backend.auth.service import (
    LOGIN_CSRF_COOKIE,
    MERCHANT_COOKIE,
    AuthStores,
    MerchantAuth,
)
from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_DATASET_PATH, DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.sqlite_store import TelemetryStores
from contracts.catalog import CaptureTimeSource, EvidenceRef, ObservationSource
from tests.unit.test_merchant_auth import FAST_ITERATIONS
from tests.unit.test_pitch import StubEncoder

DEMO_HOST = "https://form-and-field.example"
LIVE_HOST = "https://live.example"
DEMO_PASSWORD = "demo-password"
LIVE_PASSWORD = "live-password"
CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')


class NoRedirectHandler(HTTPRedirectHandler):
    """Surface redirects as HTTPError so the redirect target is asserted directly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class MerchantShellTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.media_root = root / "media"
        development_hosts = root / "development_hosts.json"
        development_hosts.write_text(json.dumps({"127.0.0.1": "pitch-demo"}))
        with StoreRepository.open(self.database_path) as stores:
            self.demo = seed_store(stores, DEFAULT_DEMO_STORE_PATH)
            document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
            document["store_id"] = "live-store"
            document["is_demo"] = False
            document["domains"] = ["live.example"]
            live_document, domains = load_store_config_in_memory(document)
            self.live = stores.create_store(live_document, domains)
        with CatalogRepository.open(self.database_path) as catalog:
            image_store = LocalImageStore(self.media_root)
            import_pitch_dataset(catalog, image_store, DEFAULT_DEMO_DATASET_PATH, self.demo)
            self.add_live_items(catalog)
        with AuthStores.open(self.database_path, iterations=FAST_ITERATIONS) as auth_stores:
            self.demo_auth = auth_stores.for_store(self.demo)
            self.live_auth = auth_stores.for_store(self.live)
            self.demo_merchant = self.demo_auth.create_merchant("dana", DEMO_PASSWORD)
            self.live_merchant = self.live_auth.create_merchant("lee", LIVE_PASSWORD)
        self.app = create_pitch_app(
            encoder=StubEncoder(),
            database_path=self.database_path,
            media_root=self.media_root,
            development_hosts_path=development_hosts,
            storefronts={"pitch-demo", "live-store"},
        )
        self.client = self.app.test_client()

    def add_live_items(self, catalog: CatalogRepository) -> None:
        for index, item_id in enumerate(("live-001", "live-002")):
            image_sha = hashlib.sha256(item_id.encode()).hexdigest()
            catalog.create_item(
                self.live.scope,
                item_id=item_id,
                title=f"Live item {index}",
                category="Bowls",
                price=Decimal("12.00"),
                price_kind="known",
                attributes={"source_title": item_id},
                provenance=(
                    EvidenceRef(
                        ObservationSource.MANUAL,
                        f"source-{item_id}",
                        datetime(2026, 9, 1, tzinfo=timezone.utc),
                    ),
                ),
                catalog_version="live-v1",
                sort_order=index,
            )
            catalog.add_image(
                self.live.scope,
                item_id=item_id,
                sha256=image_sha,
                source_sha256=image_sha,
                media_type="image/jpeg",
                width=8,
                height=8,
                byte_size=8,
                capture_time=None,
                capture_time_source=CaptureTimeSource.UNKNOWN,
            )

    # -- helpers -------------------------------------------------------------

    def auth(self, store) -> MerchantAuth:
        stores = AuthStores.open(self.database_path, iterations=FAST_ITERATIONS)
        self.addCleanup(stores.close)
        return stores.for_store(store)

    def csrf_token(self, response) -> str:
        match = CSRF_FIELD.search(response.data)
        self.assertIsNotNone(match, "login form must carry a CSRF token")
        assert match is not None
        return match.group(1).decode()

    def login(self, host: str, username: str, password: str, client=None):
        client = client or self.client
        page = client.get("/manage/login", base_url=host)
        return client.post(
            "/manage/login",
            base_url=host,
            data={
                "csrf_token": self.csrf_token(page),
                "username": username,
                "password": password,
            },
        )

    def merchant_token(self, response) -> str:
        for header in response.headers.getlist("Set-Cookie"):
            if header.startswith(f"{MERCHANT_COOKIE}="):
                return header.split(";", 1)[0].split("=", 1)[1]
        raise AssertionError("no merchant cookie was set")

    def events(self, store) -> list[dict[str, Any]]:
        with TelemetryStores.open(self.database_path) as telemetry:
            return telemetry.for_store(store).events()

    def traffic(self, store) -> list[str]:
        return [str(entry["payload"]["traffic"]) for entry in self.events(store)]

    def client_with_merchant_cookie(self, host: str, token: str):
        """A client presenting a merchant cookie for `host`, as a browser would."""

        client = self.app.test_client()
        client.set_cookie(MERCHANT_COOKIE, token, domain=host.split("//", 1)[1])
        return client

    # -- tests ---------------------------------------------------------------

    def test_manage_without_session_redirects_and_leaks_no_item_data(self) -> None:
        response = self.client.get("/manage", base_url=DEMO_HOST)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/manage/login")
        self.assertEqual(response.data, b"")
        self.assertNotIn(b"pitch-128096", response.data)
        self.assertNotIn(b"inventory", response.data)

    def test_login_requires_a_valid_csrf_token(self) -> None:
        missing = self.client.post(
            "/manage/login",
            base_url=DEMO_HOST,
            data={"username": "dana", "password": DEMO_PASSWORD},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertNotIn(f"{MERCHANT_COOKIE}=", " ".join(missing.headers.getlist("Set-Cookie")))
        page = self.client.get("/manage/login", base_url=DEMO_HOST)
        invalid = self.client.post(
            "/manage/login",
            base_url=DEMO_HOST,
            data={
                "csrf_token": "not-the-token",
                "username": "dana",
                "password": DEMO_PASSWORD,
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertNotIn(f"{MERCHANT_COOKIE}=", invalid.headers.get("Set-Cookie") or "")
        self.assertNotEqual(self.csrf_token(page), "")
        self.assertEqual(self.client.get("/manage", base_url=DEMO_HOST).status_code, 303)

    def test_login_manage_and_logout_journey(self) -> None:
        response = self.login(DEMO_HOST, "dana", DEMO_PASSWORD)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/manage")
        cookies = response.headers.getlist("Set-Cookie")
        merchant_cookie = next(c for c in cookies if c.startswith(f"{MERCHANT_COOKIE}="))
        for attribute in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, merchant_cookie)
        self.assertNotIn("Max-Age", merchant_cookie)  # Browser-session cookie, no remember-me.
        self.assertTrue(any(c.startswith(f"{LOGIN_CSRF_COOKIE}=;") for c in cookies))

        manage = self.client.get("/manage", base_url=DEMO_HOST)
        self.assertEqual(manage.status_code, 200)
        body = manage.data.decode()
        self.assertIn("Signed in as dana", body)
        self.assertIn("pitch-128096", body)
        self.assertIn("published", body)
        self.assertIn("ready", body)
        self.assertIn("Listing state", body)
        self.assertIn("Index state", body)

        token = self.merchant_token(response)
        logout = self.client.post(
            "/manage/logout",
            base_url=DEMO_HOST,
            data={"csrf_token": self.csrf_token(manage)},
        )
        self.assertEqual(logout.status_code, 303)
        self.assertEqual(logout.headers["Location"], "/manage/login")
        self.assertEqual(self.client.get("/manage", base_url=DEMO_HOST).status_code, 303)
        # The revoked token cannot be replayed even if the cookie is presented again.
        replayed = self.client_with_merchant_cookie(DEMO_HOST, token).get(
            "/manage", base_url=DEMO_HOST
        )
        self.assertEqual(replayed.status_code, 303)
        self.assertNotIn(b"pitch-128096", replayed.data)

    def test_invalid_credentials_are_generic_for_unknown_and_wrong_password(self) -> None:
        unknown = self.login(DEMO_HOST, "nobody", "whatever-password")
        self.assertEqual(unknown.status_code, 401)
        wrong = self.login(DEMO_HOST, "dana", "wrong-password")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.data, wrong.data)
        self.assertIn(b"Invalid username or password", unknown.data)
        self.assertNotIn(f"{MERCHANT_COOKIE}=", unknown.headers.get("Set-Cookie") or "")

    def test_repeated_failures_are_throttled(self) -> None:
        for _ in range(5):
            self.assertEqual(self.login(DEMO_HOST, "dana", "wrong-password").status_code, 401)
        throttled = self.login(DEMO_HOST, "dana", DEMO_PASSWORD)
        self.assertEqual(throttled.status_code, 429)
        self.assertIn("Retry-After", throttled.headers)
        self.assertNotIn(f"{MERCHANT_COOKIE}=", throttled.headers.get("Set-Cookie") or "")

    def test_logout_requires_csrf_and_keeps_the_session_on_failure(self) -> None:
        self.login(DEMO_HOST, "dana", DEMO_PASSWORD)
        manage = self.client.get("/manage", base_url=DEMO_HOST)
        rejected = self.client.post(
            "/manage/logout", base_url=DEMO_HOST, data={"csrf_token": "wrong"}
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.client.get("/manage", base_url=DEMO_HOST).status_code, 200)
        accepted = self.client.post(
            "/manage/logout",
            base_url=DEMO_HOST,
            data={"csrf_token": self.csrf_token(manage)},
        )
        self.assertEqual(accepted.status_code, 303)

    def test_cross_store_session_is_rejected(self) -> None:
        live_login = self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        live_token = self.merchant_token(live_login)
        foreign = self.client_with_merchant_cookie(DEMO_HOST, live_token)
        response = foreign.get("/manage", base_url=DEMO_HOST)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/manage/login")
        self.assertNotIn(b"live-001", response.data)
        # The same token is valid on its own storefront hostname.
        owner = self.client_with_merchant_cookie(LIVE_HOST, live_token)
        own = owner.get("/manage", base_url=LIVE_HOST)
        self.assertEqual(own.status_code, 200)
        self.assertIn(b"live-001", own.data)

    def test_merchant_storefront_traffic_is_classified_merchant_self(self) -> None:
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/", base_url=LIVE_HOST).status_code, 200)
        self.assertEqual(set(self.traffic(self.live)), {"customer"})

        merchant_client = self.app.test_client()
        login = self.login(LIVE_HOST, "lee", LIVE_PASSWORD, client=merchant_client)
        token = self.merchant_token(login)
        self.assertEqual(merchant_client.get("/", base_url=LIVE_HOST).status_code, 200)
        self.assertIn("merchant_self", self.traffic(self.live))
        self.assertIn("customer", self.traffic(self.live))

        def merchant_self_count() -> int:
            return self.traffic(self.live).count("merchant_self")

        baseline = merchant_self_count()

        # A cookie minted on another storefront hostname creates no identity here.
        demo_client = self.app.test_client()
        demo_login = self.login(DEMO_HOST, "dana", DEMO_PASSWORD, client=demo_client)
        demo_token = self.merchant_token(demo_login)
        self.client_with_merchant_cookie(LIVE_HOST, demo_token).get("/", base_url=LIVE_HOST)
        self.assertEqual(merchant_self_count(), baseline)

        # The demo storefront keeps demo traffic for anonymous visits and classifies
        # its own merchant separately from customer traffic.
        self.app.test_client().get("/", base_url=DEMO_HOST)
        self.assertIn("pitch_demo", self.traffic(self.demo))
        demo_client.get("/", base_url=DEMO_HOST)
        self.assertIn("merchant_self", self.traffic(self.demo))

        # Revoked and disabled sessions create no identity.
        auth = self.auth(self.live)
        auth.revoke(token)
        self.client_with_merchant_cookie(LIVE_HOST, token).get("/", base_url=LIVE_HOST)
        self.assertEqual(merchant_self_count(), baseline)

        reissued = auth.start_session(self.live_merchant)
        auth.disable_merchant("lee")
        self.client_with_merchant_cookie(LIVE_HOST, reissued.token).get("/", base_url=LIVE_HOST)
        self.assertEqual(merchant_self_count(), baseline)

    def test_expired_session_cookie_creates_no_merchant_identity(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=13)
        database = platform_db.Database.open(self.database_path)
        self.addCleanup(database.close)
        past_auth = MerchantAuth(
            MerchantRepository(database),
            self.live,
            iterations=FAST_ITERATIONS,
            clock=lambda: past,
        )
        issued = past_auth.start_session(self.live_merchant)
        self.client_with_merchant_cookie(LIVE_HOST, issued.token).get("/", base_url=LIVE_HOST)
        self.assertNotIn("merchant_self", self.traffic(self.live))

    def test_secrets_never_appear_in_responses(self) -> None:
        visitor = self.app.test_client()
        bodies = [visitor.get("/manage/login", base_url=DEMO_HOST).data]
        login = self.login(DEMO_HOST, "dana", DEMO_PASSWORD, client=visitor)
        bodies.append(login.data)
        raw_token = self.merchant_token(login)
        manage = visitor.get("/manage", base_url=DEMO_HOST)
        bodies.append(manage.data)
        bodies.append(visitor.post("/manage/logout", base_url=DEMO_HOST, data={}).data)
        fresh = self.app.test_client()
        bodies.append(self.login(DEMO_HOST, "dana", "wrong-password", client=fresh).data)
        with AuthStores.open(self.database_path, iterations=FAST_ITERATIONS) as auth_stores:
            record = auth_stores.for_store(self.demo).list_merchants()[0]
        connection = platform_db.connect(self.database_path)
        try:
            row = connection.execute(
                "SELECT password_salt, password_hash FROM merchants WHERE store_id = ? "
                "AND merchant_id = ?",
                (self.demo.store_id, record.merchant_id),
            ).fetchone()
        finally:
            connection.close()
        secrets = {
            raw_token,
            bytes(row["password_salt"]).hex(),
            bytes(row["password_hash"]).hex(),
        }
        for body in bodies:
            text = body.decode("utf-8", "replace")
            for secret in secrets:
                with self.subTest(secret=secret[:8]):
                    self.assertNotIn(secret, text)

    def test_manage_redirects_over_real_loopback_http(self) -> None:
        server = create_pitch_server(
            port=0,
            encoder=StubEncoder(),
            database_path=self.database_path,
            media_root=self.media_root,
            development_hosts_path=Path(self.directory.name) / "development_hosts.json",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/manage"
        try:
            opener = build_opener(NoRedirectHandler)
            with self.assertRaises(HTTPError) as caught:
                opener.open(Request(url), timeout=5)
            self.assertEqual(caught.exception.code, 303)
            self.assertEqual(caught.exception.headers["Location"], "/manage/login")
            self.assertEqual(caught.exception.read(), b"")
            caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_demo_store_item_pages_are_read_only(self) -> None:
        visitor = self.app.test_client()
        login = self.login(DEMO_HOST, "dana", DEMO_PASSWORD, client=visitor)
        self.assertEqual(login.status_code, 303)
        manage = visitor.get("/manage", base_url=DEMO_HOST)
        self.assertNotIn(b"/manage/items/", manage.data, "demo stores expose no edit links")
        csrf = self.csrf_token(manage)
        with CatalogRepository.open(self.database_path) as catalog:
            scope = self.demo.scope
            before = (
                catalog.item_count(scope),
                catalog.image_count(scope),
                catalog.event_count(scope),
                catalog.generations(scope).catalog,
            )
        page = visitor.get("/manage/items/pitch-128096", base_url=DEMO_HOST)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"illustrative demo", page.data)
        self.assertNotIn(b'name="price"', page.data)
        for suffix, data in (
            ("edit", {"title": "x", "category": "", "price": "1.00"}),
            ("listing", {"action": "hide"}),
        ):
            with self.subTest(action=suffix):
                response = visitor.post(
                    f"/manage/items/pitch-128096/{suffix}",
                    base_url=DEMO_HOST,
                    data={"csrf_token": csrf, **data},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(b"illustrative demo", response.data)
        with CatalogRepository.open(self.database_path) as catalog:
            scope = self.demo.scope
            after = (
                catalog.item_count(scope),
                catalog.image_count(scope),
                catalog.event_count(scope),
                catalog.generations(scope).catalog,
            )
        self.assertEqual(after, before)
