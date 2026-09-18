"""S10 backup, restore and restart-persistence acceptance tests."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apps.web.storefront import open_platform_stack
from apps.web.wsgi import create_pitch_app
from backend.catalog.store_repository import CatalogRepository, read_snapshot_manifest
from backend.media.image_store import LocalImageStore
from backend.ops.layout import DATABASE_FILENAME, MEDIA_DIRNAME
from backend.ops.runtime_backup import backup_runtime
from backend.ops.runtime_restore import RestoreError, restore_runtime
from backend.stores.repository import StoreRepository
from backend.telemetry.report import summarize_store
from backend.telemetry.sqlite_store import TelemetryStores
from contracts.store import StoreScope
from tests.acceptance.test_merchant_publish import jpeg_bytes
from tests.support.isolation_fixture import (
    ALPHA_STORE_ID,
    SHARED_USERNAME,
    IsolationFixture,
    provision_isolation_stores,
)
from tests.unit.test_pitch import StubEncoder


class BackupRestoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database_path = self.root / "runtime" / "shopsearch.sqlite3"
        self.media_root = self.root / "runtime" / "media"
        self.fixture: IsolationFixture = provision_isolation_stores(
            self.database_path, self.media_root
        )
        self.development_hosts = self.root / "development_hosts.json"
        self.development_hosts.write_text("{}")
        self.backup_root = self.root / "backup"

    def counts(self, database_path: Path, media_root: Path):
        with CatalogRepository.open(database_path) as catalog:
            with StoreRepository.open(database_path) as stores:
                with TelemetryStores.open(database_path) as telemetry:
                    result = {}
                    for store in stores.list_stores():
                        sink = telemetry.for_store(store)
                        result[store.store_id] = {
                            "items": catalog.item_count(store.scope),
                            "images": catalog.image_count(store.scope),
                            "events": catalog.event_count(store.scope),
                            "telemetry": len(sink.events()),
                            "report": summarize_store(sink, store.store_id)["recorded_events"],
                        }
                    return result

    def serve_storefront(self, database_path: Path, media_root: Path):
        stack = open_platform_stack(database_path, media_root)
        self.addCleanup(stack.close)
        app = create_pitch_app(
            encoder=StubEncoder(),
            stack=stack,
            development_hosts_path=self.development_hosts,
            storefronts=self.fixture.storefronts,
        )
        return app.test_client()

    def record_traffic(self) -> None:
        client = self.serve_storefront(self.database_path, self.media_root)
        for side in self.fixture.stores:
            self.assertEqual(client.get("/catalog", base_url=side.url_host).status_code, 200)
            response = client.get("/api/search?q=shared+fixture+object", base_url=side.url_host)
            self.assertEqual(response.status_code, 200)
            self.assertGreater(json.loads(response.data)["count"], 0)

    def test_online_backup_and_clean_directory_restore_reproduce_state(self) -> None:
        self.record_traffic()
        before = self.counts(self.database_path, self.media_root)
        for store_id in self.fixture.storefronts:
            with self.subTest(store=store_id):
                self.assertGreater(before[store_id]["telemetry"], 0)

        # The live database is in WAL mode: a consistent snapshot needs the online API.
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            connection.close()

        result = backup_runtime(
            database_path=self.database_path,
            media_root=self.media_root,
            destination_root=self.backup_root,
        )
        snapshot = self.backup_root / DATABASE_FILENAME
        self.assertTrue(snapshot.is_file())
        self.assertGreaterEqual(result.stores, 2)
        self.assertEqual(result.image_addresses, 6)

        # The snapshot is one self-contained file: it is not in WAL mode, so a
        # single-file restore cannot lose pages to an uncopied sidecar.
        self.assertEqual(
            sorted(path.name for path in self.backup_root.iterdir()),
            sorted([DATABASE_FILENAME, MEDIA_DIRNAME]),
        )
        connection = sqlite3.connect(snapshot)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            connection.close()

        # Every image row in the backed-up database resolves to backed-up bytes. The
        # snapshot is read through the read-only manifest so verification itself cannot
        # rewrite it.
        manifest = read_snapshot_manifest(snapshot)
        self.assertEqual(len(manifest.image_addresses), result.image_addresses)
        mirror = LocalImageStore(self.backup_root / MEDIA_DIRNAME)
        for store_id, sha, variant in manifest.image_addresses:
            with self.subTest(address=sha):
                self.assertTrue(mirror.contains(StoreScope(store_id), sha, variant))

        # Continue running the original application while the backup exists, then
        # close it and restore into a fresh clean directory.
        self.record_traffic()
        after_more_traffic = self.counts(self.database_path, self.media_root)

        restored_root = self.root / "restored"
        restored_database = restored_root / "shopsearch.sqlite3"
        restored_media = restored_root / "media"
        restored = restore_runtime(
            backup_root=self.backup_root,
            database_path=restored_database,
            media_root=restored_media,
        )
        self.assertEqual(restored.stores, result.stores)
        # Counts are verified before serving the restored copy, which would add traffic.
        self.assertEqual(self.counts(restored_database, restored_media), before)

        # The restored runtime serves the storefront, catalog, detail, media and search.
        client = self.serve_storefront(restored_database, restored_media)
        for side in self.fixture.stores:
            with self.subTest(store=side.store.store_id):
                catalog_page = client.get("/catalog", base_url=side.url_host)
                self.assertEqual(catalog_page.status_code, 200)
                for fixture_object in side.objects:
                    self.assertIn(fixture_object.title.encode(), catalog_page.data)
                detail = client.get(f"/items/{side.objects[0].item_id}", base_url=side.url_host)
                self.assertEqual(detail.status_code, 200)
                with CatalogRepository.open(restored_database) as catalog:
                    image = catalog.display_image(side.store.scope, side.objects[0].item_id)
                assert image is not None
                media = client.get(
                    f"/media/{side.store.store_id}/{image.sha256}/{image.variant}",
                    base_url=side.url_host,
                )
                self.assertEqual(media.status_code, 200)
                search = json.loads(
                    client.get("/api/search?q=shared+fixture+object", base_url=side.url_host).data
                )
                self.assertGreater(search["count"], 0)
        # The restored catalog is the snapshot's, not a later state of the original.
        after_serving = self.counts(restored_database, restored_media)
        for store_id, snapshot_counts in before.items():
            with self.subTest(store=store_id):
                self.assertEqual(after_serving[store_id]["items"], snapshot_counts["items"])
                self.assertEqual(after_serving[store_id]["images"], snapshot_counts["images"])
                self.assertEqual(after_serving[store_id]["events"], snapshot_counts["events"])
        self.assertNotEqual(after_more_traffic, before)

    def test_restore_refuses_a_non_empty_destination(self) -> None:
        self.record_traffic()
        backup_runtime(
            database_path=self.database_path,
            media_root=self.media_root,
            destination_root=self.backup_root,
        )
        # Existing database.
        with self.assertRaises(RestoreError):
            restore_runtime(
                backup_root=self.backup_root,
                database_path=self.database_path,
                media_root=self.root / "fresh-media",
            )
        # Existing non-empty media root, with no database.
        occupied = self.root / "occupied-media"
        occupied.mkdir(parents=True)
        (occupied / "stale.bin").write_bytes(b"stale")
        with self.assertRaises(RestoreError):
            restore_runtime(
                backup_root=self.backup_root,
                database_path=self.root / "fresh.sqlite3",
                media_root=occupied,
            )
        # The explicit safe operator action is required and is documented as destructive.
        forced_database = self.root / "forced.sqlite3"
        forced_media = self.root / "forced-media"
        (forced_media / ALPHA_STORE_ID).mkdir(parents=True)
        outcome = restore_runtime(
            backup_root=self.backup_root,
            database_path=forced_database,
            media_root=forced_media,
            allow_existing=True,
        )
        self.assertTrue(outcome.database_path.is_file())

    def test_restore_verifies_media_references(self) -> None:
        self.record_traffic()
        backup_runtime(
            database_path=self.database_path,
            media_root=self.media_root,
            destination_root=self.backup_root,
        )
        # Remove one backed-up blob: the restore must fail rather than pass silently.
        mirrored = self.backup_root / MEDIA_DIRNAME
        victim = next(path for path in sorted(mirrored.rglob("*")) if path.is_file())
        victim.unlink()
        with self.assertRaises(RestoreError):
            restore_runtime(
                backup_root=self.backup_root,
                database_path=self.root / "broken.sqlite3",
                media_root=self.root / "broken-media",
            )

    def test_backup_verification_catches_a_media_gap(self) -> None:
        self.record_traffic()
        # The live media root is missing one referenced blob: the backup must fail.
        store = LocalImageStore(self.media_root)
        victim = next(path for path in sorted(self.media_root.rglob("*")) if path.is_file())
        victim.unlink()
        with self.assertRaises(Exception):
            backup_runtime(
                database_path=self.database_path,
                media_root=self.media_root,
                destination_root=self.root / "incomplete-backup",
            )
        self.assertTrue(store is not None)


class RestartPersistenceTest(unittest.TestCase):
    def test_restart_reopens_catalog_media_events_and_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "shopsearch.sqlite3"
            media_root = root / "media"
            fixture = provision_isolation_stores(database_path, media_root)
            development_hosts = root / "development_hosts.json"
            development_hosts.write_text("{}")

            stack = open_platform_stack(database_path, media_root)
            app = create_pitch_app(
                encoder=StubEncoder(),
                stack=stack,
                development_hosts_path=development_hosts,
                storefronts=fixture.storefronts,
            )
            client = app.test_client()
            login_page = client.get("/manage/login", base_url=fixture.alpha.url_host)
            login_csrf = (
                login_page.data.decode().split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
            )
            login = client.post(
                "/manage/login",
                base_url=fixture.alpha.url_host,
                data={
                    "csrf_token": login_csrf,
                    "username": SHARED_USERNAME,
                    "password": fixture.alpha.password,
                },
            )
            self.assertEqual(login.status_code, 303)
            page = client.get("/manage", base_url=fixture.alpha.url_host)
            csrf = page.data.decode().split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
            published = client.post(
                "/manage/publish",
                base_url=fixture.alpha.url_host,
                data={
                    "csrf_token": csrf,
                    "price": "12.34",
                    "title": "Restart survivor",
                    "category": "Lamps",
                    "photo": (io.BytesIO(jpeg_bytes(size=(64, 48))), "photo.jpg", "image/jpeg"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(published.status_code, 303)
            item_id = published.headers["Location"].split("published=", 1)[1].split("&", 1)[0]
            self.assertEqual(
                client.get("/catalog", base_url=fixture.alpha.url_host).status_code, 200
            )
            with CatalogRepository.open(database_path) as catalog:
                image = catalog.current_image(fixture.alpha.store.scope, item_id)
                before = (
                    catalog.item_count(fixture.alpha.store.scope),
                    catalog.image_count(fixture.alpha.store.scope),
                    catalog.event_count(fixture.alpha.store.scope),
                )
            assert image is not None
            with TelemetryStores.open(database_path) as telemetry:
                telemetry_before = len(telemetry.for_store(fixture.alpha.store).events())
            self.assertGreater(telemetry_before, 0)

            # Stop every repository and server handle, then reopen the same paths.
            stack.close()
            app = None

            reopened = open_platform_stack(database_path, media_root)
            self.addCleanup(reopened.close)
            with CatalogRepository.open(database_path) as catalog:
                self.assertEqual(
                    (
                        catalog.item_count(fixture.alpha.store.scope),
                        catalog.image_count(fixture.alpha.store.scope),
                        catalog.event_count(fixture.alpha.store.scope),
                    ),
                    before,
                )
                self.assertIsNotNone(catalog.get_published(fixture.alpha.store.scope, item_id))
            with TelemetryStores.open(database_path) as telemetry:
                self.assertEqual(
                    len(telemetry.for_store(fixture.alpha.store).events()), telemetry_before
                )
            restored_client = create_pitch_app(
                encoder=StubEncoder(),
                stack=reopened,
                development_hosts_path=development_hosts,
                storefronts=fixture.storefronts,
            ).test_client()
            catalog_page = restored_client.get("/catalog", base_url=fixture.alpha.url_host)
            self.assertIn(b"Restart survivor", catalog_page.data)
            media = restored_client.get(
                f"/media/{fixture.alpha.store.store_id}/{image.sha256}/{image.variant}",
                base_url=fixture.alpha.url_host,
            )
            self.assertEqual(media.status_code, 200)


if __name__ == "__main__":
    unittest.main()
