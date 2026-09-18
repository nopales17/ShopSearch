"""Typed, environment-driven runtime configuration for the deployed platform.

Production startup reads these `SHOPSEARCH_*` variables and fails closed when the
required ones are missing or invalid: there is no silent fallback to the repository
defaults or to the pitch demo. The demo/development path is an explicit command that
builds its own configuration, so demo seeding is never a side effect of startup.

No secret is invented here. This application has no Flask client-side session and no
committed credential: merchant passwords are provisioned interactively through
`backend.auth.cli`, and sessions are opaque tokens stored hashed in the database.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ENV_PREFIX = "SHOPSEARCH_"
DATABASE_VARIABLE = f"{ENV_PREFIX}DATABASE"
MEDIA_ROOT_VARIABLE = f"{ENV_PREFIX}MEDIA_ROOT"
STORES_VARIABLE = f"{ENV_PREFIX}STORES"
BIND_HOST_VARIABLE = f"{ENV_PREFIX}BIND_HOST"
PORT_VARIABLE = f"{ENV_PREFIX}PORT"
BACKUP_ROOT_VARIABLE = f"{ENV_PREFIX}BACKUP_ROOT"
LOG_LEVEL_VARIABLE = f"{ENV_PREFIX}LOG_LEVEL"
DEVELOPMENT_HOSTS_VARIABLE = f"{ENV_PREFIX}DEVELOPMENT_HOSTS"

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_LOG_LEVEL = "INFO"

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")


class ConfigurationError(ValueError):
    """Raised when runtime configuration is absent, malformed or unsafe."""


@dataclass(frozen=True)
class RuntimeConfig:
    """One process's validated runtime settings."""

    database_path: Path
    media_root: Path
    store_ids: tuple[str, ...]
    bind_host: str = DEFAULT_BIND_HOST
    port: int = DEFAULT_PORT
    log_level: str = DEFAULT_LOG_LEVEL
    backup_root: Path | None = None
    development_hosts_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.store_ids:
            raise ConfigurationError(f"{STORES_VARIABLE} must list at least one store ID")
        for store_id in self.store_ids:
            if not _IDENTIFIER.fullmatch(store_id):
                raise ConfigurationError(f"{STORES_VARIABLE} contains an invalid store ID")
        if not self.bind_host or not self.bind_host.strip():
            raise ConfigurationError(f"{BIND_HOST_VARIABLE} must be a non-empty host")
        if isinstance(self.port, bool) or not 1 <= int(self.port) <= 65535:
            raise ConfigurationError(f"{PORT_VARIABLE} must be a port between 1 and 65535")
        if self.log_level.upper() not in logging.getLevelNamesMapping():
            raise ConfigurationError(f"{LOG_LEVEL_VARIABLE} must be a standard logging level name")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "RuntimeConfig":
        """Read and validate production configuration, or raise `ConfigurationError`."""

        values = os.environ if environ is None else environ
        database = _required_path(values, DATABASE_VARIABLE, "database file")
        media_root = _required_path(values, MEDIA_ROOT_VARIABLE, "media directory")
        store_ids = _required_stores(values)
        raw_port = values.get(PORT_VARIABLE, str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ConfigurationError(f"{PORT_VARIABLE} must be an integer port") from error
        raw_host = values.get(BIND_HOST_VARIABLE)
        bind_host = DEFAULT_BIND_HOST if raw_host is None else raw_host.strip()
        if not bind_host:
            raise ConfigurationError(f"{BIND_HOST_VARIABLE} must not be blank")
        return cls(
            database_path=database,
            media_root=media_root,
            store_ids=store_ids,
            bind_host=bind_host,
            port=port,
            log_level=_log_level(values),
            backup_root=_optional_path(values, BACKUP_ROOT_VARIABLE),
            development_hosts_path=_optional_path(values, DEVELOPMENT_HOSTS_VARIABLE),
        )

    @classmethod
    def for_local_development(
        cls,
        *,
        database_path: Path,
        media_root: Path,
        store_ids: tuple[str, ...],
        bind_host: str = DEFAULT_BIND_HOST,
        port: int = DEFAULT_PORT,
        log_level: str = DEFAULT_LOG_LEVEL,
        backup_root: Path | None = None,
        development_hosts_path: Path | None = None,
    ) -> "RuntimeConfig":
        """Explicit development configuration; never used as a production fallback."""

        return cls(
            database_path=Path(database_path),
            media_root=Path(media_root),
            store_ids=tuple(store_ids),
            bind_host=bind_host,
            port=port,
            log_level=log_level,
            backup_root=None if backup_root is None else Path(backup_root),
            development_hosts_path=(
                None if development_hosts_path is None else Path(development_hosts_path)
            ),
        )

    def describe(self) -> str:
        """Operator-facing summary that never includes secrets."""

        return (
            f"database={self.database_path} media_root={self.media_root} "
            f"stores={','.join(self.store_ids)} bind={self.bind_host}:{self.port} "
            f"log_level={self.log_level.upper()}"
        )


def _required_path(values: Mapping[str, str], variable: str, description: str) -> Path:
    raw = values.get(variable, "").strip()
    if not raw:
        raise ConfigurationError(
            f"{variable} is required: set it to the {description} this process must use"
        )
    return Path(raw).expanduser()


def _optional_path(values: Mapping[str, str], variable: str) -> Path | None:
    raw = values.get(variable, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _required_stores(values: Mapping[str, str]) -> tuple[str, ...]:
    raw = values.get(STORES_VARIABLE, "").strip()
    if not raw:
        raise ConfigurationError(
            f"{STORES_VARIABLE} is required: list the store IDs this process serves, "
            "comma separated; there is no default store"
        )
    store_ids = tuple(part.strip() for part in raw.split(","))
    if any(not store_id for store_id in store_ids):
        raise ConfigurationError(f"{STORES_VARIABLE} must not contain empty entries")
    if len(set(store_ids)) != len(store_ids):
        raise ConfigurationError(f"{STORES_VARIABLE} must not repeat a store ID")
    return store_ids


def _log_level(values: Mapping[str, str]) -> str:
    return values.get(LOG_LEVEL_VARIABLE, DEFAULT_LOG_LEVEL).strip().upper() or DEFAULT_LOG_LEVEL
