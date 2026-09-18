"""PBKDF2-HMAC-SHA256 password hashing with a random per-password salt."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from functools import lru_cache

ALGORITHM = "sha256"
PASSWORD_ITERATIONS = 600_000
SALT_BYTES = 16
HASH_BYTES = 32


@dataclass(frozen=True)
class PasswordHash:
    salt: bytes
    digest: bytes
    iterations: int


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> PasswordHash:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ValueError("password iterations must be a positive integer")
    salt = secrets.token_bytes(SALT_BYTES)
    return PasswordHash(salt, _derive(password, salt, iterations), iterations)


def verify_password(password: str, stored: PasswordHash) -> bool:
    if not isinstance(password, str) or not password:
        return False
    if stored.iterations < 1 or not stored.salt or not stored.digest:
        return False
    return hmac.compare_digest(_derive(password, stored.salt, stored.iterations), stored.digest)


def equalizing_failure(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> None:
    """Spend the same hashing work as a real check, for unknown usernames.

    Keeps invalid-credential responses from revealing whether a username exists
    through response time.
    """

    if isinstance(password, str) and password:
        _derive(password, _dummy_salt(), iterations)


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        ALGORITHM, password.encode("utf-8"), salt, iterations, dklen=HASH_BYTES
    )


@lru_cache(maxsize=1)
def _dummy_salt() -> bytes:
    return bytes(range(SALT_BYTES))
