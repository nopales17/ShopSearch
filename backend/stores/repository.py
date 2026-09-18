"""Store registry persistence. The only place store SQL and sqlite3 live.

Web, view, ranking and tooling code receive this repository, never a connection
(ADR-0005 §2). Every method that reads or writes store data is store-scoped; the
only unscoped lookup is hostname resolution, which is how a scope is obtained.

The production HTTP adapter is Waitress, which serves requests on multiple
threads, so connections are thread-local (SQLite connections are not shareable
across threads) and kept for the life of the repository.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from backend.platform import db as platform_db
from backend.platform.db import utc_now
from backend.stores.config import presentation_from_mapping
from backend.stores.hostname import normalize_hostname
from backend.stores.validation import StoreValidationError, validate_store
from contracts.store import Store, StoreScope


class StoreNotFoundError(LookupError):
    """Raised when a store scope does not resolve to a registered store."""


class DuplicateHostnameError(ValueError):
    """Raised when a hostname is already registered to another store."""


class StoreRepository:
    """Typed access to `stores` and `store_domains`."""

    @classmethod
    def open(cls, database_path: Path | str) -> "StoreRepository":
        repository = cls(database_path)
        platform_db.apply_migrations(repository._connection())
        return repository

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = str(database_path)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()

    def close(self) -> None:
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            connection.close()
        if getattr(self._local, "connection", None) is not None:
            self._local.connection = None

    def __enter__(self) -> "StoreRepository":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def create_store(self, store: Store, domains: Sequence[str]) -> Store:
        """Create a store and register its hostnames, rejecting duplicates."""

        validate_store(store)
        normalized = self._normalized_domains(domains)
        connection = self._connection()
        now = utc_now()
        with connection:
            try:
                connection.execute(
                    """
                    INSERT INTO stores (
                        store_id, display_name, currency, timezone, is_demo,
                        catalog_path, presentation_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        store.store_id,
                        store.display_name,
                        store.currency,
                        store.timezone,
                        int(store.is_demo),
                        store.catalog_path,
                        json.dumps(asdict(store.presentation), sort_keys=True),
                        store.created_at or now,
                    ),
                )
                for hostname in normalized:
                    connection.execute(
                        "INSERT INTO store_domains (hostname, store_id, created_at) "
                        "VALUES (?, ?, ?)",
                        (hostname, store.store_id, now),
                    )
            except sqlite3.IntegrityError as error:
                raise DuplicateHostnameError(
                    "store or hostname already exists in the registry"
                ) from error
        return self.get_store(store.scope)

    def add_domain(self, scope: StoreScope, hostname: str) -> None:
        self.get_store(scope)
        normalized = normalize_hostname(hostname)
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO store_domains (hostname, store_id, created_at) VALUES (?, ?, ?)",
                    (normalized, scope.store_id, utc_now()),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateHostnameError(f"hostname already registered: {normalized}") from error

    def get_store(self, scope: StoreScope) -> Store:
        row = (
            self._connection()
            .execute("SELECT * FROM stores WHERE store_id = ?", (scope.store_id,))
            .fetchone()
        )
        if row is None:
            raise StoreNotFoundError(f"no store registered for {scope.store_id}")
        return self._store(row)

    def find_store(self, scope: StoreScope) -> Store | None:
        try:
            return self.get_store(scope)
        except StoreNotFoundError:
            return None

    def find_store_by_hostname(self, hostname: str) -> Store | None:
        normalized = normalize_hostname(hostname)
        row = (
            self._connection()
            .execute(
                "SELECT stores.* FROM store_domains "
                "JOIN stores ON stores.store_id = store_domains.store_id "
                "WHERE store_domains.hostname = ?",
                (normalized,),
            )
            .fetchone()
        )
        return None if row is None else self._store(row)

    def domains_for(self, scope: StoreScope) -> tuple[str, ...]:
        self.get_store(scope)
        rows = (
            self._connection()
            .execute(
                "SELECT hostname FROM store_domains WHERE store_id = ? ORDER BY hostname",
                (scope.store_id,),
            )
            .fetchall()
        )
        return tuple(row["hostname"] for row in rows)

    def list_stores(self) -> tuple[Store, ...]:
        rows = self._connection().execute("SELECT * FROM stores ORDER BY store_id").fetchall()
        return tuple(self._store(row) for row in rows)

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = platform_db.connect(self._database_path)
            platform_db.apply_migrations(connection)
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def _store(self, row: sqlite3.Row) -> Store:
        store = Store(
            store_id=row["store_id"],
            display_name=row["display_name"],
            currency=row["currency"],
            timezone=row["timezone"],
            is_demo=bool(row["is_demo"]),
            presentation=presentation_from_mapping(json.loads(row["presentation_json"])),
            catalog_path=row["catalog_path"],
            created_at=row["created_at"],
        )
        validate_store(store)
        return store

    def _normalized_domains(self, domains: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(normalize_hostname(hostname) for hostname in domains)
        if len(set(normalized)) != len(normalized):
            raise DuplicateHostnameError("the same hostname was supplied twice")
        for hostname in normalized:
            if self.find_store_by_hostname(hostname) is not None:
                raise DuplicateHostnameError(f"hostname already registered: {hostname}")
        return normalized


__all__ = [
    "DuplicateHostnameError",
    "StoreNotFoundError",
    "StoreRepository",
    "StoreValidationError",
]
