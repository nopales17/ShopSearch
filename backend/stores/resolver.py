"""Hostname-to-store resolution with no default-store fallback.

ADR-0005 §3: a normalized Host header resolves through the domain table to
exactly one store. An explicit development host map may supplement the registry
locally; an unregistered hostname resolves to nothing, and the HTTP adapter turns
that into a 404 that carries no store data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from backend.stores.hostname import InvalidHostnameError, normalize_hostname
from backend.stores.repository import StoreRepository
from contracts.store import StoreScope


class DevelopmentHostsError(ValueError):
    """Raised when the development host map is malformed or has a wildcard."""


def load_development_hosts(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DevelopmentHostsError(f"could not load development hosts {path}: {error}") from error
    if not isinstance(document, dict):
        raise DevelopmentHostsError("development hosts must be a JSON object")
    hosts: dict[str, str] = {}
    for hostname, store_id in document.items():
        if not isinstance(hostname, str) or not isinstance(store_id, str):
            raise DevelopmentHostsError("development hosts must map hostnames to store IDs")
        try:
            normalized = normalize_hostname(hostname)
        except InvalidHostnameError as error:
            raise DevelopmentHostsError(
                f"invalid development host {hostname!r}: {error}"
            ) from error
        StoreScope(store_id)
        hosts[normalized] = store_id
    return hosts


class HostResolver:
    """Resolve a request Host header to one store scope, or to nothing."""

    def __init__(
        self,
        repository: StoreRepository,
        development_hosts: Mapping[str, str] | None = None,
    ) -> None:
        self._repository = repository
        self._development_hosts = {
            normalize_hostname(hostname): store_id
            for hostname, store_id in (development_hosts or {}).items()
        }

    def resolve(self, host_header: str | None) -> StoreScope | None:
        try:
            hostname = normalize_hostname(host_header or "")
        except InvalidHostnameError:
            return None
        store_id = self._development_hosts.get(hostname)
        if store_id is not None:
            store = self._repository.find_store(StoreScope(store_id))
            return None if store is None else store.scope
        store = self._repository.find_store_by_hostname(hostname)
        return None if store is None else store.scope

    def store_id_for(self, host_header: str | None) -> str | None:
        scope = self.resolve(host_header)
        return None if scope is None else scope.store_id
