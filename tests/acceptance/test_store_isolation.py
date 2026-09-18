"""S9 adversarial two-store isolation suite.

One application process serves two explicitly provisioned synthetic stores. Every
assertion here deliberately crosses a boundary: item IDs, merchant usernames and
source image bytes overlap between the stores, so isolation has to come from
`StoreScope` and the schema rather than from unique fixture values.

The fixture is generated test data (see `tests.support.isolation_fixture`); it is not
Cloud City, not a prospective Customer Zero store and not merchant or customer evidence.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote_plus
from urllib.request import Request, build_opener

from apps.web.wsgi import create_pitch_app, create_pitch_server
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import MERCHANT_COOKIE
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import DISPLAY_VARIANT
from backend.search.vector_source import VectorCache
from backend.telemetry.report import summarize_store
from backend.telemetry.sqlite_store import TelemetryStores
from contracts.catalog import ListingState
from contracts.telemetry import EventType
from tests.acceptance.test_merchant_publish import jpeg_bytes
from tests.support.isolation_fixture import (
    ALPHA_ONLY_ITEM_ID,
    ALPHA_STORE_ID,
    BETA_ONLY_ITEM_ID,
    BETA_STORE_ID,
    SHARED_ITEM_ID,
    SHARED_ITEM_ID_2,
    SHARED_USERNAME,
    UNPROVISIONED_HOST,
    FixtureStore,
    IsolationFixture,
    display_sha256,
    fixture_document_text,
    provision_isolation_stores,
)
from tests.unit.test_pitch import StubEncoder
from tests.unit.test_pitch_import import CONTROL_QUERIES, EVALUATION_PATH
from tests.unit.test_telemetry_sink import SESSION, make_event

CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')
ITEM_LINK = re.compile(r"/items/([A-Za-z0-9_-]{1,100})\?")
MEDIA_URL = re.compile(r"/media/([A-Za-z0-9_-]{1,100})/([0-9a-f]{64})/display")
DEMO_WORDING = ("cleveland", "museum", "cc0", "form & field", "illustrative")


class StoreIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.media_root = root / "media"
        self.fixture: IsolationFixture = provision_isolation_stores(
            self.database_path, self.media_root
        )
        # An empty development host map: each request's Host must resolve through the
        # registry alone, with no localhost shortcut.
        self.development_hosts = root / "development_hosts.json"
        self.development_hosts.write_text("{}")
        self.app = create_pitch_app(
            encoder=StubEncoder(),
            database_path=self.database_path,
            media_root=self.media_root,
            development_hosts_path=self.development_hosts,
            storefronts=self.fixture.storefronts,
        )
        self.alpha_client = self.app.test_client()
        self.beta_client = self.app.test_client()

    # -- helpers -------------------------------------------------------------

    def client(self, side: FixtureStore):
        return self.alpha_client if side is self.fixture.alpha else self.beta_client

    def get(self, side: FixtureStore, path: str, client=None):
        return (client or self.client(side)).get(path, base_url=side.url_host)

    def csrf_token(self, response) -> str:
        match = CSRF_FIELD.search(response.data)
        self.assertIsNotNone(match, "page must carry a CSRF token")
        assert match is not None
        return match.group(1).decode()

    def login(self, side: FixtureStore, password: str | None = None, client=None):
        client = client or self.client(side)
        page = client.get("/manage/login", base_url=side.url_host)
        return client.post(
            "/manage/login",
            base_url=side.url_host,
            data={
                "csrf_token": self.csrf_token(page),
                "username": SHARED_USERNAME,
                "password": password or side.password,
            },
        )

    def merchant_token(self, response) -> str:
        for header in response.headers.getlist("Set-Cookie"):
            if header.startswith(f"{MERCHANT_COOKIE}="):
                return header.split(";", 1)[0].split("=", 1)[1]
        raise AssertionError("no merchant cookie was set")

    def client_with_merchant_cookie(self, side: FixtureStore, token: str):
        client = self.app.test_client()
        client.set_cookie(MERCHANT_COOKIE, token, domain=side.host)
        return client

    def search(self, side: FixtureStore, query: str, *, category: str = "", client=None):
        path = f"/api/search?q={quote_plus(query)}"
        if category:
            path += f"&category={quote_plus(category)}"
        return self.get(side, path, client=client)

    def search_payload(self, side: FixtureStore, query: str, *, category: str = "") -> dict:
        response = self.search(side, query, category=category)
        self.assertEqual(response.status_code, 200, response.data[:200])
        return json.loads(response.data)

    def returned_item_ids(self, html: str) -> set[str]:
        return set(ITEM_LINK.findall(html))

    def counts(self, side: FixtureStore) -> tuple[int, int, int, int]:
        with CatalogRepository.open(self.database_path) as catalog:
            scope = side.store.scope
            return (
                catalog.item_count(scope),
                catalog.image_count(scope),
                catalog.event_count(scope),
                catalog.generations(scope).catalog,
            )

    def state(self, side: FixtureStore, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.item_state(side.store.scope, item_id)

    def media_status(self, side: FixtureStore, store_id: str, sha256: str) -> int:
        return self.get(side, f"/media/{store_id}/{sha256}/{DISPLAY_VARIANT}").status_code

    def both_counts(self) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        return self.counts(self.fixture.alpha), self.counts(self.fixture.beta)

    def frozen_queries(self) -> list[str]:
        cases = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))["queries"]
        return [case["query"] for case in cases] + CONTROL_QUERIES

    def publish(
        self,
        side: FixtureStore,
        *,
        photo: bytes | None = None,
        price: str = "9.99",
        title: str = "Alpha published fixture object",
        category: str | None = None,
        csrf: str | None = None,
        client=None,
    ):
        client = client or self.client(side)
        page = client.get("/manage", base_url=side.url_host)
        return client.post(
            "/manage/publish",
            base_url=side.url_host,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "price": price,
                "title": title,
                "category": category if category is not None else side.objects[0].category,
                "photo": (io.BytesIO(photo or jpeg_bytes()), "photo.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )

    def edit(
        self,
        side: FixtureStore,
        item_id: str,
        *,
        price: str,
        title: str | None = None,
        category: str | None = None,
        csrf: str | None = None,
        client=None,
    ):
        client = client or self.client(side)
        page = client.get(f"/manage/items/{item_id}", base_url=side.url_host)
        fixture_object = side.object(item_id) if item_id in side.item_ids else None
        return client.post(
            f"/manage/items/{item_id}/edit",
            base_url=side.url_host,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "title": title
                if title is not None
                else (fixture_object.title if fixture_object else ""),
                "category": (
                    category
                    if category is not None
                    else (fixture_object.category if fixture_object else "")
                ),
                "price": price,
            },
        )

    def listing(
        self, side: FixtureStore, item_id: str, action: str, *, csrf: str | None = None, client=None
    ):
        client = client or self.client(side)
        page = client.get(f"/manage/items/{item_id}", base_url=side.url_host)
        return client.post(
            f"/manage/items/{item_id}/listing",
            base_url=side.url_host,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "action": action,
            },
        )

    def replace(
        self,
        side: FixtureStore,
        item_id: str,
        photo: bytes | None = None,
        *,
        csrf: str | None = None,
        client=None,
    ):
        client = client or self.client(side)
        page = client.get(f"/manage/items/{item_id}", base_url=side.url_host)
        return client.post(
            f"/manage/items/{item_id}/replace",
            base_url=side.url_host,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "photo": (
                    io.BytesIO(photo or jpeg_bytes(size=(70, 50))),
                    "photo.jpg",
                    "image/jpeg",
                ),
            },
            content_type="multipart/form-data",
        )

    # -- composition ---------------------------------------------------------

    def test_one_process_serves_both_hostnames_concurrently(self) -> None:
        for side in self.fixture.stores:
            with self.subTest(host=side.host):
                home = self.get(side, "/")
                self.assertEqual(home.status_code, 200)
                catalog = self.get(side, "/catalog")
                self.assertEqual(catalog.status_code, 200)
                self.assertIn(side.store.display_name.encode(), catalog.data)
                for fixture_object in side.objects:
                    self.assertIn(fixture_object.title.encode(), catalog.data)
        # Each hostname renders only its own branding and items.
        alpha_catalog = self.get(self.fixture.alpha, "/catalog").data.decode()
        beta_catalog = self.get(self.fixture.beta, "/catalog").data.decode()
        self.assertIn("ALPHA", alpha_catalog)
        self.assertNotIn("BETA", alpha_catalog)
        self.assertIn("BETA", beta_catalog)
        self.assertNotIn("ALPHA", beta_catalog)
        for title in ("Beta shared fixture object", "Beta only fixture object"):
            self.assertNotIn(title, alpha_catalog)
        for title in ("Alpha shared fixture object", "Alpha only fixture object"):
            self.assertNotIn(title, beta_catalog)

    def test_two_hostnames_are_served_by_one_loopback_process(self) -> None:
        server = create_pitch_server(
            port=0,
            encoder=StubEncoder(),
            database_path=self.database_path,
            media_root=self.media_root,
            development_hosts_path=self.development_hosts,
            storefronts=self.fixture.storefronts,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def fetch(path: str, host: str) -> tuple[int, bytes]:
            request = Request(base + path, headers={"Host": host})
            try:
                with build_opener().open(request, timeout=5) as response:
                    return response.status, response.read()
            except HTTPError as error:
                body = error.read()
                error.close()
                return error.code, body

        try:
            alpha_status, alpha_body = fetch("/catalog", self.fixture.alpha.host)
            beta_status, beta_body = fetch("/catalog", self.fixture.beta.host)
            self.assertEqual((alpha_status, beta_status), (200, 200))
            self.assertIn(b"ALPHA", alpha_body)
            self.assertNotIn(b"BETA", alpha_body)
            self.assertIn(b"BETA", beta_body)
            self.assertNotIn(b"ALPHA", beta_body)
            # A store's media address never resolves through the other hostname.
            with CatalogRepository.open(self.database_path) as catalog:
                alpha_image = catalog.current_image(
                    self.fixture.alpha.store.scope, ALPHA_ONLY_ITEM_ID
                )
            assert alpha_image is not None
            path = f"/media/{ALPHA_STORE_ID}/{alpha_image.sha256}/{DISPLAY_VARIANT}"
            self.assertEqual(fetch(path, self.fixture.alpha.host)[0], 200)
            self.assertEqual(fetch(path, self.fixture.beta.host)[0], 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unknown_and_unprovisioned_hosts_leak_no_store_identity(self) -> None:
        for host in ("unknown.isolation.test", UNPROVISIONED_HOST, "form-and-field.example"):
            for path in ("/", "/catalog", "/manage", f"/items/{SHARED_ITEM_ID}"):
                with self.subTest(host=host, path=path):
                    response = self.alpha_client.get(path, base_url=f"https://{host}")
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.data, b"Not found")
                    self.assertIsNone(response.headers.get("Set-Cookie"))
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_fixture_is_synthetic_test_data_not_demo_or_store_evidence(self) -> None:
        document = fixture_document_text().lower()
        for token in DEMO_WORDING:
            with self.subTest(token=token):
                self.assertNotIn(token, document)
        self.assertIn("fixture", document)
        self.assertIn("not a real store", document)
        # One username, two stores, two identities: reuse is deliberate.
        self.assertEqual(self.fixture.alpha.merchant.username, SHARED_USERNAME)
        self.assertEqual(self.fixture.beta.merchant.username, SHARED_USERNAME)
        self.assertNotEqual(
            self.fixture.alpha.merchant.merchant_id, self.fixture.beta.merchant.merchant_id
        )
        rendered = self.get(self.fixture.alpha, "/catalog").data.decode().lower()
        self.assertIn("fixture", rendered)
        self.assertIn(self.fixture.alpha.store.display_name.lower(), rendered)
        self.assertNotIn(self.fixture.beta.store.display_name.lower(), rendered)

    # -- catalog and detail --------------------------------------------------

    def test_catalog_and_detail_are_scoped_by_store(self) -> None:
        alpha_only = self.get(self.fixture.alpha, f"/items/{ALPHA_ONLY_ITEM_ID}")
        self.assertEqual(alpha_only.status_code, 200)
        self.assertIn(b"Alpha only fixture object", alpha_only.data)
        self.assertEqual(
            self.get(self.fixture.beta, f"/items/{ALPHA_ONLY_ITEM_ID}").status_code, 404
        )

        beta_only = self.get(self.fixture.beta, f"/items/{BETA_ONLY_ITEM_ID}")
        self.assertEqual(beta_only.status_code, 200)
        self.assertIn(b"Beta only fixture object", beta_only.data)
        self.assertEqual(
            self.get(self.fixture.alpha, f"/items/{BETA_ONLY_ITEM_ID}").status_code, 404
        )

        # Deliberately shared item IDs resolve to the resolved store's own record.
        for item_id in (SHARED_ITEM_ID, SHARED_ITEM_ID_2):
            for side, other in (
                (self.fixture.alpha, self.fixture.beta),
                (self.fixture.beta, self.fixture.alpha),
            ):
                with self.subTest(store=side.store.store_id, item_id=item_id):
                    response = self.get(side, f"/items/{item_id}")
                    self.assertEqual(response.status_code, 200)
                    body = response.data.decode()
                    self.assertIn(side.object(item_id).title, body)
                    self.assertNotIn(other.object(item_id).title, body)

        self.assertEqual(self.get(self.fixture.alpha, "/items/no-such-item").status_code, 404)

    def test_browse_listings_never_show_the_other_stores_records(self) -> None:
        for side, other in (
            (self.fixture.alpha, self.fixture.beta),
            (self.fixture.beta, self.fixture.alpha),
        ):
            with self.subTest(store=side.store.store_id):
                body = self.get(side, "/catalog").data.decode()
                self.assertEqual(self.returned_item_ids(body), set(side.item_ids))
                for fixture_object in other.objects:
                    self.assertNotIn(fixture_object.title, body)
                self.assertIn(f"${side.object(SHARED_ITEM_ID).price:.0f}", body)
        # A category filter is computed over the resolved store's catalog only.
        self.assertEqual(
            self.search(
                self.fixture.alpha, "", category=self.fixture.beta.objects[0].category
            ).status_code,
            400,
        )
        self.assertEqual(
            self.search(
                self.fixture.beta, "", category=self.fixture.alpha.objects[0].category
            ).status_code,
            400,
        )

    # -- media ---------------------------------------------------------------

    def test_media_addresses_are_store_scoped(self) -> None:
        with CatalogRepository.open(self.database_path) as catalog:
            alpha_only = catalog.current_image(self.fixture.alpha.store.scope, ALPHA_ONLY_ITEM_ID)
            beta_only = catalog.current_image(self.fixture.beta.store.scope, BETA_ONLY_ITEM_ID)
            alpha_shared = catalog.current_image(self.fixture.alpha.store.scope, SHARED_ITEM_ID)
            beta_shared = catalog.current_image(self.fixture.beta.store.scope, SHARED_ITEM_ID)
        assert alpha_only and beta_only and alpha_shared and beta_shared
        # The same source bytes are one identical address in two stores.
        self.assertEqual(alpha_shared.sha256, beta_shared.sha256)
        self.assertEqual(alpha_shared.source_sha256, beta_shared.source_sha256)
        blobs = self.fixture.image_store()
        self.assertTrue(
            blobs.exists(self.fixture.alpha.store.scope, alpha_shared.sha256, DISPLAY_VARIANT)
        )
        self.assertTrue(
            blobs.exists(self.fixture.beta.store.scope, beta_shared.sha256, DISPLAY_VARIANT)
        )

        self.assertEqual(
            self.media_status(self.fixture.alpha, ALPHA_STORE_ID, alpha_only.sha256), 200
        )
        self.assertEqual(self.media_status(self.fixture.beta, BETA_STORE_ID, beta_only.sha256), 200)
        # A foreign store id in the path never resolves.
        self.assertEqual(
            self.media_status(self.fixture.beta, ALPHA_STORE_ID, alpha_only.sha256), 404
        )
        # A foreign hash under the resolved store never resolves.
        self.assertEqual(
            self.media_status(self.fixture.beta, BETA_STORE_ID, alpha_only.sha256), 404
        )
        self.assertEqual(
            self.media_status(self.fixture.alpha, ALPHA_STORE_ID, beta_only.sha256), 404
        )
        # Unless the resolved store independently owns that very address.
        self.assertEqual(
            self.media_status(self.fixture.beta, BETA_STORE_ID, beta_shared.sha256), 200
        )
        self.assertEqual(
            self.get(self.fixture.beta, f"/images/{ALPHA_ONLY_ITEM_ID}.jpg").status_code, 404
        )
        self.assertEqual(
            self.get(self.fixture.alpha, f"/images/{ALPHA_ONLY_ITEM_ID}.jpg").status_code, 200
        )

    def test_hidden_items_keep_their_bytes_without_exposing_them(self) -> None:
        with CatalogRepository.open(self.database_path) as catalog:
            alpha_shared = catalog.current_image(self.fixture.alpha.store.scope, SHARED_ITEM_ID)
        assert alpha_shared is not None
        for target in (ListingState.HIDDEN, ListingState.SOLD):
            with self.subTest(target=target):
                with CatalogRepository.open(self.database_path) as catalog:
                    catalog.transition_listing_state(
                        self.fixture.alpha.store.scope,
                        item_id=SHARED_ITEM_ID,
                        target=target,
                        actor=self.fixture.alpha.merchant.merchant_id,
                    )
                    # Internal lookup spans listing states and stays store-scoped.
                    self.assertIsNotNone(
                        catalog.current_image(self.fixture.alpha.store.scope, SHARED_ITEM_ID)
                    )
                    self.assertIsNone(
                        catalog.current_image(self.fixture.beta.store.scope, ALPHA_ONLY_ITEM_ID)
                    )
                self.assertEqual(
                    self.media_status(self.fixture.alpha, ALPHA_STORE_ID, alpha_shared.sha256),
                    404,
                )
                self.assertEqual(
                    self.get(self.fixture.alpha, f"/items/{SHARED_ITEM_ID}").status_code, 404
                )
                body = self.get(self.fixture.alpha, "/catalog").data.decode()
                self.assertNotIn(SHARED_ITEM_ID, self.returned_item_ids(body))
                # The other store owns the same address independently and still serves it.
                self.assertEqual(
                    self.media_status(self.fixture.beta, BETA_STORE_ID, alpha_shared.sha256), 200
                )
                self.assertEqual(
                    self.get(self.fixture.beta, f"/items/{SHARED_ITEM_ID}").status_code, 200
                )
                with CatalogRepository.open(self.database_path) as catalog:
                    catalog.transition_listing_state(
                        self.fixture.alpha.store.scope,
                        item_id=SHARED_ITEM_ID,
                        target=ListingState.PUBLISHED,
                        actor=self.fixture.alpha.merchant.merchant_id,
                    )

    # -- search --------------------------------------------------------------

    def test_frozen_queries_never_return_another_stores_items(self) -> None:
        queries = self.frozen_queries()
        self.assertGreaterEqual(len(queries), 15)
        for side, other in (
            (self.fixture.alpha, self.fixture.beta),
            (self.fixture.beta, self.fixture.alpha),
        ):
            for query in queries:
                with self.subTest(store=side.store.store_id, query=query):
                    payload = self.search_payload(side, query)
                    returned = self.returned_item_ids(str(payload["html"]))
                    self.assertTrue(
                        returned <= set(side.item_ids), f"{returned} not within {side.item_ids}"
                    )
                    coverage = payload["coverage"]
                    self.assertEqual(coverage["published"], len(side.objects))
                    self.assertEqual(coverage["ready"], len(side.objects))
                    self.assertEqual(coverage["excluded_unindexed"], 0)
                    if returned:
                        media_stores = {
                            match[0] for match in MEDIA_URL.findall(str(payload["html"]))
                        }
                        self.assertEqual(media_stores, {side.store.store_id})
                    # Each returned record belongs to the resolved store: the same ID on
                    # the other hostname returns that store's own record, never this one.
                    for item_id in returned:
                        own = self.get(side, f"/items/{item_id}")
                        self.assertEqual(own.status_code, 200)
                        self.assertIn(side.object(item_id).title, own.data.decode())
                        foreign = self.get(other, f"/items/{item_id}")
                        if item_id in other.item_ids:
                            self.assertEqual(foreign.status_code, 200)
                            self.assertIn(other.object(item_id).title, foreign.data.decode())
                        else:
                            self.assertEqual(foreign.status_code, 404)
        # Deliberately overlapping IDs: each hostname renders its own record content.
        for side, other in (
            (self.fixture.alpha, self.fixture.beta),
            (self.fixture.beta, self.fixture.alpha),
        ):
            # The whole seeded set behaves like any other query.
            seeded_queries = [candidate.title for candidate in side.objects]
            for query in seeded_queries:
                with self.subTest(store=side.store.store_id, seeded=query):
                    payload = self.search_payload(side, query)
                    seeded_returned = self.returned_item_ids(str(payload["html"]))
                    self.assertTrue(seeded_returned <= set(side.item_ids))
            for item_id in (SHARED_ITEM_ID, SHARED_ITEM_ID_2):
                with self.subTest(store=side.store.store_id, item_id=item_id):
                    payload = self.search_payload(side, "shared fixture object")
                    html = str(payload["html"])
                    self.assertIn(item_id, self.returned_item_ids(html))
                    self.assertIn(side.object(item_id).title, html)
                    self.assertNotIn(other.object(item_id).title, html)

    def test_generations_and_vector_caches_are_independent_per_store(self) -> None:
        catalog = CatalogRepository.open(self.database_path)
        self.addCleanup(catalog.close)
        cache = VectorCache(catalog, model_id=MODEL_ID, model_revision=MODEL_REVISION)
        alpha_before = cache.snapshot(self.fixture.alpha.store.scope)
        beta_before = cache.snapshot(self.fixture.beta.store.scope)
        self.assertNotEqual(
            alpha_before.vector_for(SHARED_ITEM_ID), beta_before.vector_for(SHARED_ITEM_ID)
        )
        self.assertEqual(alpha_before.catalog_generation, 6)
        self.assertEqual(beta_before.catalog_generation, 6)
        beta_catalog_before = self.returned_item_ids(
            self.get(self.fixture.beta, "/catalog").data.decode()
        )
        beta_search_before = self.search_payload(self.fixture.beta, "shared fixture object")

        # Change only store A: publish, then amend, then hide and unhide.
        self.assertEqual(self.login(self.fixture.alpha).status_code, 303)
        published = self.publish(self.fixture.alpha)
        self.assertEqual(published.status_code, 303)
        new_item_id = published.headers["Location"].split("published=", 1)[1].split("&", 1)[0]
        self.assertEqual(
            self.edit(
                self.fixture.alpha, new_item_id, price="5.00", title="Alpha amended"
            ).status_code,
            303,
        )
        self.assertEqual(self.listing(self.fixture.alpha, new_item_id, "hide").status_code, 303)
        self.assertEqual(self.listing(self.fixture.alpha, new_item_id, "unhide").status_code, 303)

        alpha_after = cache.snapshot(self.fixture.alpha.store.scope)
        beta_after = cache.snapshot(self.fixture.beta.store.scope)
        self.assertEqual(alpha_after.catalog_generation, alpha_before.catalog_generation + 4)
        self.assertEqual(beta_after.catalog_generation, beta_before.catalog_generation)
        self.assertEqual(beta_after.index_generation, beta_before.index_generation)
        self.assertIs(beta_after, beta_before, "store B's snapshot must not be rebuilt")
        self.assertEqual(
            beta_after.vector_for(SHARED_ITEM_ID), beta_before.vector_for(SHARED_ITEM_ID)
        )
        self.assertNotEqual(alpha_after.catalog_generation, beta_after.catalog_generation)

        # The index counter is independent too: a store A embedding write bumps only
        # store A's index generation and leaves store B's cached snapshot untouched.
        with CatalogRepository.open(self.database_path) as catalog:
            new_image = catalog.current_image(self.fixture.alpha.store.scope, new_item_id)
            assert new_image is not None
            catalog.put_ready_embedding(
                self.fixture.alpha.store.scope,
                item_id=new_item_id,
                vector=tuple(1.0 if position == 20 else 0.0 for position in range(512)),
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
                image_sha256=new_image.sha256,
            )
            alpha_indexed = catalog.generations(self.fixture.alpha.store.scope)
            beta_indexed = catalog.generations(self.fixture.beta.store.scope)
        self.assertEqual(alpha_indexed.index, alpha_after.index_generation + 1)
        self.assertEqual(beta_indexed.index, beta_before.index_generation)
        self.assertEqual(cache.snapshot(self.fixture.beta.store.scope), beta_after)
        self.assertIs(cache.snapshot(self.fixture.beta.store.scope), beta_after)
        self.assertEqual(
            self.returned_item_ids(self.get(self.fixture.beta, "/catalog").data.decode()),
            beta_catalog_before,
        )
        beta_search_after = self.search_payload(self.fixture.beta, "shared fixture object")
        for field in ("count", "coverage", "coverage_html"):
            with self.subTest(field=field):
                self.assertEqual(beta_search_after[field], beta_search_before[field])
        # Only the per-request search_id differs inside the rendered cards.
        self.assertEqual(
            self.returned_item_ids(str(beta_search_after["html"])),
            self.returned_item_ids(str(beta_search_before["html"])),
        )
        self.assertEqual(self.counts(self.fixture.alpha)[0], len(self.fixture.alpha.objects) + 1)

    # -- merchant sessions and CSRF ------------------------------------------

    def test_a_store_session_never_authorizes_another_store(self) -> None:
        login = self.login(self.fixture.alpha)
        self.assertEqual(login.status_code, 303)
        alpha_token = self.merchant_token(login)
        alpha_before = self.counts(self.fixture.alpha)
        beta_before = self.counts(self.fixture.beta)

        foreign = self.client_with_merchant_cookie(self.fixture.beta, alpha_token)
        manage = foreign.get("/manage", base_url=self.fixture.beta.url_host)
        self.assertEqual(manage.status_code, 303)
        self.assertEqual(manage.headers["Location"], "/manage/login")
        self.assertEqual(manage.data, b"")

        # Every store B mutation route ignores the foreign session and mutates nothing.
        attempts = (
            self.edit(
                self.fixture.beta, SHARED_ITEM_ID, price="1.00", csrf="foreign", client=foreign
            ),
            self.listing(self.fixture.beta, SHARED_ITEM_ID, "hide", csrf="foreign", client=foreign),
            self.replace(self.fixture.beta, SHARED_ITEM_ID, csrf="foreign", client=foreign),
            self.publish(
                self.fixture.beta, photo=jpeg_bytes(size=(52, 52)), csrf="foreign", client=foreign
            ),
        )
        for response in attempts:
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["Location"], "/manage/login")
            self.assertNotIn(b"Beta shared fixture object", response.data)
        self.assertEqual(self.counts(self.fixture.alpha), alpha_before)
        self.assertEqual(self.counts(self.fixture.beta), beta_before)
        state = self.state(self.fixture.beta, SHARED_ITEM_ID)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)

        # The same username exists in both stores with its own credentials.
        self.assertEqual(
            self.login(
                self.fixture.beta, self.fixture.alpha.password, client=self.app.test_client()
            ).status_code,
            401,
        )
        self.assertEqual(
            self.login(
                self.fixture.alpha, self.fixture.beta.password, client=self.app.test_client()
            ).status_code,
            401,
        )
        self.assertNotEqual(
            self.fixture.alpha.merchant.merchant_id, self.fixture.beta.merchant.merchant_id
        )

        # CSRF tokens are per session and per store.
        alpha_page = self.get(self.fixture.alpha, "/manage")
        alpha_csrf = self.csrf_token(alpha_page)
        beta_login = self.login(self.fixture.beta)
        self.assertEqual(beta_login.status_code, 303)
        beta_client = self.client_with_merchant_cookie(
            self.fixture.beta, self.merchant_token(beta_login)
        )
        rejected = self.edit(
            self.fixture.beta, SHARED_ITEM_ID, price="1.00", csrf=alpha_csrf, client=beta_client
        )
        self.assertEqual(rejected.status_code, 400)
        # Store A's token presented with store A's cookie on store B's host: no identity.
        foreign_client = self.client_with_merchant_cookie(self.fixture.beta, alpha_token)
        foreign_post = foreign_client.post(
            f"/manage/items/{SHARED_ITEM_ID}/listing",
            base_url=self.fixture.beta.url_host,
            data={"csrf_token": alpha_csrf, "action": "hide"},
        )
        self.assertEqual(foreign_post.status_code, 303)
        self.assertEqual(foreign_post.headers["Location"], "/manage/login")
        self.assertEqual(self.counts(self.fixture.beta), beta_before)
        unchanged = self.state(self.fixture.beta, SHARED_ITEM_ID)
        assert unchanged is not None
        self.assertIs(unchanged.listing_state, ListingState.PUBLISHED)
        self.assertIs(
            self.state(self.fixture.alpha, SHARED_ITEM_ID).listing_state,
            ListingState.PUBLISHED,  # type: ignore[union-attr]
        )

    def test_merchant_self_classification_is_per_store(self) -> None:
        anonymous = self.app.test_client()
        self.assertEqual(
            anonymous.get("/catalog", base_url=self.fixture.alpha.url_host).status_code, 200
        )
        self.assertEqual(
            anonymous.get("/catalog", base_url=self.fixture.beta.url_host).status_code, 200
        )
        with TelemetryStores.open(self.database_path) as telemetry:
            alpha_traffic = {
                str(e["payload"]["traffic"])
                for e in telemetry.for_store(self.fixture.alpha.store).events()
            }
            beta_traffic = {
                str(e["payload"]["traffic"])
                for e in telemetry.for_store(self.fixture.beta.store).events()
            }
        self.assertEqual(alpha_traffic, {"customer"})
        self.assertEqual(beta_traffic, {"customer"})

        login = self.login(self.fixture.alpha)
        merchant_client = self.client_with_merchant_cookie(
            self.fixture.alpha, self.merchant_token(login)
        )
        self.assertEqual(
            merchant_client.get("/catalog", base_url=self.fixture.alpha.url_host).status_code, 200
        )
        with TelemetryStores.open(self.database_path) as telemetry:
            alpha_sink = telemetry.for_store(self.fixture.alpha.store)
            beta_sink = telemetry.for_store(self.fixture.beta.store)
            alpha_events = alpha_sink.events()
            alpha_report = summarize_store(alpha_sink, self.fixture.alpha.store.store_id)
            beta_report = summarize_store(beta_sink, self.fixture.beta.store.store_id)
        merchant_self = [
            entry for entry in alpha_events if str(entry["payload"]["traffic"]) == "merchant_self"
        ]
        self.assertTrue(merchant_self, "the authenticated merchant's own browse is merchant_self")
        self.assertEqual({entry["store_id"] for entry in merchant_self}, {ALPHA_STORE_ID})
        self.assertEqual(alpha_report["merchant_self_events"], len(merchant_self))
        self.assertEqual(beta_report["merchant_self_events"], 0)
        self.assertNotIn("merchant_self", beta_report["traffic"])  # type: ignore[operator]
        self.assertEqual(beta_report["traffic"], {"customer": beta_report["recorded_events"]})
        self.assertEqual(alpha_report["customer"]["counts"]["catalog_opens"], 1)  # type: ignore[index]

    # -- telemetry -----------------------------------------------------------

    def test_telemetry_rows_and_reports_never_cross_stores(self) -> None:
        for side in self.fixture.stores:
            self.assertEqual(self.search_payload(side, "shared fixture object")["count"], 3)
        with TelemetryStores.open(self.database_path) as telemetry:
            alpha_sink = telemetry.for_store(self.fixture.alpha.store)
            beta_sink = telemetry.for_store(self.fixture.beta.store)
            alpha_events = alpha_sink.events()
            beta_events = beta_sink.events()
            self.assertTrue(alpha_events and beta_events)
            self.assertEqual({e["store_id"] for e in alpha_events}, {ALPHA_STORE_ID})
            self.assertEqual({e["store_id"] for e in beta_events}, {BETA_STORE_ID})
            self.assertEqual(
                {e["event_id"] for e in alpha_events} & {e["event_id"] for e in beta_events},
                set(),
            )
            # Store B rows never carry store A's item IDs, and vice versa.
            beta_text = json.dumps(beta_events)
            alpha_text = json.dumps(alpha_events)
            self.assertNotIn(ALPHA_ONLY_ITEM_ID, beta_text)
            self.assertNotIn(BETA_ONLY_ITEM_ID, alpha_text)
            self.assertIn(ALPHA_ONLY_ITEM_ID, alpha_text)
            self.assertIn(BETA_ONLY_ITEM_ID, beta_text)
            # Store A's own search rows list only store A's returned items.
            returned = [
                entry
                for entry in alpha_events
                if entry["event_type"] == EventType.SEARCH_RESULTS_RETURNED.value
            ]
            for entry in returned:
                listed = {result["item_id"] for result in entry["payload"]["results"]}  # type: ignore[index]
                self.assertTrue(listed <= set(self.fixture.alpha.item_ids))

            # Direct adversarial writes through store B's sink.
            with self.assertRaisesRegex(ValueError, "store scope mismatch"):
                beta_sink.append(
                    make_event(
                        EventType.SESSION_STARTED, store_id=ALPHA_STORE_ID, traffic="customer"
                    )
                )
            with self.assertRaisesRegex(ValueError, "attribution"):
                beta_sink.append(
                    make_event(
                        EventType.ITEM_OPENED,
                        store_id=BETA_STORE_ID,
                        traffic="customer",
                        search_id="33333333-3333-4333-8333-333333333333",
                        session_id=SESSION,
                        payload={
                            "catalog_version": self.fixture.alpha.catalog_version,
                            "item_id": ALPHA_ONLY_ITEM_ID,
                        },
                    )
                )

            alpha_report = summarize_store(alpha_sink, ALPHA_STORE_ID)
            beta_report = summarize_store(beta_sink, BETA_STORE_ID)
        self.assertEqual(alpha_report["recorded_events"], len(alpha_events))
        self.assertEqual(beta_report["recorded_events"], len(beta_events))
        self.assertEqual(alpha_report["store_id"], ALPHA_STORE_ID)
        self.assertEqual(beta_report["store_id"], BETA_STORE_ID)
        self.assertEqual(alpha_report["traffic"], {"customer": len(alpha_events)})  # type: ignore[arg-type]
        self.assertEqual(beta_report["traffic"], {"customer": len(beta_events)})  # type: ignore[arg-type]
        self.assertNotIn("merchant_self", alpha_report["traffic"])  # type: ignore[operator]
        self.assertEqual(beta_report["customer"]["counts"]["searches"], 1)  # type: ignore[index]
        self.assertEqual(alpha_report["customer"]["counts"]["searches"], 1)  # type: ignore[index]

    # -- mutations -----------------------------------------------------------

    def test_mutations_fail_closed_across_stores(self) -> None:
        self.assertEqual(self.login(self.fixture.alpha).status_code, 303)
        alpha_before, beta_before = self.both_counts()

        published = self.publish(self.fixture.alpha)
        self.assertEqual(published.status_code, 303)
        new_item_id = published.headers["Location"].split("published=", 1)[1].split("&", 1)[0]
        alpha_after_publish, beta_after_publish = self.both_counts()
        self.assertEqual(
            tuple(a - b for a, b in zip(alpha_after_publish, alpha_before, strict=True)),
            (1, 1, 1, 1),
        )
        self.assertEqual(beta_after_publish, beta_before)

        for label, operation in (
            ("edit", lambda: self.edit(self.fixture.alpha, new_item_id, price="4.00")),
            ("hide", lambda: self.listing(self.fixture.alpha, new_item_id, "hide")),
            ("unhide", lambda: self.listing(self.fixture.alpha, new_item_id, "unhide")),
            ("sold", lambda: self.listing(self.fixture.alpha, new_item_id, "sold")),
            ("relist", lambda: self.listing(self.fixture.alpha, new_item_id, "relist")),
            ("replace", lambda: self.replace(self.fixture.alpha, new_item_id)),
        ):
            with self.subTest(operation=label):
                beta_snapshot = self.counts(self.fixture.beta)
                alpha_snapshot = self.counts(self.fixture.alpha)
                response = operation()
                self.assertEqual(response.status_code, 303, response.data[:200])
                self.assertEqual(self.counts(self.fixture.beta), beta_snapshot)
                alpha_next = self.counts(self.fixture.alpha)
                self.assertEqual(
                    (alpha_next[2] - alpha_snapshot[2], alpha_next[3] - alpha_snapshot[3]),
                    (1, 1),
                )

        # Store B's own item ID through store A's authenticated routes is the same
        # non-disclosing failure as a random unknown ID, and mutates nothing.
        alpha_before_foreign, beta_before_foreign = self.both_counts()
        unknown = "no-such-isolation-item"
        comparisons = [
            self.get(self.fixture.alpha, f"/manage/items/{BETA_ONLY_ITEM_ID}"),
            self.get(self.fixture.alpha, f"/manage/items/{unknown}"),
        ]
        self.assertEqual(comparisons[0].status_code, 404)
        self.assertEqual(comparisons[0].data, comparisons[1].data)
        # The non-disclosing 404 page carries no token, so use the store's own page.
        alpha_csrf = self.csrf_token(self.get(self.fixture.alpha, "/manage"))
        for route, payload in (
            ("edit", {"title": "x", "category": "Lamps", "price": "1.00"}),
            ("listing", {"action": "hide"}),
        ):
            with self.subTest(route=route):
                foreign = self.client(self.fixture.alpha).post(
                    f"/manage/items/{BETA_ONLY_ITEM_ID}/{route}",
                    base_url=self.fixture.alpha.url_host,
                    data={"csrf_token": alpha_csrf, **payload},
                )
                missing = self.client(self.fixture.alpha).post(
                    f"/manage/items/{unknown}/{route}",
                    base_url=self.fixture.alpha.url_host,
                    data={"csrf_token": alpha_csrf, **payload},
                )
                self.assertEqual(foreign.status_code, 404)
                self.assertEqual(foreign.data, missing.data)
        self.assertEqual(
            (self.counts(self.fixture.alpha), self.counts(self.fixture.beta)),
            (alpha_before_foreign, beta_before_foreign),
        )

    def test_identical_bytes_are_independent_addresses_across_stores(self) -> None:
        self.assertEqual(self.login(self.fixture.alpha).status_code, 303)
        beta_photo = self.fixture.beta.object(BETA_ONLY_ITEM_ID).source_image
        beta_sha = display_sha256(beta_photo, self.fixture.beta.store)
        alpha_before = self.counts(self.fixture.alpha)
        beta_before = self.counts(self.fixture.beta)

        # Store A publishes store B's exact bytes: no cross-store dedup, its own item.
        published = self.publish(self.fixture.alpha, photo=beta_photo, title="Alpha copy")
        self.assertEqual(published.status_code, 303)
        self.assertEqual(
            tuple(
                a - b for a, b in zip(self.counts(self.fixture.alpha), alpha_before, strict=True)
            ),
            (1, 1, 1, 1),
        )
        self.assertEqual(self.counts(self.fixture.beta), beta_before)
        self.assertEqual(self.media_status(self.fixture.alpha, ALPHA_STORE_ID, beta_sha), 200)
        self.assertEqual(self.media_status(self.fixture.beta, BETA_STORE_ID, beta_sha), 200)

        # A duplicate publication in store A must not remove store B's blob.
        duplicate = self.publish(self.fixture.alpha, photo=beta_photo, title="Alpha duplicate")
        self.assertIn("duplicate=1", duplicate.headers["Location"])
        alpha_after_duplicate = self.counts(self.fixture.alpha)
        self.assertEqual(
            tuple(a - b for a, b in zip(alpha_after_duplicate, alpha_before, strict=True)),
            (1, 1, 1, 1),
        )
        blobs = self.fixture.image_store()
        self.assertTrue(blobs.exists(self.fixture.alpha.store.scope, beta_sha, DISPLAY_VARIANT))
        self.assertTrue(blobs.exists(self.fixture.beta.store.scope, beta_sha, DISPLAY_VARIANT))
        self.assertEqual(self.media_status(self.fixture.beta, BETA_STORE_ID, beta_sha), 200)

        # A failed replacement in store A removes only the derivative it just wrote.
        beta_snapshot = self.counts(self.fixture.beta)
        rejected = self.replace(self.fixture.alpha, SHARED_ITEM_ID, photo=b"not an image at all")
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.counts(self.fixture.beta), beta_snapshot)
        self.assertTrue(blobs.exists(self.fixture.beta.store.scope, beta_sha, DISPLAY_VARIANT))
        self.assertEqual(list(self.media_root.rglob("*.tmp")), [])
