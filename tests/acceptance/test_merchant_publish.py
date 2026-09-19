from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from apps.web.wsgi import create_pitch_app
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import AuthStores
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import LocalImageStore
from backend.media.uploads import MAX_UPLOAD_BYTES
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.indexer import EmbeddingIndexer
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import CaptureTimeSource, IndexState, ListingState
from contracts.store import Store
from tests.unit.test_merchant_auth import FAST_ITERATIONS
from tests.unit.test_pitch import StubEncoder

LIVE_HOST = "https://live.example"
OTHER_HOST = "https://other.example"
DEMO_HOST = "https://form-and-field.example"
LIVE_PASSWORD = "live-password"
DEMO_PASSWORD = "demo-password"
CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')


class StubImageEncoder:
    """Deterministic 512-d embedding; transport tests only, never model evidence."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def images(self, images: list[Any]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("model unavailable")
        return [[0.25] * 512 for _ in images]


def jpeg_bytes(*, size=(48, 32), exif_datetime: str | None = None) -> bytes:
    image = Image.new("RGB", size, (25, 70, 140))
    buffer = BytesIO()
    if exif_datetime:
        exif = image.getexif()
        exif[0x8769] = {36867: exif_datetime}
        image.save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (24, 24), (10, 200, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def live_store_document(store_id: str, domain: str) -> dict[str, Any]:
    """A neutral live-store fixture, not the museum demo's illustrative wording."""

    document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
    document["store_id"] = store_id
    document["is_demo"] = False
    document["domains"] = [domain]
    presentation = document["presentation"]
    presentation.update(
        {
            "page_title_suffix": "Test store fixture",
            "meta_description": "Local test store fixture; not a real shop.",
            "demo_strip": "Test store fixture \u00b7 photographed items only",
            "tagline": "A local test store fixture.",
            "footer_disclosure": "Test store fixture. Availability may have changed.",
            "hero_title_html": "Test store.<br><em>Fixture items.</em>",
            "hero_description": "A local fixture used by the store-scoped platform tests.",
            "catalog_disclaimer": "Test store fixture. Prices are illustrative test values.",
            "item_source_value": "Photographed for this store",
            "item_fine_print_html": "Availability may have changed.",
            "credits_copy_html": "Test store fixture; no external photo credits apply.",
            "public_claim": "Test store fixture; recently photographed items only",
        }
    )
    return document


class MerchantPublishTest(unittest.TestCase):
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
            self.live = self.add_live_store(stores, "live-store", "live.example")
            self.other = self.add_live_store(stores, "other-store", "other.example")
        with AuthStores.open(self.database_path, iterations=FAST_ITERATIONS) as auth_stores:
            self.live_auth = auth_stores.for_store(self.live)
            self.other_auth = auth_stores.for_store(self.other)
            self.demo_auth = auth_stores.for_store(self.demo)
            self.live_merchant = self.live_auth.create_merchant("lee", LIVE_PASSWORD)
            self.other_merchant = self.other_auth.create_merchant("mo", LIVE_PASSWORD)
            self.demo_merchant = self.demo_auth.create_merchant("dana", DEMO_PASSWORD)
        self.app = create_pitch_app(
            encoder=StubEncoder(),
            database_path=self.database_path,
            media_root=self.media_root,
            development_hosts_path=development_hosts,
            storefronts={"pitch-demo", "live-store", "other-store"},
        )
        self.client = self.app.test_client()

    def add_live_store(self, stores: StoreRepository, store_id: str, domain: str) -> Store:
        document, domains = load_store_config_in_memory(live_store_document(store_id, domain))
        return stores.create_store(document, domains)

    # -- helpers -------------------------------------------------------------

    def auth(self, store: Store):
        stores = AuthStores.open(self.database_path, iterations=FAST_ITERATIONS)
        self.addCleanup(stores.close)
        return stores.for_store(store)

    def csrf_token(self, response) -> str:
        match = CSRF_FIELD.search(response.data)
        self.assertIsNotNone(match, "form must carry a CSRF token")
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

    def manage_page(self, host: str = LIVE_HOST):
        return self.client.get("/manage", base_url=host)

    def publish(
        self,
        *,
        host: str = LIVE_HOST,
        photo: bytes | None = None,
        content_type: str = "image/jpeg",
        price: str = "24.00",
        title: str = "Blue bowl",
        category: str = "Bowls",
        attested: bool = False,
        csrf: str | None = None,
        client=None,
    ):
        client = client or self.client
        page = client.get("/manage", base_url=host)
        data: dict[str, Any] = {
            "csrf_token": csrf if csrf is not None else self.csrf_token(page),
            "price": price,
            "title": title,
            "category": category,
            "photo": (
                io.BytesIO(jpeg_bytes() if photo is None else photo),
                "photo.jpg",
                content_type,
            ),
        }
        if attested:
            data["attested_capture"] = "yes"
        return client.post(
            "/manage/publish",
            base_url=host,
            data=data,
            content_type="multipart/form-data",
        )

    def counts(self, store: Store) -> tuple[int, int, int, int]:
        with CatalogRepository.open(self.database_path) as catalog:
            scope = store.scope
            return (
                catalog.item_count(scope),
                catalog.image_count(scope),
                catalog.event_count(scope),
                catalog.generations(scope).catalog,
            )

    def blobs(self, store: Store) -> int:
        return LocalImageStore(self.media_root).blob_count(store.scope)

    def item_state(self, store: Store, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.item_state(store.scope, item_id)

    def captured_item(self, store: Store, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.get_published(store.scope, item_id), catalog.display_image(
                store.scope, item_id
            )

    def search(self, query: str, *, host: str = LIVE_HOST) -> dict[str, Any]:
        response = self.client.get(f"/api/search?q={query}", base_url=host)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data)

    def published_id(self, response) -> str:
        self.assertEqual(response.status_code, 303)
        location = response.headers["Location"]
        self.assertIn("/manage?published=", location)
        return location.split("published=", 1)[1].split("&", 1)[0]

    def run_indexer(self, store: Store, encoder=None):
        with CatalogRepository.open(self.database_path) as catalog:
            indexer = EmbeddingIndexer(
                catalog,
                LocalImageStore(self.media_root),
                encoder or StubImageEncoder(),
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
            )
            return indexer.run(store.scope)

    # -- tests ---------------------------------------------------------------

    def test_publish_creates_one_item_image_event_and_one_generation_bump(self) -> None:
        self.assertEqual(self.login(LIVE_HOST, "lee", LIVE_PASSWORD).status_code, 303)
        before = self.counts(self.live)
        response = self.publish(price="24.00", title="Blue bowl")
        item_id = self.published_id(response)
        after = self.counts(self.live)
        self.assertEqual(
            (
                after[0] - before[0],
                after[1] - before[1],
                after[2] - before[2],
                after[3] - before[3],
            ),
            (1, 1, 1, 1),
        )
        state = self.item_state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        self.assertIs(state.index_state, IndexState.PENDING)
        self.assertEqual(state.index_attempts, 0)
        with CatalogRepository.open(self.database_path) as catalog:
            self.assertIsNone(catalog.embedding_for(self.live.scope, item_id))
            events = [
                row
                for row in catalog._database.connection().execute(
                    "SELECT actor, event_type FROM item_events WHERE store_id = ? AND item_id = ?",
                    (self.live.store_id, item_id),
                )
            ]
        self.assertEqual(
            [(str(row["event_type"]), str(row["actor"])) for row in events],
            [("published", self.live_merchant.merchant_id)],
        )

    def test_published_item_is_browsable_then_searchable_after_indexing(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        item_id = self.published_id(self.publish())

        catalog_page = self.client.get("/catalog", base_url=LIVE_HOST)
        self.assertEqual(catalog_page.status_code, 200)
        self.assertIn(item_id.encode(), catalog_page.data)
        detail = self.client.get(f"/items/{item_id}", base_url=LIVE_HOST)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Blue bowl", detail.data)

        pending = self.search("blue")
        self.assertEqual(pending["count"], 0)
        self.assertEqual(pending["coverage"]["excluded_unindexed"], 1)

        report = self.run_indexer(self.live)
        self.assertEqual((report.ready, report.failed), (1, 0))
        indexed = self.search("blue")
        self.assertEqual(indexed["count"], 1)
        self.assertEqual(indexed["coverage"]["excluded_unindexed"], 0)

    def test_blank_price_is_unknown_and_excluded_from_bounded_queries(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        item_id = self.published_id(self.publish(price=""))
        item, image = self.captured_item(self.live, item_id)
        assert item is not None and image is not None
        self.assertIsNone(item.price)
        self.assertEqual(self.search("under+%2450")["count"], 0)
        self.assertEqual(self.search("up+to+%2450")["count"], 0)
        browse = self.client.get("/catalog", base_url=LIVE_HOST)
        self.assertIn(item_id.encode(), browse.data)

    def test_invalid_uploads_create_no_persistent_state(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        before = self.counts(self.live)
        blobs_before = self.blobs(self.live)
        cases = [
            {"photo": b"not an image", "content_type": "image/jpeg"},
            {"photo": b"", "content_type": "image/jpeg"},
            {"photo": png_bytes(), "content_type": "image/jpeg"},
            {"photo": b"x" * (MAX_UPLOAD_BYTES + 1024), "content_type": "image/jpeg"},
        ]
        for case in cases:
            with self.subTest(content_type=case["content_type"], size=len(case["photo"])):
                response = self.publish(**case)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.counts(self.live), before)
                self.assertEqual(self.blobs(self.live), blobs_before)
                self.assertEqual(list(self.media_root.rglob("*.tmp")), [])

    def test_oversized_request_is_rejected_before_parsing(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        before = self.counts(self.live)
        response = self.publish(photo=b"x" * (MAX_UPLOAD_BYTES + 256 * 1024))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.counts(self.live), before)
        self.assertEqual(self.blobs(self.live), 0)

    def test_index_failure_leaves_item_published_and_browsable(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        item_id = self.published_id(self.publish())
        report = self.run_indexer(self.live, StubImageEncoder(fail=True))
        self.assertEqual((report.ready, report.failed), (0, 1))
        state = self.item_state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        self.assertIs(state.index_state, IndexState.FAILED)
        self.assertIn("RuntimeError", state.index_error or "")
        self.assertIn(item_id.encode(), self.client.get("/catalog", base_url=LIVE_HOST).data)
        self.assertEqual(self.search("blue")["count"], 0)

    def test_capture_provenance_paths_are_distinguishable(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        exif_id = self.published_id(
            self.publish(photo=jpeg_bytes(exif_datetime="2025:01:02 03:04:05"), title="Exif item")
        )
        attested_id = self.published_id(
            self.publish(photo=jpeg_bytes(size=(40, 40)), title="Attested item", attested=True)
        )
        unknown_id = self.published_id(
            self.publish(photo=jpeg_bytes(size=(36, 36)), title="Unknown item")
        )
        _, exif_image = self.captured_item(self.live, exif_id)
        _, attested_image = self.captured_item(self.live, attested_id)
        unknown_item, unknown_image = self.captured_item(self.live, unknown_id)
        assert exif_image is not None and attested_image is not None
        assert unknown_image is not None and unknown_item is not None
        self.assertIs(exif_image.capture_time_source, CaptureTimeSource.EXIF)
        self.assertEqual(exif_image.capture_time.year, 2025)
        self.assertIs(attested_image.capture_time_source, CaptureTimeSource.MERCHANT_ATTESTATION)
        self.assertIsNotNone(attested_image.capture_time)
        self.assertIs(unknown_image.capture_time_source, CaptureTimeSource.UNKNOWN)
        self.assertIsNone(unknown_image.capture_time)
        # Upload time never becomes capture time and never matches the attested stamp.
        self.assertNotEqual(attested_image.capture_time, unknown_image.created_at)

    def test_duplicate_bytes_reuse_the_blob_without_a_second_item(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        photo = jpeg_bytes(size=(60, 40))
        first_id = self.published_id(self.publish(photo=photo, price="10.00", title="First"))
        after_first = self.counts(self.live)
        duplicate = self.publish(photo=photo, price="99.00", title="Second")
        self.assertIn("duplicate=1", duplicate.headers["Location"])
        self.assertEqual(self.published_id(duplicate), first_id)
        self.assertEqual(self.counts(self.live), after_first)
        self.assertEqual(self.blobs(self.live), 1)
        item, _ = self.captured_item(self.live, first_id)
        assert item is not None
        self.assertEqual(item.title, "First")
        self.assertEqual(item.price, Decimal("10.00"))
        confirmation = self.client.get(duplicate.headers["Location"], base_url=LIVE_HOST)
        self.assertIn(b"already published", confirmation.data)

    def test_cross_store_deduplication_does_not_occur(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        photo = jpeg_bytes(size=(70, 50))
        live_id = self.published_id(self.publish(photo=photo))
        other_client = self.app.test_client()
        login = self.login(OTHER_HOST, "mo", LIVE_PASSWORD, client=other_client)
        self.assertEqual(login.status_code, 303)
        other_id = self.published_id(
            self.publish(photo=photo, client=other_client, host=OTHER_HOST)
        )
        self.assertEqual(self.counts(self.other)[0], 1)
        self.assertEqual(self.blobs(self.other), 1)
        self.assertEqual(self.blobs(self.live), 1)
        self.assertNotEqual(live_id, other_id)

    def test_auth_and_csrf_failures_create_no_state(self) -> None:
        before = self.counts(self.live)
        anonymous = self.app.test_client()
        unauthenticated = self.publish(client=anonymous, csrf="whatever")
        self.assertEqual(unauthenticated.status_code, 303)
        self.assertEqual(unauthenticated.headers["Location"], "/manage/login")

        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        rejected = self.publish(csrf="not-the-token")
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.counts(self.live), before)

        # A store-A merchant session presented on store B creates nothing.
        foreign = self.app.test_client()
        demo_login = self.login(DEMO_HOST, "dana", DEMO_PASSWORD, client=foreign)
        self.assertEqual(demo_login.status_code, 303)
        demo_before = self.counts(self.demo)
        foreign_post = self.publish(client=foreign, host=LIVE_HOST, csrf="not-a-real-token")
        self.assertEqual(foreign_post.status_code, 303)
        self.assertEqual(self.counts(self.live), before)
        self.assertEqual(self.counts(self.demo), demo_before)

    def test_generic_composition_gives_the_demo_store_no_publish_form(self) -> None:
        """Without the explicit interactive-demo capability the demo cannot publish.

        The merchant account created in `setUp` proves the rule is compositional rather
        than credential-based: authenticating successfully still changes nothing here.
        """

        visitor = self.app.test_client()
        self.login(DEMO_HOST, "dana", DEMO_PASSWORD, client=visitor)
        page = visitor.get("/manage", base_url=DEMO_HOST)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"/manage/publish", page.data)
        self.assertIn(b"illustrative demo", page.data)
        before = self.counts(self.demo)
        response = self.publish(
            client=visitor, host=DEMO_HOST, csrf=self.csrf_token(page), photo=jpeg_bytes()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"illustrative demo", response.data)
        self.assertEqual(self.counts(self.demo), before)

    def test_publish_form_is_usable_at_375px(self) -> None:
        self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        page = self.manage_page().data.decode()
        for expected in (
            'name="viewport" content="width=device-width',
            'enctype="multipart/form-data"',
            'name="photo" accept="image/*" capture="environment" required',
            'name="price" inputmode="decimal"',
            'name="title"',
            'name="category"',
            'name="attested_capture"',
            'name="csrf_token"',
            "font-size:1rem",
            "width:100%",
            "box-sizing:border-box",
            "overflow-x:auto",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, page)
        widths = [int(value) for value in re.findall(r"width:(\d+)px", page)]
        self.assertTrue(all(value <= 375 for value in widths), widths)
