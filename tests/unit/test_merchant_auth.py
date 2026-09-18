from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from backend.auth.passwords import (
    HASH_BYTES,
    PASSWORD_ITERATIONS,
    SALT_BYTES,
    hash_password,
    verify_password,
)
from backend.auth.repository import (
    DuplicateUsernameError,
    MerchantNotFoundError,
    MerchantRepository,
)
from backend.auth.service import (
    SESSION_TTL,
    AuthStores,
    LoginRateLimiter,
    MerchantAuth,
    normalize_username,
    token_digest,
)
from backend.platform import db as platform_db
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from contracts.store import Store

FAST_ITERATIONS = 1_000


def add_live_store(store_repository: StoreRepository, store_id: str) -> Store:
    document = json.loads(DEFAULT_DEMO_STORE_PATH.read_text())
    document["store_id"] = store_id
    document["is_demo"] = False
    document["domains"] = []
    store, domains = load_store_config_in_memory(document)
    return store_repository.create_store(store, domains)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class PasswordHashingTest(unittest.TestCase):
    def test_defaults_are_pbkdf2_sha256_with_a_random_salt(self) -> None:
        self.assertEqual(PASSWORD_ITERATIONS, 600_000)
        stored = hash_password("correct horse battery staple")
        self.assertEqual(stored.iterations, PASSWORD_ITERATIONS)
        self.assertEqual(len(stored.salt), SALT_BYTES)
        self.assertEqual(len(stored.digest), HASH_BYTES)
        self.assertTrue(verify_password("correct horse battery staple", stored))
        self.assertFalse(verify_password("wrong", stored))
        second = hash_password("correct horse battery staple", iterations=FAST_ITERATIONS)
        self.assertNotEqual(stored.salt, second.salt)
        self.assertNotEqual(stored.digest, second.digest)

    def test_empty_passwords_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            hash_password("")
        self.assertFalse(verify_password("", hash_password("x", iterations=FAST_ITERATIONS)))

    def test_usernames_normalize_deterministically(self) -> None:
        self.assertEqual(normalize_username("  Alice "), "alice")
        for invalid in ("", "   ", "bad user", "bad@example.com", "a" * 65):
            with self.subTest(invalid=invalid):
                self.assertIsNone(normalize_username(invalid))


class MerchantAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "shopsearch.sqlite3"
        self.stores = StoreRepository.open(self.database_path)
        self.addCleanup(self.stores.close)
        self.demo = seed_store(self.stores, DEFAULT_DEMO_STORE_PATH)
        self.live = add_live_store(self.stores, "live-store")
        self.auth_stores = AuthStores.open(self.database_path, iterations=FAST_ITERATIONS)
        self.addCleanup(self.auth_stores.close)
        self.auth = self.auth_stores.for_store(self.demo)
        self.live_auth = self.auth_stores.for_store(self.live)

    def service(self, store: Store, *, clock=None, limiter=None) -> MerchantAuth:
        database = platform_db.Database.open(self.database_path)
        self.addCleanup(database.close)
        return MerchantAuth(
            MerchantRepository(database),
            store,
            iterations=FAST_ITERATIONS,
            clock=clock,
            rate_limiter=limiter,
        )

    def test_multiple_accounts_per_store_and_reuse_across_stores(self) -> None:
        alice = self.auth.create_merchant("Alice", "first-password")
        bob = self.auth.create_merchant("bob", "second-password")
        self.assertEqual({alice.username, bob.username}, {"alice", "bob"})
        self.assertEqual(len(self.auth.list_merchants()), 2)
        reused = self.live_auth.create_merchant("alice", "third-password")
        self.assertEqual(reused.username, "alice")
        self.assertNotEqual(reused.merchant_id, alice.merchant_id)
        with self.assertRaises(DuplicateUsernameError):
            self.auth.create_merchant(" ALICE ", "fourth-password")

    def test_wrong_password_disabled_and_missing_accounts_fail_generically(self) -> None:
        self.auth.create_merchant("alice", "right-password")
        wrong = self.auth.authenticate("alice", "wrong-password")
        unknown = self.auth.authenticate("nobody", "wrong-password")
        self.assertEqual(wrong, unknown)  # One generic invalid-credential outcome.
        self.assertFalse(wrong.throttled)
        self.assertTrue(self.auth.disable_merchant("alice"))
        self.assertIsNone(self.auth.authenticate("alice", "right-password").identity)
        with self.assertRaises(MerchantNotFoundError):
            self.auth.disable_merchant("nobody")

    def test_sessions_are_store_scoped_and_only_hashes_are_persisted(self) -> None:
        identity = self.auth.create_merchant("alice", "right-password")
        issued = self.auth.start_session(identity)
        session = self.auth.identify(issued.token)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.identity.username, "alice")
        self.assertNotEqual(session.csrf_token, issued.token)
        # The raw token is never stored; only its SHA-256 digest is.
        connection = platform_db.connect(self.database_path)
        try:
            stored = [
                str(row["token_sha256"])
                for row in connection.execute("SELECT token_sha256 FROM merchant_sessions")
            ]
        finally:
            connection.close()
        self.assertNotIn(issued.token, stored)
        self.assertEqual(stored, [token_digest(issued.token)])
        # A token from another store's hostname yields no identity.
        self.assertIsNone(self.live_auth.identify(issued.token))
        # Revocation and credential reset both end the session.
        self.assertTrue(self.auth.revoke(issued.token))
        self.assertIsNone(self.auth.identify(issued.token))
        second = self.auth.start_session(identity)
        revoked = self.auth.reset_password("alice", "new-password")
        self.assertEqual(revoked, 1)
        self.assertIsNone(self.auth.identify(second.token))
        self.assertIsNotNone(self.auth.authenticate("alice", "new-password").identity)
        self.assertIsNone(self.auth.authenticate("alice", "right-password").identity)

    def test_sessions_expire_after_twelve_hours(self) -> None:
        self.assertEqual(SESSION_TTL, timedelta(hours=12))
        clock = FakeClock(datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
        auth = self.service(self.demo, clock=clock)
        identity = auth.create_merchant("alice", "right-password")
        issued = auth.start_session(identity)
        self.assertIsNotNone(auth.identify(issued.token))
        clock.advance(timedelta(hours=11, minutes=59))
        self.assertIsNotNone(auth.identify(issued.token))
        clock.advance(timedelta(minutes=2))
        self.assertIsNone(auth.identify(issued.token))

    def test_disabled_merchant_sessions_stop_authorizing(self) -> None:
        identity = self.auth.create_merchant("alice", "right-password")
        issued = self.auth.start_session(identity)
        self.assertIsNotNone(self.auth.identify(issued.token))
        self.auth.disable_merchant("alice")
        self.assertIsNone(self.auth.identify(issued.token))

    def test_failed_logins_are_throttled_and_success_clears_the_bucket(self) -> None:
        clock = FakeClock(datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
        ticks = {"value": 0.0}

        def monotonic() -> float:
            return ticks["value"]

        limiter = LoginRateLimiter(max_attempts=5, window_seconds=900.0, clock=monotonic)
        auth = self.service(self.demo, clock=clock, limiter=limiter)
        auth.create_merchant("alice", "right-password")
        for _ in range(5):
            self.assertIsNone(auth.authenticate("alice", "wrong-password").identity)
        throttled = auth.authenticate("alice", "right-password")
        self.assertTrue(throttled.throttled)
        self.assertGreater(throttled.retry_after_seconds, 0)
        # Unknown usernames are throttled identically, so the limit leaks nothing.
        for _ in range(5):
            auth.authenticate("nobody", "wrong-password")
        self.assertTrue(auth.authenticate("nobody", "wrong-password").throttled)
        # The window expires from the failure that opened it.
        ticks["value"] = 901.0
        self.assertIsNotNone(auth.authenticate("alice", "right-password").identity)

    def test_successful_login_clears_earlier_failures(self) -> None:
        ticks = {"value": 0.0}
        limiter = LoginRateLimiter(
            max_attempts=5, window_seconds=900.0, clock=lambda: ticks["value"]
        )
        auth = self.service(self.demo, limiter=limiter)
        auth.create_merchant("alice", "right-password")
        for _ in range(3):
            auth.authenticate("alice", "wrong-password")
        self.assertIsNotNone(auth.authenticate("alice", "right-password").identity)
        for _ in range(4):
            self.assertFalse(auth.authenticate("alice", "wrong-password").throttled)


class ScriptedReader:
    def __init__(self, values: Iterator[str]) -> None:
        self._values = values

    def __call__(self, prompt: str) -> str:
        return next(self._values)
