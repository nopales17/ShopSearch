"""SQLite connection factory and versioned forward-only migration runner.

ADR-0004 selects SQLite in WAL mode behind repository protocols. This module owns
connections, the `foreign_keys` pragma every connection needs, and migration
bookkeeping. It contains no store-specific SQL.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with an explicit offset (ADR-0004)."""

    return datetime.now(timezone.utc).isoformat()


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the pragmas ADR-0004 requires on every connection."""

    location = str(database_path)
    if location != ":memory:":
        Path(location).parent.mkdir(parents=True, exist_ok=True)
    # Connections are used from exactly one owning thread (see `Database`), but the
    # server shutdown path closes every thread's connection from the main thread, so
    # SQLite's per-thread object check is disabled here.
    connection = sqlite3.connect(location, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def apply_migrations(
    connection: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> tuple[str, ...]:
    """Apply every unapplied `*.sql` migration in filename order.

    Migrations are forward-only and written to be re-runnable (`IF NOT EXISTS`);
    each applied version is recorded so a re-run is a no-op. Returns the versions
    applied by this call.
    """

    connection.executescript(_MIGRATIONS_TABLE)
    applied = {
        row["version"] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    newly_applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, utc_now()),
        )
        connection.commit()
        newly_applied.append(version)
    return tuple(newly_applied)


def applied_versions(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return recorded migration versions in application order."""

    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY rowid").fetchall()
    return tuple(row["version"] for row in rows)


class Database:
    """One SQLite file with thread-local connections and migrations applied.

    Waitress serves requests on multiple threads and SQLite connections are not
    shareable across threads, so each thread gets its own migrated connection for
    the life of the database object.
    """

    @classmethod
    def open(cls, database_path: Path | str) -> "Database":
        database = cls(database_path)
        apply_migrations(database.connection())
        return database

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = str(database_path)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()

    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = connect(self._database_path)
            apply_migrations(connection)
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def close(self) -> None:
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            connection.close()
        if getattr(self._local, "connection", None) is not None:
            self._local.connection = None

    def backup_to(self, destination: Path | str) -> None:
        """Write a consistent snapshot with SQLite's online backup API.

        WAL mode means a plain file copy of a live database is not a snapshot; the
        backup API reads a transaction-consistent image while the process keeps
        running. The destination is overwritten in place and may not exist yet.
        """

        target_path = Path(destination)
        if target_path.parent:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.connection()
        target = sqlite3.connect(str(target_path))
        try:
            source.backup(target)
            # The copied header keeps the source's WAL mode, which would leave the
            # snapshot's newest pages in a sidecar the operator does not copy. Fold
            # them back into the single snapshot file and drop the WAL.
            target.execute("PRAGMA journal_mode=delete")
            target.commit()
        finally:
            target.close()

    def check_health(self) -> None:
        """Raise when this database cannot serve a trivial read."""

        self.connection().execute("SELECT 1").fetchone()
