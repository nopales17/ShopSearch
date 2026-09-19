"""S11 acceptance: the explicit interactive Form & Field merchant demo.

One demo merchant (`demo`/`demo`) can sign in, publish a photographed item into the
dedicated disposable demo runtime, see it browsable before it is indexed, explicitly
make it searchable, and use the S8 lifecycle — while the committed museum records stay
read-only with their CMA/CC0 provenance intact.

Every mutation here is local demonstration state. Nothing in this file is customer,
demand, adoption or merchandising evidence, and no merchant or customer is real.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from apps.web.demo_runtime import (
    DEMO_PASSWORD,
    DEMO_PID_FILENAME,
    DEMO_RUNTIME_DIRNAME,
    DEMO_USERNAME,
    bootstrap_demo_runtime,
)
from apps.web.manage import InteractiveDemo
from apps.web.wsgi import create_pitch_app
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.pitch import load_pitch_catalog
from backend.platform.paths import DEFAULT_DEMO_DATASET_PATH
from backend.search.indexer import EmbeddingIndexer, IndexerConfig
from contracts.catalog import IndexState, ListingState
from tests.acceptance.test_merchant_publish import jpeg_bytes
from tests.unit.test_pitch import StubEncoder

HOST = "https://form-and-field.example"
MUSEUM_ITEM = "pitch-128096"
UPLOAD_CATEGORY = "Demo uploads"
CSRF_FIELD = re.compile(rb'name="csrf_token" value="([^"]+)"')


class StubClipEncoder(StubEncoder):
    """Deterministic text+image encoder; transport tests only, never model evidence."""

    def __init__(self, *, fail_images: bool = False) -> None:
        self.fail_images = fail_images

    def images(self, images: list[Any]) -> list[list[float]]:
        if self.fail_images:
            raise RuntimeError("model unavailable")
        return [[0.25] * 512 for _ in images]


def media_digest(media_root: Path) -> dict[str, str]:
    return {
        path.relative_to(media_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(media_root.rglob("*"))
        if path.is_file()
    }


class InteractiveDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.baseline.cleanup)
        cls.baseline_root = Path(cls.baseline.name) / DEMO_RUNTIME_DIRNAME
        stack, _ = bootstrap_demo_runtime(cls.baseline_root)
        stack.close()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / DEMO_RUNTIME_DIRNAME
        shutil.copytree(self.baseline_root, self.root)
        self.stack, self.report = bootstrap_demo_runtime(self.root)
        self.addCleanup(self.stack.close)
        self.store = self.stack.demo_store
        self.scope = self.store.scope
        self.encoder = StubClipEncoder()
        self.capability = InteractiveDemo(DEMO_USERNAME, DEMO_PASSWORD)
        self.client = self.build_app().test_client()

    # -- helpers -------------------------------------------------------------

    def build_app(self, *, encoder: Any = None, capability: Any = "default"):
        index_encoder = encoder or self.encoder
        indexer = EmbeddingIndexer(
            self.stack.catalog_repository,
            self.stack.image_store,
            index_encoder,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            config=IndexerConfig(backoff_seconds=0.0, max_backoff_seconds=0.0),
            sleep=lambda _seconds: None,
        )
        return create_pitch_app(
            encoder=index_encoder,
            stack=self.stack,
            storefronts={self.store.store_id},
            interactive_demo=self.capability if capability == "default" else capability,
            index_store=indexer.run,
        )

    def csrf_token(self, response) -> str:
        match = CSRF_FIELD.search(response.data)
        self.assertIsNotNone(match, "page must carry a CSRF token")
        assert match is not None
        return match.group(1).decode()

    def login(self, client=None, *, username: str = DEMO_USERNAME, password: str = DEMO_PASSWORD):
        client = client or self.client
        page = client.get("/manage/login", base_url=HOST)
        return client.post(
            "/manage/login",
            base_url=HOST,
            data={
                "csrf_token": self.csrf_token(page),
                "username": username,
                "password": password,
            },
        )

    def manage_page(self, client=None):
        return (client or self.client).get("/manage", base_url=HOST)

    def publish(
        self,
        *,
        client=None,
        csrf: str | None = None,
        title: str = "Local demo bowl",
        category: str = UPLOAD_CATEGORY,
        price: str = "24.00",
        photo: bytes | None = None,
    ):
        client = client or self.client
        token = csrf if csrf is not None else self.csrf_token(self.manage_page(client))
        return client.post(
            "/manage/publish",
            base_url=HOST,
            data={
                "csrf_token": token,
                "price": price,
                "title": title,
                "category": category,
                "attested_capture": "yes",
                "photo": (io.BytesIO(photo or jpeg_bytes()), "photo.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )

    def publish_one(self, **kwargs) -> str:
        response = self.publish(**kwargs)
        self.assertEqual(response.status_code, 303)
        location = response.headers["Location"]
        return location.split("published=", 1)[1].split("&", 1)[0]

    def counts(self) -> tuple[int, int, int, tuple[int, int]]:
        catalog = self.stack.catalog_repository
        generations = catalog.generations(self.scope)
        return (
            catalog.item_count(self.scope),
            catalog.image_count(self.scope),
            catalog.event_count(self.scope),
            (generations.catalog, generations.index),
        )

    def search(self, query: str = "", *, category: str = UPLOAD_CATEGORY, client=None):
        params = {"category": category}
        if query:
            params["q"] = query
        response = (client or self.client).get(f"/api/search?{urlencode(params)}", base_url=HOST)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data)

    def item_state(self, item_id: str):
        return self.stack.catalog_repository.item_state(self.scope, item_id)

    # -- credential and composition boundary ---------------------------------

    def test_interactive_composition_signs_in_the_local_demo_credential(self) -> None:
        login_page = self.client.get("/manage/login", base_url=HOST)
        self.assertIn(b"Local demonstration credential", login_page.data)
        self.assertIn(b">demo<", login_page.data)
        wrong = self.login(password="not-the-demo-password")
        self.assertEqual(wrong.status_code, 401)
        self.assertIn(b"Invalid username or password", wrong.data)
        valid = self.login()
        self.assertEqual(valid.status_code, 303)
        self.assertEqual(valid.headers["Location"], "/manage")
        self.assertIn("shopsearch_merchant=", valid.headers["Set-Cookie"])
        page = self.manage_page()
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Signed in as demo", page.data)
        self.assertIn(b"/manage/publish", page.data)

    def test_generic_composition_never_reveals_or_enables_demo_mutation(self) -> None:
        generic = self.build_app(capability=None).test_client()
        login_page = generic.get("/manage/login", base_url=HOST)
        self.assertEqual(login_page.status_code, 200)
        self.assertNotIn(b"Local demonstration credential", login_page.data)
        self.assertNotIn(b">demo<", login_page.data)

        # A merchant account can exist for the demo store and still change nothing.
        self.assertEqual(self.login(generic).status_code, 303)
        page = generic.get("/manage", base_url=HOST)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"/manage/publish", page.data)
        self.assertNotIn(b"/manage/items/", page.data)
        self.assertIn(b"illustrative demo", page.data)
        before = self.counts()
        refused = self.publish(client=generic, csrf=self.csrf_token(page))
        self.assertEqual(refused.status_code, 400)
        self.assertIn(b"illustrative demo", refused.data)
        self.assertEqual(self.counts(), before)

        item_page = generic.get(f"/manage/items/{MUSEUM_ITEM}", base_url=HOST)
        self.assertEqual(item_page.status_code, 200)
        self.assertIn(b"illustrative demo", item_page.data)
        self.assertNotIn(b'name="price"', item_page.data)
        for action, data in (
            ("edit", {"title": "changed", "category": "", "price": "1.00"}),
            ("listing", {"action": "hide"}),
            ("index", {}),
        ):
            with self.subTest(action=action):
                response = generic.post(
                    f"/manage/items/{MUSEUM_ITEM}/{action}",
                    base_url=HOST,
                    data={"csrf_token": self.csrf_token(page), **data},
                )
                self.assertIn(response.status_code, (400, 404))
        self.assertEqual(self.counts(), before)

    def test_index_action_is_absent_without_the_interactive_capability(self) -> None:
        generic = self.build_app(capability=None).test_client()
        self.login(generic)
        page = generic.get("/manage", base_url=HOST)
        before = self.counts()
        response = generic.post(
            f"/manage/items/{MUSEUM_ITEM}/index",
            base_url=HOST,
            data={"csrf_token": self.csrf_token(page)},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.counts(), before)

    # -- publish, browse, index ---------------------------------------------

    def test_publish_is_browsable_before_indexing_and_excluded_from_visual_search(self) -> None:
        self.login()
        before = self.counts()
        item_id = self.publish_one()
        after = self.counts()
        self.assertEqual(after[0], before[0] + 1, "exactly one item")
        self.assertEqual(after[1], before[1] + 1, "exactly one image")
        self.assertEqual(after[2], before[2] + 1, "exactly one item event")
        self.assertEqual(after[3][0], before[3][0] + 1, "exactly one catalog-generation bump")

        state = self.item_state(item_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.listing_state, ListingState.PUBLISHED)
        self.assertEqual(state.index_state, IndexState.PENDING)

        detail = self.client.get(f"/items/{item_id}", base_url=HOST)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Local demo bowl", detail.data)
        browse = self.search()
        self.assertEqual(browse["count"], 1)
        self.assertIn(item_id, browse["html"])
        priced = self.search("under $30")
        self.assertEqual(priced["count"], 1, "price paths never depend on index state")
        self.assertIn(item_id, priced["html"])

        visual = self.search("blue")
        self.assertEqual(visual["count"], 0)
        self.assertEqual(
            visual["coverage"],
            {
                "published": 91,
                "ready": 90,
                "excluded_unindexed": 1,
                "visual_text": True,
            },
        )
        self.assertIn("1 of 91", visual["coverage_html"])

    def test_publish_confirmation_offers_the_storefront_and_indexing_controls(self) -> None:
        self.login()
        item_id = self.publish_one()
        page = self.client.get(f"/manage?published={item_id}", base_url=HOST)
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'href="/items/{item_id}"'.encode(), page.data)
        self.assertIn(b"View in storefront", page.data)
        self.assertIn(f'action="/manage/items/{item_id}/index"'.encode(), page.data)
        self.assertIn(b"Make searchable now", page.data)
        self.assertIn(b"Your local upload", page.data)

    def test_make_searchable_now_is_post_only_authenticated_and_csrf_protected(self) -> None:
        self.login()
        item_id = self.publish_one()
        target = f"/manage/items/{item_id}/index"
        self.assertEqual(self.client.get(target, base_url=HOST).status_code, 405)

        anonymous = self.build_app().test_client()
        self.assertEqual(
            anonymous.post(target, base_url=HOST, data={"csrf_token": "x"}).status_code, 303
        )
        before = self.counts()
        rejected = self.client.post(target, base_url=HOST, data={"csrf_token": "not-the-token"})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.item_state(item_id).index_state, IndexState.PENDING)

    def test_make_searchable_now_indexes_without_a_second_catalog_event(self) -> None:
        self.login()
        item_id = self.publish_one()
        page = self.manage_page()
        before = self.counts()
        response = self.client.post(
            f"/manage/items/{item_id}/index",
            base_url=HOST,
            data={"csrf_token": self.csrf_token(page)},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["Location"], f"/manage/items/{item_id}?updated=searchable"
        )
        after = self.counts()
        self.assertEqual(after[2], before[2], "indexing appends no catalog item event")
        self.assertEqual(after[3][0], before[3][0], "indexing never bumps the catalog generation")
        self.assertEqual(after[3][1], before[3][1] + 1, "one embedding write bumps the index")
        state = self.item_state(item_id)
        assert state is not None
        self.assertEqual(state.listing_state, ListingState.PUBLISHED)
        self.assertEqual(state.index_state, IndexState.READY)

        visual = self.search("blue")
        self.assertEqual(visual["count"], 1)
        self.assertIn(item_id, visual["html"])
        self.assertEqual(visual["coverage"]["excluded_unindexed"], 0)
        self.assertEqual(visual["coverage"]["ready"], 91)

        notice = self.client.get(
            f"/manage/items/{item_id}", base_url=HOST, query_string={"updated": "searchable"}
        )
        self.assertIn(b"searchable by description now", notice.data)

    def test_indexing_failure_keeps_the_item_published_and_reports_honestly(self) -> None:
        failing = StubClipEncoder(fail_images=True)
        client = self.build_app(encoder=failing).test_client()
        self.login(client)
        item_id = self.publish_one(client=client)
        page = client.get("/manage", base_url=HOST)
        response = client.post(
            f"/manage/items/{item_id}/index",
            base_url=HOST,
            data={"csrf_token": self.csrf_token(page)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The description index could not be built", response.data)
        self.assertIn(b"model unavailable", response.data)
        state = self.item_state(item_id)
        assert state is not None
        self.assertEqual(state.listing_state, ListingState.PUBLISHED)
        self.assertEqual(state.index_state, IndexState.FAILED)
        self.assertIn("model unavailable", state.index_error or "")
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=HOST).status_code, 200)
        self.assertEqual(self.search()["count"], 1)
        self.assertEqual(self.search("blue")["count"], 0)

    # -- S8 lifecycle on an uploaded demo item -------------------------------

    def test_uploaded_item_supports_edit_listing_and_photo_replacement(self) -> None:
        self.login()
        item_id = self.publish_one()
        page = self.manage_page()
        csrf = self.csrf_token(page)

        edited = self.client.post(
            f"/manage/items/{item_id}/edit",
            base_url=HOST,
            data={
                "csrf_token": csrf,
                "title": "Renamed bowl",
                "category": UPLOAD_CATEGORY,
                "price": "31.50",
            },
        )
        self.assertEqual(edited.status_code, 303)
        self.assertEqual(edited.headers["Location"], f"/manage/items/{item_id}?updated=saved")
        state = self.item_state(item_id)
        assert state is not None
        self.assertEqual(state.listing_state, ListingState.PUBLISHED)
        detail = self.client.get(f"/items/{item_id}", base_url=HOST).data.decode()
        self.assertIn("Renamed bowl", detail)
        self.assertIn("$31.50", detail)

        events_before = self.counts()
        hidden = self.client.post(
            f"/manage/items/{item_id}/listing",
            base_url=HOST,
            data={"csrf_token": csrf, "action": "hide"},
        )
        self.assertEqual(hidden.status_code, 303)
        self.assertEqual(self.item_state(item_id).listing_state, ListingState.HIDDEN)
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=HOST).status_code, 404)
        self.assertEqual(self.counts()[2], events_before[2] + 1)

        self.client.post(
            f"/manage/items/{item_id}/listing",
            base_url=HOST,
            data={"csrf_token": csrf, "action": "unhide"},
        )
        self.assertEqual(self.item_state(item_id).listing_state, ListingState.PUBLISHED)
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=HOST).status_code, 200)

        self.client.post(
            f"/manage/items/{item_id}/listing",
            base_url=HOST,
            data={"csrf_token": csrf, "action": "sold"},
        )
        self.assertEqual(self.item_state(item_id).listing_state, ListingState.SOLD)
        self.client.post(
            f"/manage/items/{item_id}/listing",
            base_url=HOST,
            data={"csrf_token": csrf, "action": "relist"},
        )
        self.assertEqual(self.item_state(item_id).listing_state, ListingState.PUBLISHED)

        # Index it, then replace the photo: the old vector must stop being usable.
        self.client.post(
            f"/manage/items/{item_id}/index",
            base_url=HOST,
            data={"csrf_token": csrf},
        )
        self.assertEqual(self.item_state(item_id).index_state, IndexState.READY)
        replaced = self.client.post(
            f"/manage/items/{item_id}/replace",
            base_url=HOST,
            data={
                "csrf_token": csrf,
                "attested_capture": "yes",
                "photo": (io.BytesIO(jpeg_bytes(size=(64, 48))), "new.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(replaced.status_code, 303)
        self.assertEqual(replaced.headers["Location"], f"/manage/items/{item_id}?updated=replaced")
        self.assertEqual(self.item_state(item_id).listing_state, ListingState.PUBLISHED)
        self.assertEqual(self.item_state(item_id).index_state, IndexState.PENDING)
        self.assertEqual(self.client.get(f"/items/{item_id}", base_url=HOST).status_code, 200)
        self.assertEqual(self.search("blue")["count"], 0)
        self.assertEqual(self.search()["count"], 1)
        self.client.post(
            f"/manage/items/{item_id}/index",
            base_url=HOST,
            data={"csrf_token": csrf},
        )
        self.assertEqual(self.item_state(item_id).index_state, IndexState.READY)
        self.assertEqual(self.search("blue")["count"], 1)

    def test_committed_museum_items_reject_every_mutation_and_index_action(self) -> None:
        self.login()
        page = self.manage_page()
        csrf = self.csrf_token(page)
        self.assertNotIn(f'href="/manage/items/{MUSEUM_ITEM}"'.encode(), page.data)
        self.assertIn(b"Museum collection (read-only)", page.data)

        detail = self.client.get(f"/manage/items/{MUSEUM_ITEM}", base_url=HOST)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"read-only demo collection", detail.data)
        self.assertNotIn(b'name="price"', detail.data)
        self.assertNotIn(b"Make searchable now", detail.data)

        state_before = self.item_state(MUSEUM_ITEM)
        index_before = self.stack.catalog_repository.index_summary(
            self.scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=512
        )
        counts_before = self.counts()
        media_before = media_digest(self.report.media_root)
        attempts = (
            ("edit", {"title": "forged", "category": "", "price": "1.00"}, jpeg_bytes()),
            ("listing", {"action": "hide"}, None),
            ("replace", {"attested_capture": "yes"}, jpeg_bytes(size=(64, 48))),
            ("index", {}, None),
        )
        for action, data, photo in attempts:
            with self.subTest(action=action):
                payload: dict[str, Any] = {"csrf_token": csrf, **data}
                if photo is not None:
                    payload["photo"] = (io.BytesIO(photo), "photo.jpg", "image/jpeg")
                response = self.client.post(
                    f"/manage/items/{MUSEUM_ITEM}/{action}",
                    base_url=HOST,
                    data=payload,
                    content_type="multipart/form-data",
                )
                self.assertIn(response.status_code, (400, 404))
        self.assertEqual(self.item_state(MUSEUM_ITEM), state_before)
        self.assertEqual(
            self.stack.catalog_repository.index_summary(
                self.scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=512
            ),
            index_before,
        )
        self.assertEqual(self.counts(), counts_before)
        self.assertEqual(media_digest(self.report.media_root), media_before)
        committed = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, self.store.configuration())
        expected_bowls = sum(1 for item in committed.items if item.category == "Bowls")
        self.assertEqual(self.search(category="Bowls")["count"], expected_bowls)

    # -- provenance rendering and telemetry ---------------------------------

    def test_uploaded_and_museum_items_render_their_own_provenance(self) -> None:
        museum_page = self.client.get(f"/items/{MUSEUM_ITEM}", base_url=HOST).data.decode()
        museum = museum_page.split('<div class="detail-copy">')[1].split("</main>")[0]
        for expected in (
            "Original title",
            "Dimensions",
            "The Cleveland Museum of Art · CC0",
            "This museum object is not for sale",
            "View the original source",
        ):
            self.assertIn(expected, museum)
        self.assertNotIn("Uploaded through the local merchant demo", museum)

        self.login()
        item_id = self.publish_one()
        uploaded_page = self.client.get(f"/items/{item_id}", base_url=HOST).data.decode()
        # The item's own detail block, not the store-wide footer, must make no
        # museum-attribution claim it cannot support.
        uploaded = uploaded_page.split('<div class="detail-copy">')[1].split("</main>")[0]
        self.assertIn("Uploaded through the local merchant demo", uploaded)
        self.assertIn("not part of the committed museum collection", uploaded)
        for forbidden in (
            "Original title",
            "Dimensions",
            "Cleveland Museum of Art",
            "CC0",
            "View the original source",
            "museum object is not for sale",
            "accession_number",
        ):
            self.assertNotIn(forbidden, uploaded)

        credits = self.client.get("/credits", base_url=HOST).data.decode()
        self.assertNotIn("Local demo bowl", credits)
        self.assertIn("committed museum collection", credits)
        footer = self.client.get("/", base_url=HOST).data.decode()
        self.assertIn("committed museum collection", footer)
        self.assertIn("Items uploaded through the local merchant demo", footer)

    def test_storefront_traffic_classification_is_unchanged(self) -> None:
        self.client.get("/", base_url=HOST)
        self.login()
        self.client.get("/", base_url=HOST)
        events = self.stack.telemetry_stores.for_store(self.store).events()
        classifications = [event["payload"]["traffic"] for event in events]
        self.assertIn("pitch_demo", classifications)
        self.assertIn("merchant_self", classifications)
        self.assertNotIn("customer", classifications)

    def test_demo_runtime_is_installed_under_its_own_root(self) -> None:
        self.assertTrue(self.root.is_dir())
        self.assertEqual(self.root.name, DEMO_RUNTIME_DIRNAME)
        self.assertTrue((self.root / "shopsearch.sqlite3").is_file())
        self.assertTrue((self.root / "media").is_dir())
        # The generic local platform database is untouched by the demo runtime.
        self.assertFalse((self.root / DEMO_PID_FILENAME).exists())
