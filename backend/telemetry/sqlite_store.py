"""Store-scoped append-only telemetry on the platform substrate.

ADR-0004 selects SQLite behind a `TelemetrySink`; ADR-0005 makes the store scope
mandatory. Rows are never updated or deleted: a repeated event ID is ignored when its
snapshot is identical and rejected when the content differs. Store scope, traffic
class and search attribution are validated before any row is written.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.platform import db as platform_db
from backend.telemetry.validation import (
    select_parent,
    serialize_event,
    validate_attribution,
    validate_event,
)
from contracts.store import Store
from contracts.telemetry import TelemetryEvent, TrafficClass

_COLUMNS = "store_id, event_id, event_type, occurred_at, session_id, search_id, payload_json"


class SqliteTelemetryStore:
    """One store's append-only validated telemetry rows."""

    def __init__(self, database: platform_db.Database, store: Store) -> None:
        self._database = database
        self._store = store
        self.scope = store.scope

    @property
    def store_id(self) -> str:
        return self._store.store_id

    def append(self, event: TelemetryEvent) -> bool:
        """Persist an event once. Returns false for a repeated event ID."""

        snapshot = serialize_event(event)
        traffic = validate_event(snapshot)
        if snapshot["store_id"] != self._store.store_id:
            raise ValueError("telemetry store scope mismatch")
        # Merchant-self traffic is never customer traffic, so it is valid for any
        # store kind; demo/fixture classes stay demo-only and customer stays live-only.
        if traffic is not TrafficClass.MERCHANT_SELF and traffic.is_demo != self._store.is_demo:
            raise ValueError("telemetry traffic class does not match the store")
        connection = self._database.connection()
        existing = self._event_row(connection, str(snapshot["event_id"]))
        if existing is not None:
            if _snapshot(existing) != snapshot:
                raise ValueError("event ID reused for different content")
            return False
        candidates = self._search_candidates(connection, snapshot["search_id"])
        validate_attribution(snapshot, select_parent(snapshot, candidates))
        try:
            with connection:
                connection.execute(
                    "INSERT INTO telemetry_events ("
                    "store_id, event_id, event_type, occurred_at, session_id, search_id, "
                    "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._store.store_id,
                        snapshot["event_id"],
                        snapshot["event_type"],
                        snapshot["occurred_at"],
                        snapshot["session_id"],
                        snapshot["search_id"],
                        json.dumps(snapshot["payload"], sort_keys=True, allow_nan=False),
                    ),
                )
        except sqlite3.IntegrityError:
            # A concurrent writer inserted the same ID first: identical wins, else reject.
            existing = self._event_row(connection, str(snapshot["event_id"]))
            if existing is not None and _snapshot(existing) == snapshot:
                return False
            raise ValueError("event ID reused for different content") from None
        return True

    def events(self) -> list[dict[str, Any]]:
        """Stored snapshots for this store, ordered by recorded time then event ID."""

        rows = (
            self._database.connection()
            .execute(
                f"SELECT {_COLUMNS} FROM telemetry_events WHERE store_id = ? "
                "ORDER BY occurred_at, event_id",
                (self._store.store_id,),
            )
            .fetchall()
        )
        return [_snapshot(row) for row in rows]

    def count(self) -> int:
        row = (
            self._database.connection()
            .execute(
                "SELECT COUNT(*) AS count FROM telemetry_events WHERE store_id = ?",
                (self._store.store_id,),
            )
            .fetchone()
        )
        return int(row["count"])

    def _event_row(self, connection: sqlite3.Connection, event_id: str) -> sqlite3.Row | None:
        return connection.execute(
            f"SELECT {_COLUMNS} FROM telemetry_events WHERE store_id = ? AND event_id = ?",
            (self._store.store_id, event_id),
        ).fetchone()

    def _search_candidates(
        self, connection: sqlite3.Connection, search_id: object
    ) -> list[dict[str, Any]]:
        if not isinstance(search_id, str) or not search_id:
            return []
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM telemetry_events "
            "WHERE store_id = ? AND search_id = ? ORDER BY occurred_at, event_id",
            (self._store.store_id, search_id),
        ).fetchall()
        return [_snapshot(row) for row in rows]


class TelemetryStores:
    """Opens store-scoped telemetry sinks against one database file."""

    @classmethod
    def open(cls, database_path: Path | str) -> "TelemetryStores":
        return cls(platform_db.Database.open(database_path))

    def __init__(self, database: platform_db.Database) -> None:
        self._database = database

    def for_store(self, store: Store) -> SqliteTelemetryStore:
        return SqliteTelemetryStore(self._database, store)

    def close(self) -> None:
        self._database.close()

    def __enter__(self) -> "TelemetryStores":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": str(row["event_id"]),
        "event_type": str(row["event_type"]),
        "occurred_at": str(row["occurred_at"]),
        "session_id": str(row["session_id"]),
        "store_id": str(row["store_id"]),
        "search_id": None if row["search_id"] is None else str(row["search_id"]),
        "payload": json.loads(row["payload_json"]),
    }
