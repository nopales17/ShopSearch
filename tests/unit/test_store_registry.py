from __future__ import annotations

import ast
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.platform.paths import REPOSITORY_ROOT as ROOT
from backend.stores import cli
from backend.stores.config import load_store_config, load_store_config_in_memory
from backend.stores.hostname import InvalidHostnameError, normalize_hostname
from backend.stores.repository import DuplicateHostnameError, StoreRepository
from backend.stores.resolver import DevelopmentHostsError, HostResolver, load_development_hosts
from backend.stores.seed import seed_store
from backend.stores.validation import StoreValidationError, validate_store
from contracts.store import StoreScope


def demo_document() -> dict[str, object]:
    return json.loads(DEFAULT_DEMO_STORE_PATH.read_text())


class MigrationTest(unittest.TestCase):
    def test_empty_database_applies_idempotently_and_records_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = platform_db.connect(Path(directory) / "shopsearch.sqlite3")
            try:
                applied = platform_db.apply_migrations(connection)
                migrations = (
                    "0001_store_registry.sql",
                    "0002_catalog_and_media.sql",
                    "0003_embeddings_and_index_generations.sql",
                    "0004_telemetry_events.sql",
                    "0005_merchant_auth.sql",
                    "0006_image_source_uniqueness.sql",
                )
                self.assertEqual(applied, migrations)
                self.assertEqual(
                    platform_db.applied_versions(connection),
                    migrations,
                )
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertLessEqual(
                    {
                        "stores",
                        "store_domains",
                        "items",
                        "images",
                        "item_events",
                        "embeddings",
                        "store_generations",
                        "telemetry_events",
                        "merchants",
                        "merchant_sessions",
                    },
                    tables,
                )
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                indexes = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }
                self.assertIn("images_store_source_idx", indexes)
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal"
                )
                self.assertEqual(platform_db.apply_migrations(connection), ())
                self.assertEqual(
                    platform_db.applied_versions(connection),
                    migrations,
                )
            finally:
                connection.close()


class HostnameNormalizationTest(unittest.TestCase):
    def test_case_port_trailing_dot_and_idna_normalize_together(self) -> None:
        for raw in [
            "Shop.Example.COM:8443",
            "shop.example.com.",
            "shop.example.com",
            " SHOP.EXAMPLE.COM ",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_hostname(raw), "shop.example.com")
        self.assertEqual(
            normalize_hostname("xn--mnchen-3ya.example"), normalize_hostname("MÜNCHEN.example")
        )

    def test_rejects_wildcards_and_malformed_hosts(self) -> None:
        for raw in ["", "   ", "*", "*.example.com", "bad/host", "has space"]:
            with self.subTest(raw=raw), self.assertRaises(InvalidHostnameError):
                normalize_hostname(raw)


class StoreRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.repository = StoreRepository.open(self.root / "shopsearch.sqlite3")
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.repository.close)

    def test_demo_store_seeds_once_and_stays_idempotent(self) -> None:
        store = seed_store(self.repository, DEFAULT_DEMO_STORE_PATH)
        second = seed_store(self.repository, DEFAULT_DEMO_STORE_PATH)
        self.assertEqual(store, second)
        self.assertEqual(self.repository.domains_for(store.scope), ("form-and-field.example",))
        self.assertEqual(len(self.repository.list_stores()), 1)
        self.assertTrue(store.is_demo)
        self.assertEqual(store.configuration().store_id, "pitch-demo")

    def test_creating_a_store_with_a_domain_rejects_duplicate_hostnames(self) -> None:
        document = demo_document()
        document["store_id"] = "second-store"
        document["is_demo"] = False
        document["domains"] = ["Shop.Example.com"]
        store, domains = load_store_config_in_memory(document)
        self.repository.create_store(store, domains)
        resolved = self.repository.find_store_by_hostname("shop.example.com.")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.store_id, "second-store")

        other = dict(document)
        other["store_id"] = "third-store"
        with self.assertRaises(DuplicateHostnameError):
            self.repository.create_store(*load_store_config_in_memory(other))
        with self.assertRaises(DuplicateHostnameError):
            self.repository.create_store(store, ("shop.example.com", "SHOP.example.com"))

    def test_demo_store_disclosures_are_mandatory(self) -> None:
        store = load_store_config(DEFAULT_DEMO_STORE_PATH)[0]
        validate_store(store)
        for field, value in [
            ("footer_disclosure", "Brand new copy with no required assertions."),
            ("catalog_disclaimer", "Everything is available."),
            ("public_claim", "Great things, always in stock."),
            ("credits_copy_html", "Photos used with permission."),
        ]:
            with self.subTest(field=field), self.assertRaises(StoreValidationError):
                validate_store(
                    replace(store, presentation=replace(store.presentation, **{field: value}))
                )
        with self.assertRaises(StoreValidationError):
            self.repository.create_store(
                replace(
                    store,
                    presentation=replace(store.presentation, footer_disclosure="No disclosures."),
                ),
                ("unused.example",),
            )

    def test_cli_creates_a_store_and_rejects_a_duplicate_hostname(self) -> None:
        document = demo_document()
        document["store_id"] = "cli-store"
        document["is_demo"] = False
        document["domains"] = []
        config = self.root / "cli-store.json"
        config.write_text(json.dumps(document))
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = cli.main(
                [
                    "--database",
                    str(self.root / "shopsearch.sqlite3"),
                    "create",
                    "--config",
                    str(config),
                    "--domain",
                    "Shop.Example.COM:8443",
                ]
            )
        self.assertEqual(exit_code, 0)
        resolved = self.repository.find_store_by_hostname("shop.example.com")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.store_id, "cli-store")

        duplicate = dict(document)
        duplicate["store_id"] = "cli-store-two"
        duplicate_config = self.root / "cli-store-two.json"
        duplicate_config.write_text(json.dumps(duplicate))
        with contextlib.redirect_stderr(io.StringIO()):
            duplicate_exit = cli.main(
                [
                    "--database",
                    str(self.root / "shopsearch.sqlite3"),
                    "create",
                    "--config",
                    str(duplicate_config),
                    "--domain",
                    "shop.example.com",
                ]
            )
        self.assertEqual(duplicate_exit, 1)


class HostResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.repository = StoreRepository.open(self.root / "shopsearch.sqlite3")
        seed_store(self.repository, DEFAULT_DEMO_STORE_PATH)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.repository.close)

    def test_registered_hostname_variants_resolve_to_one_store(self) -> None:
        store = seed_store(self.repository, DEFAULT_DEMO_STORE_PATH)
        self.repository.add_domain(store.scope, "shop.example.com")
        resolver = HostResolver(self.repository)
        expected = store.scope
        hosts = ["Shop.Example.COM:8443", "shop.example.com.", "shop.example.com"]
        for host in hosts:
            with self.subTest(host=host):
                self.assertEqual(resolver.resolve(host), expected)

    def test_unknown_hosts_never_fall_back_to_a_store(self) -> None:
        resolver = HostResolver(self.repository, {"localhost": "pitch-demo"})
        self.assertEqual(resolver.resolve("localhost:5000"), StoreScope("pitch-demo"))
        for host in [None, "", "unknown.example", "localhost.evil.example", "127.0.0.2:8000"]:
            with self.subTest(host=host):
                self.assertIsNone(resolver.resolve(host))

    def test_development_map_rejects_wildcards_and_unknown_store_ids(self) -> None:
        wildcard = self.root / "wildcard.json"
        wildcard.write_text(json.dumps({"*": "pitch-demo"}))
        with self.assertRaises(DevelopmentHostsError):
            load_development_hosts(wildcard)
        unknown = self.root / "unknown.json"
        unknown.write_text(json.dumps({"localhost": "not a store id"}))
        with self.assertRaises(ValueError):
            load_development_hosts(unknown)
        resolver = HostResolver(self.repository, {"missing.example": "absent-store"})
        self.assertIsNone(resolver.resolve("missing.example"))


class PersistenceImportBoundaryTest(unittest.TestCase):
    """Only the persistence layer may import sqlite3 or the connection factory.

    ADR-0005 §2 rejects a static "every SQL statement mentions store_id" grep as
    brittle. This test asserts the boundary instead: `sqlite3` and the raw connection
    factory stay inside the repository layer, and no web, view, search, tool or
    experiment module reaches for a connection of its own. Tests may open raw
    connections for schema-level adversarial proof; application code may not.
    """

    ALLOWED = {
        "backend/platform/db.py",
        "backend/stores/repository.py",
        "backend/catalog/store_repository.py",
        "backend/telemetry/sqlite_store.py",
        "backend/auth/repository.py",
    }
    # `backend/auth/service.py` builds each store's `MerchantRepository` around a
    # `Database` handle but executes no SQL itself; the test below pins that fact.
    RAW_FACTORY_ALLOWED = ALLOWED | {"backend/auth/service.py"}

    # Attributes that hand out a connection or the connection factory itself.
    RAW_FACTORY_ATTRIBUTES = frozenset({"Database", "connect", "apply_migrations", "connect"})
    SCANNED_PACKAGES = ("apps", "backend", "contracts", "tools", "experiments")

    def scanned_modules(self) -> list[tuple[str, Path]]:
        return [
            (path.relative_to(ROOT).as_posix(), path)
            for package in self.SCANNED_PACKAGES
            for path in sorted((ROOT / package).rglob("*.py"))
        ]

    def test_sqlite3_and_the_raw_connection_factory_stay_in_the_persistence_layer(self) -> None:
        sqlite_offenders: list[str] = []
        factory_offenders: list[str] = []
        for relative, path in self.scanned_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            aliases = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "sqlite3" and relative not in self.ALLOWED:
                            sqlite_offenders.append(f"{relative}: imports sqlite3")
                        if alias.name == "backend.platform.db":
                            aliases.add(alias.asname or "db")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if relative not in self.ALLOWED and module.split(".")[0] == "sqlite3":
                        sqlite_offenders.append(f"{relative}: imports {module}")
                    if relative not in self.RAW_FACTORY_ALLOWED and module == "backend.platform.db":
                        factory_offenders.append(f"{relative}: imports {module}")
                    elif module == "backend.platform":
                        for alias in node.names:
                            if alias.name == "db":
                                aliases.add(alias.asname or "db")
            for node in ast.walk(tree):
                if (
                    relative not in self.RAW_FACTORY_ALLOWED
                    and isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in aliases
                    and node.attr in self.RAW_FACTORY_ATTRIBUTES
                ):
                    factory_offenders.append(f"{relative}: {node.value.id}.{node.attr}")
        self.assertEqual(sorted(set(sqlite_offenders)), [], "sqlite3 escaped the repository layer")
        self.assertEqual(
            sorted(set(factory_offenders)), [], "the connection factory escaped its layer"
        )
        self.assertIn("import sqlite3", (ROOT / "backend/platform/db.py").read_text())

    def test_the_one_connection_factory_exception_executes_no_sql(self) -> None:
        module = (ROOT / "backend/auth/service.py").read_text(encoding="utf-8")
        self.assertIn("platform_db.Database", module)
        for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE "):
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword, module)

    def test_the_boundary_scans_application_code_only(self) -> None:
        scanned = {relative for relative, _ in self.scanned_modules()}
        self.assertTrue(any(relative.startswith("apps/") for relative in scanned))
        self.assertTrue(any(relative.startswith("backend/search/") for relative in scanned))
        self.assertFalse(any(relative.startswith("tests/") for relative in scanned))
        for relative in self.ALLOWED:
            self.assertIn(relative, scanned)
