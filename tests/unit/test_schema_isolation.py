"""S9 schema audit: every store-scoped table and its isolation mechanism.

The audit enumerates the whole schema, so a new store-scoped table must be added here
with its isolation mechanism. Findings for the S2-S8 tables:

| table               | isolation mechanism                                                      |
|---------------------|-------------------------------------------------------------------------|
| `stores`            | primary key `store_id`; the scope root every other row resolves through    |
| `store_domains`     | `hostname` primary key (one hostname resolves to exactly one store) plus a |
|                     | foreign key to `stores(store_id)`                                         |
| `items`             | primary key `(store_id, item_id)` plus FK `store_id -> stores(store_id)`   |
| `images`            | primary key `(store_id, image_id)`, `UNIQUE (store_id, item_id, variant)`, |
|                     | composite FK `(store_id, item_id) -> items`                               |
| `item_events`       | primary key `(store_id, event_id)`, composite FK `(store_id, item_id)`     |
| `store_generations` | primary key `store_id` plus FK to `stores`                                |
| `embeddings`        | primary key `(store_id, item_id)`, composite FK `(store_id, item_id)`      |
| `telemetry_events`  | primary key `(store_id, event_id)` plus FK `store_id -> stores(store_id)`  |
| `merchants`         | primary key `(store_id, merchant_id)`, `UNIQUE (store_id, username)`,      |
|                     | FK `store_id -> stores(store_id)`                                        |
| `merchant_sessions` | primary key `(store_id, token_sha256)`, composite FK                       |
|                     | `(store_id, merchant_id) -> merchants`                                    |

Direct store-owned rows reference `stores(store_id)`; only rows with a real parent
relationship carry a composite key, so no artificial composite foreign key is added.
These tests import `sqlite3` and open a raw connection on purpose: they are the
schema-level adversarial proof. They never ship in an application path, and the
persistence import boundary keeps `sqlite3` out of `apps`, `backend`, `contracts`,
`tools` and `experiments`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.catalog.store_repository import CatalogRepository
from backend.platform import db as platform_db
from contracts.store import StoreScope
from tests.support.isolation_fixture import (
    ALPHA_ONLY_ITEM_ID,
    ALPHA_STORE_ID,
    BETA_STORE_ID,
    SHARED_ITEM_ID,
    IsolationFixture,
    provision_isolation_stores,
)

# Every table the schema creates, so a new table cannot escape the audit.
EXPECTED_TABLES = {
    "schema_migrations",
    "stores",
    "store_domains",
    "items",
    "images",
    "item_events",
    "store_generations",
    "embeddings",
    "telemetry_events",
    "merchants",
    "merchant_sessions",
}

# Tables that own a `store_id` column directly.
STORE_SCOPED_TABLES = (
    "store_domains",
    "items",
    "images",
    "item_events",
    "store_generations",
    "embeddings",
    "telemetry_events",
    "merchants",
    "merchant_sessions",
)

# Child rows with a real parent: the foreign key must carry `store_id` on both sides.
CHILD_RELATIONSHIPS = {
    "images": ("items", ("store_id", "item_id")),
    "item_events": ("items", ("store_id", "item_id")),
    "embeddings": ("items", ("store_id", "item_id")),
    "merchant_sessions": ("merchants", ("store_id", "merchant_id")),
}

# Direct store-owned rows reference the scope root rather than a fabricated parent.
DIRECT_STORE_REFERENCES = (
    "store_domains",
    "items",
    "store_generations",
    "telemetry_events",
    "merchants",
)

INSERT_IMAGE = (
    "INSERT INTO images (store_id, image_id, item_id, variant, sha256, source_sha256, "
    "media_type, width, height, byte_size, capture_time, capture_time_source, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, 'image/jpeg', 1, 1, 1, NULL, 'unknown', ?)"
)
INSERT_EVENT = (
    "INSERT INTO item_events (store_id, event_id, item_id, event_type, actor, occurred_at, "
    "after_json) VALUES (?, ?, ?, 'tampered', 'attacker', ?, '{}')"
)
INSERT_EMBEDDING = (
    "INSERT INTO embeddings (store_id, item_id, dim, model_id, model_revision, image_sha256, "
    "vector, created_at, updated_at) VALUES (?, ?, 1, 'm', 'r', ?, ?, ?, ?)"
)
INSERT_SESSION = (
    "INSERT INTO merchant_sessions (store_id, token_sha256, merchant_id, csrf_token, "
    "issued_at, expires_at) VALUES (?, ?, ?, 'csrf', ?, ?)"
)
STAMP = "2026-09-18T00:00:00+00:00"


class SchemaIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database_path = root / "shopsearch.sqlite3"
        self.fixture: IsolationFixture = provision_isolation_stores(
            self.database_path, root / "media"
        )
        self.connection = platform_db.connect(self.database_path)
        self.addCleanup(self.connection.close)

    # -- introspection helpers ----------------------------------------------

    def tables(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row["name"]) for row in rows}

    def columns(self, table: str) -> tuple[str, ...]:
        return tuple(
            str(row["name"]) for row in self.connection.execute(f"PRAGMA table_info({table})")
        )

    def primary_key(self, table: str) -> tuple[str, ...]:
        keyed = sorted(
            (int(row["pk"]), str(row["name"]))
            for row in self.connection.execute(f"PRAGMA table_info({table})")
            if int(row["pk"]) > 0
        )
        return tuple(name for _, name in keyed)

    def foreign_keys(self, table: str) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
        grouped: dict[int, list[sqlite3.Row]] = {}
        for row in self.connection.execute(f"PRAGMA foreign_key_list({table})"):
            grouped.setdefault(int(row["id"]), []).append(row)
        relationships = []
        for identifier in sorted(grouped):
            rows = sorted(grouped[identifier], key=lambda row: int(row["seq"]))
            relationships.append(
                (
                    str(rows[0]["table"]),
                    tuple(str(row["from"]) for row in rows),
                    tuple(str(row["to"]) for row in rows),
                )
            )
        return relationships

    def unique_indexes(self, table: str) -> set[tuple[str, ...]]:
        indexes: set[tuple[str, ...]] = set()
        for row in self.connection.execute(f"PRAGMA index_list({table})"):
            if not int(row["unique"]):
                continue
            name = str(row["name"])
            indexes.add(
                tuple(
                    str(info["name"])
                    for info in self.connection.execute(f"PRAGMA index_info({name})")
                )
            )
        return indexes

    def stored_image(self, store_id: str, item_id: str):
        with CatalogRepository.open(self.database_path) as catalog:
            return catalog.current_image(StoreScope(store_id), item_id)

    def insert(self, statement: str, parameters: tuple[object, ...]) -> None:
        with self.connection:
            self.connection.execute(statement, parameters)

    # -- audit ---------------------------------------------------------------

    def test_the_audit_covers_every_table_in_the_schema(self) -> None:
        self.assertEqual(self.tables(), EXPECTED_TABLES)

    def test_every_store_scoped_table_carries_the_store_scope(self) -> None:
        self.assertIn("store_id", self.primary_key("stores"))
        self.assertEqual(self.primary_key("items"), ("store_id", "item_id"))
        self.assertEqual(self.primary_key("images"), ("store_id", "image_id"))
        self.assertEqual(self.primary_key("item_events"), ("store_id", "event_id"))
        self.assertEqual(self.primary_key("embeddings"), ("store_id", "item_id"))
        self.assertEqual(self.primary_key("telemetry_events"), ("store_id", "event_id"))
        self.assertEqual(self.primary_key("merchants"), ("store_id", "merchant_id"))
        self.assertEqual(self.primary_key("merchant_sessions"), ("store_id", "token_sha256"))
        self.assertEqual(self.primary_key("store_generations"), ("store_id",))
        for table in STORE_SCOPED_TABLES:
            with self.subTest(table=table):
                self.assertIn("store_id", self.columns(table))

    def test_child_foreign_keys_include_store_id(self) -> None:
        for child, (parent, expected) in CHILD_RELATIONSHIPS.items():
            with self.subTest(child=child):
                self.assertEqual(self.primary_key(parent), expected)
                matches = [
                    relationship
                    for relationship in self.foreign_keys(child)
                    if relationship[0] == parent
                ]
                self.assertEqual(len(matches), 1, f"{child} must reference {parent}")
                _, local_columns, parent_columns = matches[0]
                self.assertEqual(local_columns, expected)
                self.assertEqual(parent_columns, expected)
                self.assertIn("store_id", local_columns)

    def test_direct_store_owned_rows_reference_the_registry(self) -> None:
        for table in DIRECT_STORE_REFERENCES:
            with self.subTest(table=table):
                targets = {target for target, _, _ in self.foreign_keys(table)}
                self.assertIn("stores", targets)
        # Child tables reach `stores` through their composite parent relationship.
        for table, (parent, _) in CHILD_RELATIONSHIPS.items():
            with self.subTest(table=table):
                targets = {target for target, _, _ in self.foreign_keys(table)}
                self.assertEqual(targets, {parent})

    def test_store_scoped_uniqueness_is_per_store(self) -> None:
        self.assertIn(("store_id", "username"), self.unique_indexes("merchants"))
        self.assertIn(("store_id", "item_id", "variant"), self.unique_indexes("images"))
        self.assertIn(("store_id", "source_sha256", "variant"), self.unique_indexes("images"))

    # -- adversarial schema writes ------------------------------------------

    def test_cross_store_child_rows_are_rejected_by_the_schema(self) -> None:
        # A parent that exists only in store A: the deliberate shared item ID cannot
        # be used here because it legitimately exists in both stores.
        alpha_item = ALPHA_ONLY_ITEM_ID
        alpha_merchant = self.fixture.alpha.merchant.merchant_id
        attempts = {
            "image->item": (
                INSERT_IMAGE,
                (
                    BETA_STORE_ID,
                    "cross-store-image",
                    alpha_item,
                    "display",
                    "a" * 64,
                    "b" * 64,
                    STAMP,
                ),
            ),
            "event->item": (
                INSERT_EVENT,
                (BETA_STORE_ID, "cross-store-event", alpha_item, STAMP),
            ),
            "embedding->item": (
                INSERT_EMBEDDING,
                (BETA_STORE_ID, alpha_item, "a" * 64, b"\x00\x00\x80?", STAMP, STAMP),
            ),
            "session->merchant": (
                INSERT_SESSION,
                (BETA_STORE_ID, "c" * 64, alpha_merchant, STAMP, STAMP),
            ),
        }
        for label, (statement, parameters) in attempts.items():
            with self.subTest(attempt=label):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(statement, parameters)

    def test_unknown_store_and_shared_hostname_rows_are_rejected(self) -> None:
        order = sorted(self.fixture.stores, key=lambda side: side.store.store_id)
        first, second = order
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                "INSERT INTO store_generations (store_id, catalog_generation, index_generation, "
                "updated_at) VALUES ('no-such-store', 0, 0, ?)",
                (STAMP,),
            )
        # One hostname resolves to exactly one store, enforced by the primary key.
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                "INSERT INTO store_domains (hostname, store_id, created_at) VALUES (?, ?, ?)",
                (first.host, second.store.store_id, STAMP),
            )

    def test_identical_source_bytes_are_independent_store_scoped_addresses(self) -> None:
        alpha_image = self.stored_image(ALPHA_STORE_ID, SHARED_ITEM_ID)
        beta_image = self.stored_image(BETA_STORE_ID, SHARED_ITEM_ID)
        assert alpha_image is not None and beta_image is not None
        # One deliberate overlap: identical source bytes, identical stored address.
        self.assertEqual(alpha_image.source_sha256, beta_image.source_sha256)
        self.assertEqual(alpha_image.sha256, beta_image.sha256)

        # The same store cannot represent those bytes twice for one variant...
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                INSERT_IMAGE,
                (
                    ALPHA_STORE_ID,
                    "duplicate-source-image",
                    SHARED_ITEM_ID,
                    "display",
                    "e" * 64,
                    alpha_image.source_sha256,
                    STAMP,
                ),
            )
        # ...while a different variant may reuse them, and the other store already does.
        self.insert(
            INSERT_IMAGE,
            (
                ALPHA_STORE_ID,
                "variant-image",
                SHARED_ITEM_ID,
                "thumb",
                "f" * 64,
                alpha_image.source_sha256,
                STAMP,
            ),
        )
        rows = self.connection.execute(
            "SELECT store_id, variant FROM images WHERE source_sha256 = ? ORDER BY store_id",
            (alpha_image.source_sha256,),
        ).fetchall()
        self.assertEqual(
            {(str(row["store_id"]), str(row["variant"])) for row in rows},
            {(ALPHA_STORE_ID, "display"), (ALPHA_STORE_ID, "thumb"), (BETA_STORE_ID, "display")},
        )
