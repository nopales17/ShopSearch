"""Per-store merchant authentication, rate limiting and cookie helpers."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4

from backend.auth.passwords import (
    PASSWORD_ITERATIONS,
    equalizing_failure,
    hash_password,
    verify_password,
)
from backend.auth.repository import (
    MerchantNotFoundError,
    MerchantRecord,
    MerchantRepository,
)
from backend.platform import db as platform_db
from contracts.auth import IssuedMerchantSession, MerchantIdentity, MerchantSession
from contracts.store import Store, StoreScope

MERCHANT_COOKIE = "shopsearch_merchant"
LOGIN_CSRF_COOKIE = "shopsearch_login_csrf"

# 12-hour absolute session lifetime, no remember-me behavior.
SESSION_TTL = timedelta(hours=12)
TOKEN_BYTES = 32
CSRF_BYTES = 32
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60.0
SESSION_COOKIE_ATTRIBUTES = "Path=/; Secure; HttpOnly; SameSite=Lax"

_USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def normalize_username(value: str) -> str | None:
    """Normalize a submitted username, or return None when it is not usable."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if _USERNAME.fullmatch(normalized) else None


def merchant_cookie_header(token: str) -> str:
    return f"{MERCHANT_COOKIE}={token}; {SESSION_COOKIE_ATTRIBUTES}"


def login_csrf_cookie_header(token: str) -> str:
    return f"{LOGIN_CSRF_COOKIE}={token}; {SESSION_COOKIE_ATTRIBUTES}"


def clear_cookie_header(name: str) -> str:
    return f"{name}=; {SESSION_COOKIE_ATTRIBUTES}; Max-Age=0"


def csrf_matches(submitted: object, expected: object) -> bool:
    if not isinstance(submitted, str) or not isinstance(expected, str):
        return False
    if not submitted or not expected:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))


@dataclass(frozen=True)
class LoginOutcome:
    identity: MerchantIdentity | None = None
    retry_after_seconds: float = 0.0

    @property
    def throttled(self) -> bool:
        return self.identity is None and self.retry_after_seconds > 0


class LoginRateLimiter:
    """Process-local failed-login throttle keyed by (store_id, normalized username).

    The selected runtime is one Waitress process, so no shared store is needed. A
    successful authentication clears the bucket; the window is fixed from the failure
    that opened it, so throttling ends when that window expires.
    """

    def __init__(
        self,
        *,
        max_attempts: int = MAX_LOGIN_ATTEMPTS,
        window_seconds: float = LOGIN_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def retry_after(self, key: tuple[str, str]) -> float:
        with self._lock:
            failures = self._prune(key)
            if len(failures) < self._max_attempts:
                return 0.0
            return max(0.0, failures[0] + self._window - self._clock())

    def record_failure(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._prune(key).append(self._clock())

    def clear(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, key: tuple[str, str]) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = self._clock() - self._window
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures


class MerchantAuth:
    """Merchant operations for exactly one store."""

    def __init__(
        self,
        repository: MerchantRepository,
        store: Store,
        *,
        iterations: int = PASSWORD_ITERATIONS,
        rate_limiter: LoginRateLimiter | None = None,
        session_ttl: timedelta = SESSION_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._store = store
        self._iterations = iterations
        self._limiter = rate_limiter or LoginRateLimiter()
        self._session_ttl = session_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def scope(self) -> StoreScope:
        return self._store.scope

    # -- founder operations --------------------------------------------------

    def create_merchant(self, username: str, password: str) -> MerchantIdentity:
        normalized = self._require_username(username)
        password_hash = hash_password(password, iterations=self._iterations)
        merchant_id = str(uuid4())
        self._repository.insert_merchant(
            self.scope,
            merchant_id=merchant_id,
            username=normalized,
            password=password_hash,
        )
        return MerchantIdentity(self._store.store_id, merchant_id, normalized)

    def disable_merchant(self, username: str) -> bool:
        record = self._require_merchant(username)
        updated = self._repository.set_disabled(self.scope, record.merchant_id, disabled=True)
        if updated:
            self._repository.revoke_merchant_sessions(self.scope, record.merchant_id)
        return updated

    def reset_password(self, username: str, password: str) -> int:
        """Replace the credential and revoke every existing session for that merchant."""

        record = self._require_merchant(username)
        password_hash = hash_password(password, iterations=self._iterations)
        if not self._repository.replace_password(self.scope, record.merchant_id, password_hash):
            raise MerchantNotFoundError(f"no merchant {record.username}")
        return self._repository.revoke_merchant_sessions(self.scope, record.merchant_id)

    def list_merchants(self) -> tuple[MerchantIdentity, ...]:
        return tuple(
            MerchantIdentity(self._store.store_id, record.merchant_id, record.username)
            for record in self._repository.list_merchants(self.scope)
        )

    # -- runtime -------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> LoginOutcome:
        """Verify a credential. The result never says whether a username exists."""

        normalized = normalize_username(username)
        key = (self._store.store_id, normalized or str(username or "").strip().lower()[:64])
        wait = self._limiter.retry_after(key)
        if wait > 0:
            return LoginOutcome(retry_after_seconds=wait)
        if normalized is None:
            equalizing_failure(password, iterations=self._iterations)
            self._limiter.record_failure(key)
            return LoginOutcome()
        record = self._repository.merchant_by_username(self.scope, normalized)
        if record is None:
            equalizing_failure(password, iterations=self._iterations)
            self._limiter.record_failure(key)
            return LoginOutcome()
        if record.disabled or not verify_password(password, record.password):
            self._limiter.record_failure(key)
            return LoginOutcome()
        self._limiter.clear(key)
        return LoginOutcome(MerchantIdentity(self._store.store_id, record.merchant_id, normalized))

    def start_session(self, identity: MerchantIdentity) -> IssuedMerchantSession:
        if identity.store_id != self._store.store_id:
            raise ValueError("merchant identity belongs to another store")
        token = secrets.token_urlsafe(TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(CSRF_BYTES)
        expires_at = self._clock() + self._session_ttl
        self._repository.insert_session(
            self.scope,
            token_sha256=token_digest(token),
            merchant_id=identity.merchant_id,
            csrf_token=csrf_token,
            expires_at=expires_at.isoformat(),
        )
        return IssuedMerchantSession(token, csrf_token, expires_at)

    def identify(self, raw_token: str | None) -> MerchantSession | None:
        """Resolve a cookie token inside this store, or return None."""

        if not isinstance(raw_token, str) or not raw_token:
            return None
        record = self._repository.session_by_token(self.scope, token_digest(raw_token))
        if record is None or record.revoked_at is not None or record.disabled:
            return None
        if _parse_timestamp(record.expires_at) <= self._clock():
            return None
        return MerchantSession(
            MerchantIdentity(self._store.store_id, record.merchant_id, record.username),
            record.csrf_token,
            _parse_timestamp(record.expires_at),
        )

    def revoke(self, raw_token: str | None) -> bool:
        if not isinstance(raw_token, str) or not raw_token:
            return False
        return self._repository.revoke_session(self.scope, token_digest(raw_token))

    # -- internals -----------------------------------------------------------

    def _require_username(self, username: str) -> str:
        normalized = normalize_username(username)
        if normalized is None:
            raise ValueError("username must be 1-64 characters of [a-z0-9._-]")
        return normalized

    def _require_merchant(self, username: str) -> MerchantRecord:
        record = self._repository.merchant_by_username(self.scope, self._require_username(username))
        if record is None:
            raise MerchantNotFoundError(f"no merchant {username}")
        return record


def token_digest(raw_token: str) -> str:
    """The only representation of a session token this system persists."""

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class AuthStores:
    """Opens store-scoped merchant auth services against one database file."""

    @classmethod
    def open(
        cls, database_path: Path | str, *, iterations: int = PASSWORD_ITERATIONS
    ) -> "AuthStores":
        return cls(platform_db.Database.open(database_path), iterations=iterations)

    def __init__(
        self, database: platform_db.Database, *, iterations: int = PASSWORD_ITERATIONS
    ) -> None:
        self._database = database
        self._repository = MerchantRepository(database)
        self._iterations = iterations
        self._limiter = LoginRateLimiter()

    def for_store(self, store: Store) -> MerchantAuth:
        return MerchantAuth(
            self._repository,
            store,
            iterations=self._iterations,
            rate_limiter=self._limiter,
        )

    def close(self) -> None:
        self._database.close()

    def __enter__(self) -> "AuthStores":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
