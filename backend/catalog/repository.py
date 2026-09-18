"""Validated loading for the explicitly non-production fixture catalog."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.catalog.read_model import LoadedCatalog
from backend.catalog.validation import (
    CatalogValidationError,
    identifier,
    parse_price,
    required_string,
)
from contracts.catalog import (
    CatalogItem,
    EvidenceRef,
    ItemObservation,
    ObservationSource,
    StoreConfiguration,
)


def load_fixture_catalog(catalog_path: Path, store_path: Path) -> LoadedCatalog:
    """Load only a fixture dataset that declares it is not store inventory."""

    catalog_document = _load_document(catalog_path)
    store_document = _load_document(store_path)
    if catalog_document.get("dataset_kind") != "test_fixture":
        raise CatalogValidationError("catalog must declare dataset_kind=test_fixture")
    if catalog_document.get("not_customer_zero_inventory") is not True:
        raise CatalogValidationError(
            "fixture catalog must declare it is not Customer Zero inventory"
        )

    store = _parse_store(store_document)
    records = catalog_document.get("items")
    if not isinstance(records, list) or len(records) < 30:
        raise CatalogValidationError("fixture catalog must contain at least 30 records")

    items = tuple(_parse_item(record, store.store_id) for record in records)
    item_ids = [item.item_id for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise CatalogValidationError("fixture catalog item IDs must be unique")
    # Inline fixture evidence is the complete source record, not a dangling photo ID.
    observations = tuple(
        ItemObservation(
            observation_id=item.evidence[0].source_id,
            source=item.evidence[0].source_type,
            observed_at=item.evidence[0].observed_at,
            attributes={"fixture": True},
        )
        for item in items
    )
    if len({observation.observation_id for observation in observations}) != len(observations):
        raise CatalogValidationError("fixture source IDs must be unique")
    digest = hashlib.sha256(
        json.dumps([catalog_document, store_document], sort_keys=True).encode()
    ).hexdigest()
    version = required_string(catalog_document, "catalog_version") + ":" + digest
    return LoadedCatalog(store=store, version=version, items=items, observations=observations)


def _load_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogValidationError(f"could not load {path}: {error}") from error
    if not isinstance(value, dict):
        raise CatalogValidationError(f"{path} must contain a JSON object")
    return value


def _parse_store(record: dict[str, Any]) -> StoreConfiguration:
    currency = required_string(record, "currency")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise CatalogValidationError("currency must be a three-letter uppercase code")
    try:
        ZoneInfo(required_string(record, "timezone"))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise CatalogValidationError("store timezone must be a valid IANA timezone") from error
    return StoreConfiguration(
        store_id=identifier(record, "store_id"),
        display_name=required_string(record, "display_name"),
        currency=currency,
        timezone=required_string(record, "timezone"),
    )


def _parse_item(record: Any, store_id: str) -> CatalogItem:
    if not isinstance(record, dict):
        raise CatalogValidationError("each item must be an object")
    if record.get("fixture") is not True:
        raise CatalogValidationError("each fixture item must be marked fixture=true")
    if record.get("store_id", store_id) != store_id:
        raise CatalogValidationError("item store scope conflicts with configured store")
    evidence_record = record.get("evidence")
    if not isinstance(evidence_record, dict):
        raise CatalogValidationError("each item needs a provenance object")
    try:
        source = ObservationSource(required_string(evidence_record, "source_type"))
        observed_at = datetime.fromisoformat(required_string(evidence_record, "observed_at"))
    except ValueError as error:
        raise CatalogValidationError(
            f"invalid provenance for {record.get('item_id')}: {error}"
        ) from error
    if observed_at.tzinfo is None:
        raise CatalogValidationError("fixture observation timestamps must include a timezone")
    if source != ObservationSource.MANUAL:
        raise CatalogValidationError("this fixture loader supports manual fixture sources only")
    price = parse_price(record.get("price"))
    attributes = record.get("attributes", {})
    if not isinstance(attributes, dict):
        raise CatalogValidationError("item attributes must be an object")
    return CatalogItem(
        item_id=identifier(record, "item_id"),
        store_id=store_id,
        title=required_string(record, "title"),
        category=required_string(record, "category"),
        price=price,
        image_uri=None,
        attributes=attributes,
        evidence=[
            EvidenceRef(
                source_type=source,
                source_id=identifier(evidence_record, "source_id"),
                observed_at=observed_at,
            )
        ],
        is_fixture=True,
    )
