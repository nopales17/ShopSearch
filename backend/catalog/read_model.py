"""Catalog-owned in-memory read model handed to views, search and telemetry.

`LoadedCatalog` is the public representation of a store's catalog for one request
lifetime or process snapshot. S2 built it from JSON; S3 builds it from the
store-scoped catalog repository. Search consumes it and never mutates it.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.catalog import CatalogItem, ItemObservation, StoreConfiguration


@dataclass(frozen=True)
class LoadedCatalog:
    store: StoreConfiguration
    version: str
    items: tuple[CatalogItem, ...]
    observations: tuple[ItemObservation, ...]
    dataset_kind: str = "test_fixture"

    def get(self, item_id: str) -> CatalogItem | None:
        return next((item for item in self.items if item.item_id == item_id), None)

    def items_by_result(self, item_id: str) -> CatalogItem:
        item = self.get(item_id)
        if item is None:
            raise ValueError("search returned an unknown catalog item")
        return item

    def observation(self, source_id: str) -> ItemObservation:
        return next(
            observation
            for observation in self.observations
            if observation.observation_id == source_id
        )

    def public_snapshot(self, item: CatalogItem) -> dict[str, object]:
        """Catalog-owned representation; never a physical availability claim."""
        return {
            "item_id": item.item_id,
            "title": item.title,
            "price": str(item.price) if item.price is not None else None,
            "currency": self.store.currency,
            # Store-owned public claim wording (ADR-0005 §7), never a code literal.
            "public_claim": self.store.public_claim,
            "observations": [
                {
                    "source_id": ref.source_id,
                    "source_type": ref.source_type.value,
                    "observed_at": self.observation(ref.source_id).observed_at.isoformat(),
                }
                for ref in item.evidence
            ],
        }
