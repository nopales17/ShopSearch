"""Typed loading for founder-authored store configuration documents."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from backend.stores.validation import StoreValidationError, validate_store
from contracts.store import HeroImage, Store, StorePresentation


def load_store_config(path: Path) -> tuple[Store, tuple[str, ...]]:
    """Return the validated store record and its configured hostnames."""

    return load_store_config_in_memory(_load_object(path))


def load_store_config_in_memory(document: Mapping[str, Any]) -> tuple[Store, tuple[str, ...]]:
    """Validate an in-memory store document, used by the provisioning CLI and tests."""

    presentation = presentation_from_mapping(document.get("presentation"))
    domains = document.get("domains", [])
    if not isinstance(domains, list) or any(not isinstance(host, str) for host in domains):
        raise StoreValidationError("domains must be a list of hostnames")
    store = Store(
        store_id=_required_string(document, "store_id"),
        display_name=_required_string(document, "display_name"),
        currency=_required_string(document, "currency"),
        timezone=_required_string(document, "timezone"),
        is_demo=_required_bool(document, "is_demo"),
        presentation=presentation,
    )
    validate_store(store)
    return store, tuple(domains)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreValidationError(f"could not load store config {path}: {error}") from error
    if not isinstance(value, dict):
        raise StoreValidationError("store config must contain a JSON object")
    return value


def presentation_from_mapping(value: Any) -> StorePresentation:
    if not isinstance(value, dict):
        raise StoreValidationError("presentation must be an object")
    expected = {field.name for field in fields(StorePresentation)}
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing:
        raise StoreValidationError(f"presentation missing fields: {sorted(missing)}")
    if unknown:
        raise StoreValidationError(f"presentation has unknown fields: {sorted(unknown)}")
    values: dict[str, Any] = dict(value)
    raw_heroes = values["hero_images"]
    if not isinstance(raw_heroes, list):
        raise StoreValidationError("presentation.hero_images must be a list")
    values["hero_images"] = tuple(_hero_image(entry) for entry in raw_heroes)
    for name in ("example_queries", "categories"):
        raw = values[name]
        if not isinstance(raw, list) or any(not isinstance(entry, str) for entry in raw):
            raise StoreValidationError(f"presentation.{name} must be a list of strings")
        values[name] = tuple(raw)
    for name, entry in values.items():
        if name in {"hero_images", "example_queries", "categories"}:
            continue
        if not isinstance(entry, str):
            raise StoreValidationError(f"presentation.{name} must be a string")
    return StorePresentation(**values)


def _hero_image(value: Any) -> HeroImage:
    if not isinstance(value, dict):
        raise StoreValidationError("each hero image must be an object")
    expected = {field.name for field in fields(HeroImage)}
    if value.keys() != expected:
        raise StoreValidationError(f"hero image fields must be {sorted(expected)}")
    return HeroImage(
        role=_required_string(value, "role"),
        item_id=_required_string(value, "item_id"),
        src=_required_string(value, "src"),
        alt=_required_string(value, "alt"),
        label=_required_string(value, "label"),
        width=_required_int(value, "width"),
        height=_required_int(value, "height"),
    )


def _required_string(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StoreValidationError(f"{field} must be a non-empty string")
    return value


def _required_bool(record: Mapping[str, Any], field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise StoreValidationError(f"{field} must be a boolean")
    return value


def _required_int(record: Mapping[str, Any], field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StoreValidationError(f"{field} must be a positive integer")
    return value
