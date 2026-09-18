"""Idempotent seeding of founder-authored store records into the registry."""

from __future__ import annotations

from pathlib import Path

from backend.stores.config import load_store_config
from backend.stores.hostname import normalize_hostname
from backend.stores.repository import StoreRepository
from backend.stores.validation import StoreValidationError
from contracts.store import Store


def seed_store(repository: StoreRepository, config_path: Path) -> Store:
    """Create the configured store if absent and register any missing hostnames.

    Re-running is a no-op. If the record already exists with different
    founder-authored content, the seed fails loudly instead of silently
    rewriting or ignoring store configuration.
    """

    store, domains = load_store_config(config_path)
    existing = repository.find_store(store.scope)
    if existing is None:
        return repository.create_store(store, domains)
    _require_same_record(existing, store)
    registered = set(repository.domains_for(existing.scope))
    for hostname in domains:
        normalized = normalize_hostname(hostname)
        if normalized not in registered:
            repository.add_domain(existing.scope, normalized)
    return existing


def _require_same_record(existing: Store, configured: Store) -> None:
    fields = ("display_name", "currency", "timezone", "is_demo")
    for field in fields:
        if getattr(existing, field) != getattr(configured, field):
            raise StoreValidationError(
                f"seeded store {existing.store_id} differs from configuration in {field}; "
                "apply a migration instead of editing the seed silently"
            )
    if existing.presentation != configured.presentation:
        raise StoreValidationError(
            f"seeded store {existing.store_id} presentation differs from configuration; "
            "apply a migration instead of editing the seed silently"
        )
