"""Founder-provisioned merchant authentication contracts (S6).

A merchant identity is always bound to exactly one store; a session belonging to
another store must never produce an identity on the resolved hostname.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MerchantIdentity:
    store_id: str
    merchant_id: str
    username: str


@dataclass(frozen=True)
class MerchantSession:
    """A validated merchant session; the raw token is never part of this record."""

    identity: MerchantIdentity
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedMerchantSession:
    """The one-time result of starting a session; only hashes are persisted."""

    token: str
    csrf_token: str
    expires_at: datetime
