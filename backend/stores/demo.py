"""The committed Form & Field demo store record.

Tooling and evaluation code read the same store configuration the registry seeds,
so the catalog's store identity and public claim wording have one source.
"""

from __future__ import annotations

from pathlib import Path

from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config
from contracts.catalog import StoreConfiguration
from contracts.store import Store


def load_demo_store(path: Path | None = None) -> Store:
    store, _ = load_store_config(path or DEFAULT_DEMO_STORE_PATH)
    return store


def demo_store_configuration(path: Path | None = None) -> StoreConfiguration:
    return load_demo_store(path).configuration()
