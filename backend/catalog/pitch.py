"""Validated, permitted-photo demo catalog. No physical stock observations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from backend.catalog.repository import (
    CatalogValidationError,
    LoadedCatalog,
    _identifier,
    _parse_price,
    _required_string,
)
from contracts.catalog import (
    CatalogItem,
    EvidenceRef,
    ItemObservation,
    ObservationSource,
    StoreConfiguration,
)


def load_pitch_catalog(path: Path) -> LoadedCatalog:
    document = json.loads(path.read_text())
    if (
        document.get("dataset_kind") != "pitch_demo"
        or document.get("not_customer_zero_inventory") is not True
    ):
        raise CatalogValidationError("explicit pitch-demo scope required")
    records = document.get("items", [])
    if not 20 <= len(records) <= 100:
        raise CatalogValidationError("pitch demo requires 20–100 permitted photographs")
    items, observations = [], []
    for record in records:
        item_id = _identifier(record, "item_id")
        if record.get("demo") is not True or record.get("store_id") != "pitch-demo":
            raise CatalogValidationError("pitch record scope mismatch")
        if record.get("license") != "CC0" or not record.get("source_url", "").startswith(
            "https://clevelandart.org/art/"
        ):
            raise CatalogValidationError("reviewed CC0 source record required")
        image_uri = f"/images/{item_id}.jpg"
        if record.get("image_uri") != image_uri:
            raise CatalogValidationError("unexpected image path")
        image_path = path.parent / "images" / f"{item_id}.jpg"
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != record.get("image_sha256"):
            raise CatalogValidationError("image hash differs from reviewed photo")
        price = _parse_price(record.get("price"))
        if record.get("price_kind") != ("unknown" if price is None else "illustrative_demo"):
            raise CatalogValidationError("demo price must not masquerade as sale price")
        reviewed_at = datetime.fromisoformat(record["source_reviewed_at"])
        if reviewed_at.tzinfo is None or record.get("photo_captured_at") is not None:
            raise CatalogValidationError("source review time is not photo capture time")
        observation_id = "source-review-" + item_id
        observations.append(
            ItemObservation(
                observation_id,
                ObservationSource.MANUAL,
                reviewed_at,
                image_uri,
                {
                    "scope": "online_source_review_only",
                    "source_url": record["source_url"],
                    "photo_captured_at": None,
                },
            )
        )
        items.append(
            CatalogItem(
                item_id=item_id,
                store_id="pitch-demo",
                title=_required_string(record, "title"),
                category=_required_string(record, "category"),
                price=price,
                image_uri=image_uri,
                attributes=record,
                evidence=[EvidenceRef(ObservationSource.MANUAL, observation_id, reviewed_at)],
            )
        )
    if len({i.item_id for i in items}) != len(items) or len(
        {i.attributes["image_sha256"] for i in items}
    ) != len(items):
        raise CatalogValidationError("duplicate item or photo")
    version = "pitch-v1:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return LoadedCatalog(
        StoreConfiguration("pitch-demo", "FORM & FIELD", "USD", "America/Los_Angeles"),
        version,
        tuple(items),
        tuple(observations),
        "pitch_demo",
    )
