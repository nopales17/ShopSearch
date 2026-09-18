"""S8 acceptance: merchant edit, hide/unhide, sold/relist and image replacement."""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from apps.web.wsgi import create_pitch_app
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import AuthStores
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import DISPLAY_VARIANT, LocalImageStore
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.indexer import EmbeddingIndexer
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.catalog import IndexState, ListingState
from contracts.store import Store
from tests.acceptance.test_merchant_publish import (
    StubImageEncoder,
    jpeg_bytes,
    live_store_document,
)
from tests.unit.test_merchant_auth import FAST_ITERATIONS
from tests.unit.test_pitch import StubEncoder

LIVE_HOST = "https://live.example"
OTHER_HOST = "https://other.example"
LIVE_PASSWORD = "live-password"
CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')


class MerchantManageItemsTest(unittest.TestCase):
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
            self.live_merchant = auth_stores.for_store(self.live).create_merchant(
                "lee", LIVE_PASSWORD
            )
            auth_stores.for_store(self.other).create_merchant("mo", LIVE_PASSWORD)
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

    def csrf_token(self, response) -> str:
        match = CSRF_FIELD.search(response.data)
        self.assertIsNotNone(match, "page must carry a CSRF token")
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

    def publish(self, *, photo: bytes | None = None, price: str = "24.00", title="Blue bowl"):
        page = self.client.get("/manage", base_url=LIVE_HOST)
        return self.client.post(
            "/manage/publish",
            base_url=LIVE_HOST,
            data={
                "csrf_token": self.csrf_token(page),
                "price": price,
                "title": title,
                "category": "Bowls",
                "photo": (io.BytesIO(photo or jpeg_bytes()), "photo.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )

    def item_page(self, item_id: str, host: str = LIVE_HOST, client=None):
        return (client or self.client).get(f"/manage/items/{item_id}", base_url=host)

    def edit(self, item_id: str, *, price: str, title="Blue bowl", category="Bowls", csrf=None):
        page = self.item_page(item_id)
        return self.client.post(
            f"/manage/items/{item_id}/edit",
            base_url=LIVE_HOST,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "title": title,
                "category": category,
                "price": price,
            },
        )

    def listing(self, item_id: str, action: str, *, host: str = LIVE_HOST, client=None, csrf=None):
        client = client or self.client
        page = client.get(f"/manage/items/{item_id}", base_url=host)
        return client.post(
            f"/manage/items/{item_id}/listing",
            base_url=host,
            data={
                "csrf_token": csrf if csrf is not None else self.csrf_token(page),
                "action": action,
            },
        )

    def replace(self, item_id: str, photo: bytes, *, attested: bool = False, csrf=None):
        page = self.item_page(item_id)
        data: dict[str, Any] = {
            "csrf_token": csrf if csrf is not None else self.csrf_token(page),
            "photo": (io.BytesIO(photo), "photo.jpg", "image/jpeg"),
        }
        if attested:
            data["attested_capture"] = "yes"
        return self.client.post(
            f"/manage/items/{item_id}/replace",
            base_url=LIVE_HOST,
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

    def state(self, store: Store, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.item_state(store.scope, item_id)

    def current_image(self, store: Store, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.current_image(store.scope, item_id)

    def blobs(self, store: Store) -> int:
        return LocalImageStore(self.media_root).blob_count(store.scope)

    def search(self, query: str, *, host: str = LIVE_HOST) -> dict[str, Any]:
        response = self.client.get(f"/api/search?q={query}", base_url=host)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data)

    def published_id(self, response) -> str:
        self.assertEqual(response.status_code, 303)
        location = response.headers["Location"]
        return location.split("published=", 1)[1].split("&", 1)[0]

    def index(self, store: Store, encoder=None):
        with CatalogRepository.open(self.database_path) as catalog:
            return EmbeddingIndexer(
                catalog,
                LocalImageStore(self.media_root),
                encoder or StubImageEncoder(),
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
            ).run(store.scope)

    def surfaces(self, item_id: str, item_sha: str):
        """(present in browse, detail status, bounded-price count, media status)."""

        catalog = self.client.get("/catalog", base_url=LIVE_HOST)
        detail = self.client.get(f"/items/{item_id}", base_url=LIVE_HOST)
        media = self.client.get(
            f"/media/{self.live.store_id}/{item_sha}/{DISPLAY_VARIANT}", base_url=LIVE_HOST
        )
        return (
            item_id.encode() in catalog.data,
            detail.status_code,
            self.search("under+%2450")["count"],
            media.status_code,
        )

    def sign_in(self) -> None:
        response = self.login(LIVE_HOST, "lee", LIVE_PASSWORD)
        self.assertEqual(response.status_code, 303)

    # -- metadata ------------------------------------------------------------

    def test_editing_price_updates_bounded_search_immediately(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        self.assertEqual(self.search("under+%2450")["count"], 1)
        self.assertEqual(self.search("up+to+%2445")["count"], 1)

        before = self.counts(self.live)
        to_unknown = self.edit(item_id, price="")
        self.assertEqual(to_unknown.status_code, 303)
        self.assertEqual(to_unknown.headers["Location"], f"/manage/items/{item_id}?updated=saved")
        self.assertEqual(self.search("under+%2450")["count"], 0)
        self.assertEqual(self.search("up+to+%2445")["count"], 0)
        after_unknown = self.counts(self.live)
        self.assertEqual((after_unknown[2] - before[2], after_unknown[3] - before[3]), (1, 1))
        # An unknown price keeps the item browsable and openable.
        self.assertIn(item_id.encode(), self.client.get("/catalog", base_url=LIVE_HOST).data)
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=LIVE_HOST).status_code, 200)

        restored = self.edit(item_id, price="19.99")
        self.assertEqual(restored.status_code, 303)
        self.assertEqual(self.search("under+%2450")["count"], 1)
        self.assertEqual(self.search("up+to+%2445")["count"], 1)
        after_known = self.counts(self.live)
        self.assertEqual(
            (after_known[2] - after_unknown[2], after_known[3] - after_unknown[3]), (1, 1)
        )

    def test_no_op_edit_appends_no_event_and_no_generation_bump(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        before = self.counts(self.live)
        response = self.edit(item_id, price="24.0")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], f"/manage/items/{item_id}?updated=unchanged")
        self.assertEqual(self.counts(self.live), before)
        page = self.client.get(response.headers["Location"], base_url=LIVE_HOST)
        self.assertIn(b"Nothing changed.", page.data)

    def test_edit_records_actor_and_before_after(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        response = self.edit(item_id, price="31.50", title="Green vase", category="Vases")
        self.assertEqual(response.status_code, 303)
        with CatalogRepository.open(self.database_path) as catalog:
            row = (
                catalog._database.connection()
                .execute(
                    "SELECT actor, before_json, after_json FROM item_events "
                    "WHERE store_id = ? AND item_id = ? AND event_type = 'metadata_edited'",
                    (self.live.store_id, item_id),
                )
                .fetchone()
            )
        self.assertEqual(str(row["actor"]), self.live_merchant.merchant_id)
        self.assertEqual(json.loads(row["before_json"])["price"], "24.00")
        self.assertEqual(json.loads(row["after_json"])["price"], "31.50")
        self.assertEqual(json.loads(row["after_json"])["title"], "Green vase")

    # -- listing state -------------------------------------------------------

    def test_hide_and_unhide_change_every_customer_surface(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        image = self.current_image(self.live, item_id)
        assert image is not None
        self.assertEqual(self.surfaces(item_id, image.sha256), (True, 200, 1, 200))

        before = self.counts(self.live)
        hidden = self.listing(item_id, "hide")
        self.assertEqual(hidden.status_code, 303)
        self.assertEqual(hidden.headers["Location"], f"/manage/items/{item_id}?updated=hidden")
        self.assertEqual(self.surfaces(item_id, image.sha256), (False, 404, 0, 404))
        after = self.counts(self.live)
        self.assertEqual((after[2] - before[2], after[3] - before[3]), (1, 1))
        state = self.state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.HIDDEN)
        # Hidden items keep their media and identity.
        self.assertIsNotNone(self.current_image(self.live, item_id))
        self.assertEqual(self.blobs(self.live), 1)

        shown = self.listing(item_id, "unhide")
        self.assertEqual(shown.status_code, 303)
        self.assertEqual(shown.headers["Location"], f"/manage/items/{item_id}?updated=unhidden")
        self.assertEqual(self.surfaces(item_id, image.sha256), (True, 200, 1, 200))
        restored = self.state(self.live, item_id)
        assert restored is not None
        self.assertIs(restored.listing_state, ListingState.PUBLISHED)
        self.assertEqual(
            self.counts(self.live)[0], 1, "unhide must restore the same item, not create one"
        )

    def test_sold_and_relist_change_every_customer_surface(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        image = self.current_image(self.live, item_id)
        assert image is not None
        sold = self.listing(item_id, "sold")
        self.assertEqual(sold.status_code, 303)
        self.assertEqual(sold.headers["Location"], f"/manage/items/{item_id}?updated=sold")
        self.assertEqual(self.surfaces(item_id, image.sha256), (False, 404, 0, 404))
        state = self.state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.SOLD)
        with CatalogRepository.open(self.database_path) as catalog:
            event = (
                catalog._database.connection()
                .execute(
                    "SELECT actor, after_json FROM item_events "
                    "WHERE store_id = ? AND item_id = ? AND event_type = 'sold'",
                    (self.live.store_id, item_id),
                )
                .fetchone()
            )
        self.assertEqual(str(event["actor"]), self.live_merchant.merchant_id)
        self.assertIn("occurred_at", json.loads(event["after_json"]))
        self.assertEqual(self.blobs(self.live), 1, "sold items keep their media")

        relisted = self.listing(item_id, "relist")
        self.assertEqual(relisted.status_code, 303)
        self.assertEqual(relisted.headers["Location"], f"/manage/items/{item_id}?updated=relisted")
        self.assertEqual(self.surfaces(item_id, image.sha256), (True, 200, 1, 200))
        self.assertEqual(self.counts(self.live)[0], 1)

    def test_repeated_listing_action_is_a_no_op(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        self.listing(item_id, "hide")
        before = self.counts(self.live)
        again = self.listing(item_id, "hide")
        self.assertEqual(again.headers["Location"], f"/manage/items/{item_id}?updated=unchanged")
        self.assertEqual(self.counts(self.live), before)

    def test_unknown_listing_action_is_rejected(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        before = self.counts(self.live)
        response = self.listing(item_id, "publish")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.counts(self.live), before)

    # -- image replacement ---------------------------------------------------

    def test_replacement_stays_browsable_and_reindexes_after_one_run(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish(price="24.00"))
        first = self.current_image(self.live, item_id)
        assert first is not None
        report = self.index(self.live)
        self.assertEqual(report.ready, 1)
        self.assertEqual(self.search("blue")["count"], 1)

        before = self.counts(self.live)
        replacement = self.replace(item_id, jpeg_bytes(size=(80, 60)))
        self.assertEqual(replacement.status_code, 303)
        self.assertEqual(
            replacement.headers["Location"], f"/manage/items/{item_id}?updated=replaced"
        )
        after = self.counts(self.live)
        self.assertEqual((after[2] - before[2], after[3] - before[3]), (1, 1))
        self.assertEqual(self.blobs(self.live), 2, "old bytes are retained, not deleted")

        new_image = self.current_image(self.live, item_id)
        assert new_image is not None
        self.assertNotEqual(new_image.sha256, first.sha256)
        state = self.state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)
        self.assertIs(state.index_state, IndexState.PENDING)
        # Browsable immediately, excluded from visual text until the indexer runs.
        self.assertIn(item_id.encode(), self.client.get("/catalog", base_url=LIVE_HOST).data)
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=LIVE_HOST).status_code, 200)
        self.assertEqual(
            self.client.get(
                f"/media/{self.live.store_id}/{new_image.sha256}/{DISPLAY_VARIANT}",
                base_url=LIVE_HOST,
            ).status_code,
            200,
        )
        pending = self.search("blue")
        self.assertEqual(pending["count"], 0)
        self.assertEqual(pending["coverage"]["excluded_unindexed"], 1)
        self.assertEqual(self.search("under+%2450")["count"], 1)

        reindexed = self.index(self.live)
        self.assertEqual((reindexed.ready, reindexed.failed), (1, 0))
        ready = self.search("blue")
        self.assertEqual(ready["count"], 1)
        self.assertEqual(ready["coverage"]["excluded_unindexed"], 0)
        with CatalogRepository.open(self.database_path) as catalog:
            binding = catalog.embedding_for(self.live.scope, item_id)
        assert binding is not None
        self.assertEqual(binding.image_sha256, new_image.sha256)

    def test_replacement_with_the_current_bytes_is_a_no_op(self) -> None:
        self.sign_in()
        photo = jpeg_bytes(size=(90, 70))
        item_id = self.published_id(self.publish(photo=photo))
        before = self.counts(self.live)
        response = self.replace(item_id, photo)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], f"/manage/items/{item_id}?updated=unchanged")
        self.assertEqual(self.counts(self.live), before)
        self.assertEqual(self.blobs(self.live), 1)

    def test_replacement_with_another_items_bytes_is_rejected(self) -> None:
        self.sign_in()
        photo = jpeg_bytes(size=(92, 72))
        first_id = self.published_id(self.publish(photo=photo, title="First"))
        second_id = self.published_id(self.publish(photo=jpeg_bytes(size=(94, 74)), title="Second"))
        before = self.counts(self.live)
        blobs = self.blobs(self.live)
        response = self.replace(second_id, photo)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already belong", response.data)
        self.assertEqual(self.counts(self.live), before)
        self.assertEqual(self.blobs(self.live), blobs)
        self.assertIsNotNone(self.current_image(self.live, first_id))

    def test_replacement_with_an_invalid_photo_creates_no_state(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        before = self.counts(self.live)
        blobs = self.blobs(self.live)
        bad = self.replace(item_id, b"not an image at all")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.counts(self.live), before)
        self.assertEqual(self.blobs(self.live), blobs)
        self.assertEqual(list(self.media_root.rglob("*.tmp")), [])

    def test_replacement_without_a_photo_creates_no_state(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        page = self.item_page(item_id)
        before = self.counts(self.live)
        response = self.client.post(
            f"/manage/items/{item_id}/replace",
            base_url=LIVE_HOST,
            data={"csrf_token": self.csrf_token(page)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.counts(self.live), before)

    def test_duplicate_bytes_of_a_hidden_item_keep_its_blob(self) -> None:
        self.sign_in()
        photo = jpeg_bytes(size=(96, 76))
        item_id = self.published_id(self.publish(photo=photo))
        self.listing(item_id, "hide")
        blobs = self.blobs(self.live)
        duplicate = self.publish(photo=photo, price="99.00", title="Duplicate")
        self.assertIn("duplicate=1", duplicate.headers["Location"])
        self.assertEqual(self.blobs(self.live), blobs)
        kept = self.current_image(self.live, item_id)
        assert kept is not None
        self.assertTrue(
            LocalImageStore(self.media_root).exists(self.live.scope, kept.sha256, DISPLAY_VARIANT)
        )

    # -- isolation -----------------------------------------------------------

    def test_cross_store_item_ids_are_indistinguishable_from_unknown(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        other_client = self.app.test_client()
        login = self.login(OTHER_HOST, "mo", LIVE_PASSWORD, client=other_client)
        self.assertEqual(login.status_code, 303)
        before_live = self.counts(self.live)
        before_other = self.counts(self.other)

        foreign_get = other_client.get(f"/manage/items/{item_id}", base_url=OTHER_HOST)
        unknown_get = other_client.get("/manage/items/no-such-item", base_url=OTHER_HOST)
        self.assertEqual(foreign_get.status_code, 404)
        self.assertEqual(foreign_get.data, unknown_get.data)
        self.assertNotIn(item_id.encode(), foreign_get.data)

        # The non-disclosing 404 page carries no token; a real session's page does.
        foreign_csrf = self.csrf_token(other_client.get("/manage", base_url=OTHER_HOST))
        foreign_post = other_client.post(
            f"/manage/items/{item_id}/edit",
            base_url=OTHER_HOST,
            data={"csrf_token": foreign_csrf, "title": "x", "price": "1.00"},
        )
        unknown_post = other_client.post(
            "/manage/items/no-such-item/edit",
            base_url=OTHER_HOST,
            data={"csrf_token": foreign_csrf, "title": "x", "price": "1.00"},
        )
        self.assertEqual(foreign_post.status_code, 404)
        self.assertEqual(foreign_post.data, unknown_post.data)
        for action in ("hide", "sold"):
            response = other_client.post(
                f"/manage/items/{item_id}/listing",
                base_url=OTHER_HOST,
                data={"csrf_token": foreign_csrf, "action": action},
            )
            self.assertEqual(response.status_code, 404)
        replacement = other_client.post(
            f"/manage/items/{item_id}/replace",
            base_url=OTHER_HOST,
            data={
                "csrf_token": foreign_csrf,
                "photo": (io.BytesIO(jpeg_bytes()), "photo.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(replacement.status_code, 404)
        self.assertEqual(self.counts(self.live), before_live)
        self.assertEqual(self.counts(self.other), before_other)
        self.assertEqual(self.blobs(self.other), 0)
        state = self.state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)

    def test_auth_and_csrf_failures_mutate_nothing(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        before = self.counts(self.live)
        anonymous = self.app.test_client()
        for suffix, data in (
            ("edit", {"title": "x", "price": "1.00"}),
            ("listing", {"action": "hide"}),
        ):
            response = anonymous.post(
                f"/manage/items/{item_id}/{suffix}",
                base_url=LIVE_HOST,
                data={"csrf_token": "whatever", **data},
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["Location"], "/manage/login")
        rejected = self.edit(item_id, price="1.00", csrf="not-the-token")
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.counts(self.live), before)
        state = self.state(self.live, item_id)
        assert state is not None
        self.assertIs(state.listing_state, ListingState.PUBLISHED)

    # -- presentation --------------------------------------------------------

    def test_manage_list_links_to_item_pages(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        page = self.client.get("/manage", base_url=LIVE_HOST)
        self.assertIn(f'href="/manage/items/{item_id}"'.encode(), page.data)

    def test_item_page_is_usable_at_375px(self) -> None:
        self.sign_in()
        item_id = self.published_id(self.publish())
        page = self.item_page(item_id).data.decode()
        for expected in (
            'name="viewport" content="width=device-width',
            f'action="/manage/items/{item_id}/edit"',
            f'action="/manage/items/{item_id}/listing"',
            f'action="/manage/items/{item_id}/replace"',
            'enctype="multipart/form-data"',
            'name="photo" accept="image/*" capture="environment" required',
            'name="attested_capture"',
            'name="csrf_token"',
            'inputmode="decimal"',
            "font-size:1rem",
            "width:100%",
            "box-sizing:border-box",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, page)
        widths = [int(value) for value in re.findall(r"width:(\d+)px", page)]
        self.assertTrue(all(value <= 375 for value in widths), widths)


if __name__ == "__main__":
    unittest.main()
