"""S10 runtime configuration boundary: env-driven, validated and fail-closed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.runtime.config import (
    BACKUP_ROOT_VARIABLE,
    BIND_HOST_VARIABLE,
    DATABASE_VARIABLE,
    DEVELOPMENT_HOSTS_VARIABLE,
    LOG_LEVEL_VARIABLE,
    MEDIA_ROOT_VARIABLE,
    PORT_VARIABLE,
    STORES_VARIABLE,
    ConfigurationError,
    RuntimeConfig,
)


class RuntimeConfigTest(unittest.TestCase):
    def environment(self, **overrides: str) -> dict[str, str]:
        values = {
            DATABASE_VARIABLE: "/srv/shopsearch/data/shopsearch.sqlite3",
            MEDIA_ROOT_VARIABLE: "/srv/shopsearch/media",
            STORES_VARIABLE: "live-store",
        }
        values.update(overrides)
        return values

    def test_reads_every_documented_variable(self) -> None:
        config = RuntimeConfig.from_environment(
            self.environment(
                **{
                    BIND_HOST_VARIABLE: "127.0.0.2",
                    PORT_VARIABLE: "8100",
                    LOG_LEVEL_VARIABLE: "warning",
                    BACKUP_ROOT_VARIABLE: "/mnt/backup/shopsearch",
                    DEVELOPMENT_HOSTS_VARIABLE: "/etc/shopsearch/development_hosts.json",
                }
            )
        )
        self.assertEqual(config.database_path, Path("/srv/shopsearch/data/shopsearch.sqlite3"))
        self.assertEqual(config.media_root, Path("/srv/shopsearch/media"))
        self.assertEqual(config.store_ids, ("live-store",))
        self.assertEqual(config.bind_host, "127.0.0.2")
        self.assertEqual(config.port, 8100)
        self.assertEqual(config.log_level, "WARNING")
        self.assertEqual(config.backup_root, Path("/mnt/backup/shopsearch"))
        self.assertEqual(
            config.development_hosts_path, Path("/etc/shopsearch/development_hosts.json")
        )
        self.assertNotIn("password", config.describe().lower())

    def test_defaults_are_loopback_and_standard_log_level(self) -> None:
        config = RuntimeConfig.from_environment(self.environment())
        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.port, 8000)
        self.assertEqual(config.log_level, "INFO")
        self.assertIsNone(config.backup_root)
        self.assertIsNone(config.development_hosts_path)

    def test_multiple_stores_are_an_explicit_allowlist(self) -> None:
        config = RuntimeConfig.from_environment(
            self.environment(**{STORES_VARIABLE: " isolation-alpha , isolation-beta "})
        )
        self.assertEqual(config.store_ids, ("isolation-alpha", "isolation-beta"))

    def test_missing_required_configuration_fails_closed(self) -> None:
        for variable in (DATABASE_VARIABLE, MEDIA_ROOT_VARIABLE, STORES_VARIABLE):
            with self.subTest(variable=variable):
                values = self.environment()
                del values[variable]
                with self.assertRaises(ConfigurationError) as caught:
                    RuntimeConfig.from_environment(values)
                self.assertIn(variable, str(caught.exception))
        # Blank values are missing values, not silent defaults.
        with self.assertRaises(ConfigurationError):
            RuntimeConfig.from_environment(self.environment(**{DATABASE_VARIABLE: "   "}))

    def test_invalid_values_are_rejected_with_a_useful_error(self) -> None:
        cases = {
            "port-not-a-number": {PORT_VARIABLE: "http"},
            "port-out-of-range": {PORT_VARIABLE: "70000"},
            "store-id-unsafe": {STORES_VARIABLE: "../escape"},
            "store-list-empty-entry": {STORES_VARIABLE: "live-store,"},
            "store-list-duplicate": {STORES_VARIABLE: "live-store,live-store"},
            "unknown-log-level": {LOG_LEVEL_VARIABLE: "chatty"},
            "blank-bind-host": {BIND_HOST_VARIABLE: "   "},
        }
        for label, overrides in cases.items():
            with self.subTest(case=label), self.assertRaises(ConfigurationError):
                RuntimeConfig.from_environment(self.environment(**overrides))

    def test_local_development_configuration_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = RuntimeConfig.for_local_development(
                database_path=root / "demo.sqlite3",
                media_root=root / "media",
                store_ids=("pitch-demo",),
                port=8018,
            )
        self.assertEqual(config.store_ids, ("pitch-demo",))
        self.assertEqual(config.port, 8018)
        self.assertEqual(config.bind_host, "127.0.0.1")
        with self.assertRaises(ConfigurationError):
            RuntimeConfig.for_local_development(
                database_path=Path("demo.sqlite3"), media_root=Path("media"), store_ids=()
            )

    def test_environment_only_configuration_never_requires_a_secret(self) -> None:
        # No Flask client-side session exists, so there is no secret to invent or
        # commit: required configuration is paths, store IDs and network binding.
        config = RuntimeConfig.from_environment(self.environment())
        self.assertFalse(hasattr(config, "secret_key"))


if __name__ == "__main__":
    unittest.main()
