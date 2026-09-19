"""S11 unit coverage: the dedicated, disposable Form & Field demo runtime.

The interactive demo is allowed to mutate catalog state because that state lives in an
ignored, disposable runtime root. These tests pin the two properties that make that
safe: bootstrapping is additive (an existing runtime keeps its local uploads), and
resetting rebuilds only the committed baseline after refusing to race a live demo.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.web.demo_runtime import (
    DEMO_PASSWORD,
    DEMO_RUNTIME_DIRNAME,
    DEMO_USERNAME,
    DemoRuntimeError,
    bootstrap_demo_runtime,
    clear_demo_process,
    demo_runtime_in_use,
    record_demo_process,
    reset_demo_runtime,
)
from backend.catalog.pitch import load_pitch_catalog
from backend.catalog.publish import MerchantPublisher
from backend.platform.paths import DEFAULT_DEMO_DATASET_PATH
from backend.telemetry.validation import new_event
from contracts.catalog import IndexState, ListingState
from contracts.telemetry import EventType, TrafficClass
from tests.unit.test_pitch import StubEncoder


class StubClipEncoder(StubEncoder):
    """Deterministic text+image encoder; transport tests only, never model evidence."""

    def images(self, images: list[Any]) -> list[list[float]]:
        return [[0.25] * 512 for _ in images]


def jpeg_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (180, 60, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def media_digest(media_root: Path) -> dict[str, str]:
    return {
        path.relative_to(media_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(media_root.rglob("*"))
        if path.is_file()
    }


class DemoRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / DEMO_RUNTIME_DIRNAME

    def publish_one(self, stack, *, title: str = "Local demo bowl") -> str:
        store = stack.demo_store
        merchant_id = stack.auth_stores.for_store(store).list_merchants()[0].merchant_id
        publisher = MerchantPublisher(
            store, stack.catalog_repository, stack.image_store, interactive_demo=True
        )
        published = publisher.publish(
            merchant_id=merchant_id,
            photo=jpeg_bytes(),
            declared_content_type="image/jpeg",
            price="24.00",
            title=title,
            category="Bowls",
            attested_capture=True,
        )
        return published.item_id

    def test_bootstrap_creates_the_committed_baseline_and_the_local_credential(self) -> None:
        stack, report = bootstrap_demo_runtime(self.root)
        try:
            store = stack.demo_store
            scope = store.scope
            self.assertTrue(report.is_pristine_baseline)
            self.assertEqual(report.items, 90)
            self.assertEqual(report.ready_embeddings, 90)
            self.assertEqual(report.uploaded_items, 0)
            self.assertTrue(report.credential_ok)
            self.assertEqual(report.root, self.root.resolve())
            self.assertEqual(report.database_path, self.root.resolve() / "shopsearch.sqlite3")
            self.assertEqual(report.media_root, self.root.resolve() / "media")
            identity = (
                stack.auth_stores.for_store(store)
                .authenticate(DEMO_USERNAME, DEMO_PASSWORD)
                .identity
            )
            self.assertIsNotNone(identity)
            assert identity is not None
            self.assertEqual(identity.username, DEMO_USERNAME)

            # The committed museum records keep their IDs, prices, images and metadata.
            committed = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, store.configuration())
            stored = {item.item_id: item for item in stack.catalog_repository.published(scope)}
            self.assertEqual(set(stored), {item.item_id for item in committed.items})
            for item in committed.items:
                record = stored[item.item_id]
                self.assertEqual(record.title, item.title)
                self.assertEqual(record.price, item.price)
                self.assertEqual(record.category, item.category)
                self.assertEqual(record.attributes["source_url"], item.attributes["source_url"])
                self.assertEqual(record.attributes["license"], item.attributes["license"])
                self.assertEqual(
                    record.attributes["accession_number"], item.attributes["accession_number"]
                )
                self.assertTrue(record.image_uri)
                self.assertIsNone(record.attributes.get("merchant_upload"))
        finally:
            stack.close()

    def test_second_bootstrap_preserves_local_uploads_and_mutations(self) -> None:
        stack, _ = bootstrap_demo_runtime(self.root)
        item_id = self.publish_one(stack)
        scope = stack.demo_store.scope
        events = stack.catalog_repository.event_count(scope)
        stack.close()

        stack, report = bootstrap_demo_runtime(self.root)
        try:
            self.assertEqual(report.items, 91)
            self.assertEqual(report.uploaded_items, 1)
            self.assertFalse(report.is_pristine_baseline)
            self.assertEqual(stack.catalog_repository.event_count(scope), events)
            state = stack.catalog_repository.item_state(scope, item_id)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.listing_state, ListingState.PUBLISHED)
            self.assertEqual(state.index_state, IndexState.PENDING)
        finally:
            stack.close()

    def test_reset_drops_local_state_and_restores_the_pristine_baseline(self) -> None:
        stack, pristine = bootstrap_demo_runtime(self.root)
        pristine_media = media_digest(pristine.media_root)
        item_id = self.publish_one(stack)
        store = stack.demo_store
        scope = store.scope
        auth = stack.auth_stores.for_store(store)
        session = auth.start_session(auth.list_merchants()[0])
        telemetry = stack.telemetry_stores.for_store(store)
        telemetry.append(
            new_event(
                EventType.HOMEPAGE_VIEWED,
                str(uuid4()),
                scope.store_id,
                {
                    "traffic": TrafficClass.PITCH_DEMO.value,
                    "catalog_version": stack.catalog_repository.catalog_version(scope),
                },
            )
        )
        self.assertEqual(telemetry.count(), 1)
        self.assertNotEqual(media_digest(pristine.media_root), pristine_media)
        stack.close()

        report = reset_demo_runtime(self.root)
        self.assertTrue(report.is_pristine_baseline)
        self.assertEqual(report.items, 90)
        self.assertEqual(report.ready_embeddings, 90)
        self.assertEqual(report.uploaded_items, 0)
        self.assertTrue(report.credential_ok)

        stack, _ = bootstrap_demo_runtime(self.root)
        try:
            self.assertEqual(stack.catalog_repository.item_count(scope), 90)
            self.assertIsNone(stack.catalog_repository.item_state(scope, item_id))
            self.assertEqual(stack.telemetry_stores.for_store(store).count(), 0)
            self.assertIsNone(stack.auth_stores.for_store(store).identify(session.token))
            self.assertEqual(media_digest(pristine.media_root), pristine_media)
        finally:
            stack.close()

    def test_reset_refuses_a_live_demo_process_and_a_foreign_directory(self) -> None:
        stack, _ = bootstrap_demo_runtime(self.root)
        stack.close()
        record_demo_process(self.root, os.getpid())
        self.assertEqual(demo_runtime_in_use(self.root), os.getpid())
        with self.assertRaises(DemoRuntimeError):
            reset_demo_runtime(self.root)
        self.assertTrue(self.root.exists())
        clear_demo_process(self.root)
        self.assertIsNone(demo_runtime_in_use(self.root))

        # A pid file left behind by a crashed demo is stale, not an active runtime.
        (self.root / "demo.pid").write_text("2147483647\n", encoding="utf-8")
        self.assertIsNone(demo_runtime_in_use(self.root))

        foreign = Path(self.directory.name) / "not-the-demo"
        foreign.mkdir()
        with self.assertRaises(DemoRuntimeError):
            reset_demo_runtime(foreign)
        self.assertTrue(foreign.exists())

    def test_reset_touches_only_the_dedicated_demo_root(self) -> None:
        generic = Path(self.directory.name) / "generic-local-runtime"
        generic.mkdir()
        database = generic / "shopsearch.sqlite3"
        database.write_bytes(b"generic-platform-state")
        media = generic / "media"
        media.mkdir()
        kept = media / "kept.jpg"
        kept.write_bytes(b"generic-platform-media")
        stack, _ = bootstrap_demo_runtime(self.root)
        stack.close()

        reset_demo_runtime(self.root)

        self.assertEqual(database.read_bytes(), b"generic-platform-state")
        self.assertEqual(kept.read_bytes(), b"generic-platform-media")
        self.assertTrue(self.root.is_dir())
