"""Store-scoped persistence for merchant accounts and sessions.

Every statement is scoped by `store_id`; a session lookup therefore never resolves a
merchant from another store, and the composite foreign key keeps rows consistent.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from backend.auth.passwords import PasswordHash
from backend.platform import db as platform_db
from backend.platform.db import utc_now
from contracts.store import StoreScope


class MerchantNotFoundError(LookupError):
    """Raised when a store has no such merchant."""


class DuplicateUsernameError(ValueError):
    """Raised when a username already exists inside the same store."""


@dataclass(frozen=True)
class MerchantRecord:
    merchant_id: str
    username: str
    password: PasswordHash
    disabled: bool


@dataclass(frozen=True)
class SessionRecord:
    merchant_id: str
    username: str
    disabled: bool
    csrf_token: str
    issued_at: str
    expires_at: str
    revoked_at: str | None


class MerchantRepository:
    """Typed access to `merchants` and `merchant_sessions` for one database."""

    @classmethod
    def open(cls, database_path: Path | str) -> "MerchantRepository":
        return cls(platform_db.Database.open(database_path))

    def __init__(self, database: platform_db.Database) -> None:
        self._database = database

    def close(self) -> None:
        self._database.close()

    # -- merchants ----------------------------------------------------------

    def insert_merchant(
        self,
        scope: StoreScope,
        *,
        merchant_id: str,
        username: str,
        password: PasswordHash,
    ) -> None:
        now = utc_now()
        try:
            with self._database.connection() as connection:
                connection.execute(
                    "INSERT INTO merchants ("
                    "store_id, merchant_id, username, password_salt, password_hash, "
                    "password_iterations, disabled, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (
                        scope.store_id,
                        merchant_id,
                        username,
                        password.salt,
                        password.digest,
                        password.iterations,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateUsernameError(
                f"username already exists in store {scope.store_id}"
            ) from error

    def merchant_by_username(self, scope: StoreScope, username: str) -> MerchantRecord | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT merchant_id, username, password_salt, password_hash, "
                "password_iterations, disabled FROM merchants "
                "WHERE store_id = ? AND username = ?",
                (scope.store_id, username),
            )
            .fetchone()
        )
        return None if row is None else _merchant(row)

    def merchant_by_id(self, scope: StoreScope, merchant_id: str) -> MerchantRecord | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT merchant_id, username, password_salt, password_hash, "
                "password_iterations, disabled FROM merchants "
                "WHERE store_id = ? AND merchant_id = ?",
                (scope.store_id, merchant_id),
            )
            .fetchone()
        )
        return None if row is None else _merchant(row)

    def list_merchants(self, scope: StoreScope) -> tuple[MerchantRecord, ...]:
        rows = (
            self._database.connection()
            .execute(
                "SELECT merchant_id, username, password_salt, password_hash, "
                "password_iterations, disabled FROM merchants "
                "WHERE store_id = ? ORDER BY username",
                (scope.store_id,),
            )
            .fetchall()
        )
        return tuple(_merchant(row) for row in rows)

    def set_disabled(self, scope: StoreScope, merchant_id: str, *, disabled: bool) -> bool:
        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE merchants SET disabled = ?, updated_at = ? "
                "WHERE store_id = ? AND merchant_id = ?",
                (1 if disabled else 0, utc_now(), scope.store_id, merchant_id),
            )
        return cursor.rowcount > 0

    def replace_password(self, scope: StoreScope, merchant_id: str, password: PasswordHash) -> bool:
        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE merchants SET password_salt = ?, password_hash = ?, "
                "password_iterations = ?, updated_at = ? "
                "WHERE store_id = ? AND merchant_id = ?",
                (
                    password.salt,
                    password.digest,
                    password.iterations,
                    utc_now(),
                    scope.store_id,
                    merchant_id,
                ),
            )
        return cursor.rowcount > 0

    # -- sessions -----------------------------------------------------------

    def insert_session(
        self,
        scope: StoreScope,
        *,
        token_sha256: str,
        merchant_id: str,
        csrf_token: str,
        expires_at: str,
    ) -> None:
        try:
            with self._database.connection() as connection:
                connection.execute(
                    "INSERT INTO merchant_sessions ("
                    "store_id, token_sha256, merchant_id, csrf_token, issued_at, expires_at"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        scope.store_id,
                        token_sha256,
                        merchant_id,
                        csrf_token,
                        utc_now(),
                        expires_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("merchant session could not be stored") from error

    def session_by_token(self, scope: StoreScope, token_sha256: str) -> SessionRecord | None:
        row = (
            self._database.connection()
            .execute(
                "SELECT sessions.merchant_id AS merchant_id, merchants.username AS username, "
                "merchants.disabled AS disabled, sessions.csrf_token AS csrf_token, "
                "sessions.issued_at AS issued_at, sessions.expires_at AS expires_at, "
                "sessions.revoked_at AS revoked_at "
                "FROM merchant_sessions AS sessions "
                "JOIN merchants "
                "ON merchants.store_id = sessions.store_id "
                "AND merchants.merchant_id = sessions.merchant_id "
                "WHERE sessions.store_id = ? AND sessions.token_sha256 = ?",
                (scope.store_id, token_sha256),
            )
            .fetchone()
        )
        if row is None:
            return None
        return SessionRecord(
            merchant_id=str(row["merchant_id"]),
            username=str(row["username"]),
            disabled=bool(row["disabled"]),
            csrf_token=str(row["csrf_token"]),
            issued_at=str(row["issued_at"]),
            expires_at=str(row["expires_at"]),
            revoked_at=None if row["revoked_at"] is None else str(row["revoked_at"]),
        )

    def revoke_session(self, scope: StoreScope, token_sha256: str) -> bool:
        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE merchant_sessions SET revoked_at = ? "
                "WHERE store_id = ? AND token_sha256 = ? AND revoked_at IS NULL",
                (utc_now(), scope.store_id, token_sha256),
            )
        return cursor.rowcount > 0

    def revoke_merchant_sessions(self, scope: StoreScope, merchant_id: str) -> int:
        with self._database.connection() as connection:
            cursor = connection.execute(
                "UPDATE merchant_sessions SET revoked_at = ? "
                "WHERE store_id = ? AND merchant_id = ? AND revoked_at IS NULL",
                (utc_now(), scope.store_id, merchant_id),
            )
        return int(cursor.rowcount)


def _merchant(row: sqlite3.Row) -> MerchantRecord:
    return MerchantRecord(
        merchant_id=str(row["merchant_id"]),
        username=str(row["username"]),
        password=PasswordHash(
            salt=bytes(row["password_salt"]),
            digest=bytes(row["password_hash"]),
            iterations=int(row["password_iterations"]),
        ),
        disabled=bool(row["disabled"]),
    )
