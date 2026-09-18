"""Deterministic two-store isolation fixture for the S9 adversarial suite.

S9 adds no customer or merchant capability. It provisions two synthetic stores from
one committed document (`data/stores/isolation-fixture.json`) so that the deliberate
overlaps are explicit rather than accidental:

* the same item IDs (`iso-shared-object`, `iso-shared-object-2`) exist in both stores;
* the same source image bytes back those shared objects in both stores, so the stored
  content address is identical while the two stores own independent blobs;
* the same merchant username exists in both stores with different credentials and
  therefore different merchant identities.

Isolation must therefore come from `StoreScope`, not from globally unique fixture
values. Every value here is generated test data: it is not Cloud City, not a prospective
Customer Zero store, and not evidence about any real merchant or customer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import AuthStores
from backend.catalog.store_repository import CatalogRepository
from backend.media.derivatives import render_display
from backend.media.image_store import DISPLAY_VARIANT, LocalImageStore
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.search.vector_source import EMBEDDING_DIMENSIONS
from backend.stores.config import load_store_config_in_memory
from backend.stores.repository import StoreRepository
from contracts.auth import MerchantIdentity
from contracts.catalog import CaptureTimeSource, EvidenceRef, ObservationSource
from contracts.store import Store
from tests.unit.test_merchant_auth import FAST_ITERATIONS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ISOLATION_FIXTURE_PATH = DEFAULT_DEMO_STORE_PATH.parent / "isolation-fixture.json"

ALPHA_STORE_ID = "isolation-alpha"
BETA_STORE_ID = "isolation-beta"
UNPROVISIONED_STORE_ID = "isolation-unprovisioned"

ALPHA_HOST = "alpha.isolation.test"
BETA_HOST = "beta.isolation.test"
UNPROVISIONED_HOST = "unprovisioned.isolation.test"

SHARED_ITEM_ID = "iso-shared-object"
SHARED_ITEM_ID_2 = "iso-shared-object-2"
ALPHA_ONLY_ITEM_ID = "iso-alpha-object"
BETA_ONLY_ITEM_ID = "iso-beta-object"

SHARED_USERNAME = "shared-merchant"
ALPHA_PASSWORD = "alpha-isolation-password"
BETA_PASSWORD = "beta-isolation-password"

_OBSERVED_AT = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FixtureObject:
    """One synthetic catalog object, including its deterministic embedding slot."""

    item_id: str
    title: str
    category: str
    price: Decimal
    source_image: bytes
    vector_index: int

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source_image).hexdigest()


@dataclass(frozen=True)
class FixtureStore:
    """One provisioned isolation store with its own catalog and merchant."""

    store: Store
    merchant: MerchantIdentity
    password: str
    catalog_version: str
    objects: tuple[FixtureObject, ...]

    @property
    def host(self) -> str:
        return {ALPHA_STORE_ID: ALPHA_HOST, BETA_STORE_ID: BETA_HOST}[self.store.store_id]

    @property
    def url_host(self) -> str:
        return f"https://{self.host}"

    def object(self, item_id: str) -> FixtureObject:
        for candidate in self.objects:
            if candidate.item_id == item_id:
                return candidate
        raise KeyError(item_id)

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(candidate.item_id for candidate in self.objects)


@dataclass(frozen=True)
class IsolationFixture:
    """Two provisioned isolation stores plus a registered unprovisioned host."""

    alpha: FixtureStore
    beta: FixtureStore
    unprovisioned: Store
    database_path: Path
    media_root: Path

    @property
    def storefronts(self) -> frozenset[str]:
        return frozenset({self.alpha.store.store_id, self.beta.store.store_id})

    @property
    def stores(self) -> tuple[FixtureStore, FixtureStore]:
        return (self.alpha, self.beta)

    def image_store(self) -> LocalImageStore:
        return LocalImageStore(self.media_root)


def provision_isolation_stores(database_path: Path, media_root: Path) -> IsolationFixture:
    """Create both synthetic stores, their catalogs, embeddings and merchants."""

    with StoreRepository.open(database_path) as stores:
        alpha_store, alpha_domains = load_store_config_in_memory(
            _store_document(ALPHA_STORE_ID, host=ALPHA_HOST, label="ALPHA")
        )
        beta_store, beta_domains = load_store_config_in_memory(
            _store_document(BETA_STORE_ID, host=BETA_HOST, label="BETA")
        )
        unprovisioned_document, unprovisioned_domains = load_store_config_in_memory(
            _store_document(UNPROVISIONED_STORE_ID, host=UNPROVISIONED_HOST, label="UNPROVISIONED")
        )
        alpha = stores.create_store(alpha_store, alpha_domains)
        beta = stores.create_store(beta_store, beta_domains)
        unprovisioned = stores.create_store(unprovisioned_document, unprovisioned_domains)

    image_store = LocalImageStore(media_root)
    alpha_objects = _alpha_objects()
    beta_objects = _beta_objects()
    with CatalogRepository.open(database_path) as catalog:
        _seed_catalog(catalog, image_store, alpha, alpha_objects, "isolation-alpha-catalog")
        _seed_catalog(catalog, image_store, beta, beta_objects, "isolation-beta-catalog")

    with AuthStores.open(database_path, iterations=FAST_ITERATIONS) as auth_stores:
        alpha_merchant = auth_stores.for_store(alpha).create_merchant(
            SHARED_USERNAME, ALPHA_PASSWORD
        )
        beta_merchant = auth_stores.for_store(beta).create_merchant(SHARED_USERNAME, BETA_PASSWORD)

    return IsolationFixture(
        alpha=FixtureStore(
            alpha, alpha_merchant, ALPHA_PASSWORD, "isolation-alpha-catalog", alpha_objects
        ),
        beta=FixtureStore(
            beta, beta_merchant, BETA_PASSWORD, "isolation-beta-catalog", beta_objects
        ),
        unprovisioned=unprovisioned,
        database_path=database_path,
        media_root=media_root,
    )


def fixture_document_text() -> str:
    """The committed fixture document, for checks that it carries no demo wording."""

    return ISOLATION_FIXTURE_PATH.read_text(encoding="utf-8")


def display_sha256(source_image: bytes, store: Store) -> str:
    """The stored display address these source bytes take in `store`."""

    derivative = render_display(source_image, store_timezone=ZoneInfo(store.timezone))
    return hashlib.sha256(derivative.data).hexdigest()


def _alpha_objects() -> tuple[FixtureObject, ...]:
    return (
        FixtureObject(
            SHARED_ITEM_ID,
            "Alpha shared fixture object",
            "Lamps",
            Decimal("11.00"),
            _jpeg((20, 80, 200)),
            vector_index=0,
        ),
        FixtureObject(
            SHARED_ITEM_ID_2,
            "Alpha second shared object",
            "Lamps",
            Decimal("13.50"),
            _jpeg((210, 120, 40)),
            vector_index=1,
        ),
        FixtureObject(
            ALPHA_ONLY_ITEM_ID,
            "Alpha only fixture object",
            "Lamps",
            Decimal("19.25"),
            _jpeg((40, 160, 90)),
            vector_index=2,
        ),
    )


def _beta_objects() -> tuple[FixtureObject, ...]:
    return (
        # Deliberately the same item ID and the same source bytes as alpha's copy.
        FixtureObject(
            SHARED_ITEM_ID,
            "Beta shared fixture object",
            "Tools",
            Decimal("77.00"),
            _jpeg((20, 80, 200)),
            vector_index=10,
        ),
        FixtureObject(
            SHARED_ITEM_ID_2,
            "Beta second shared object",
            "Tools",
            Decimal("88.50"),
            _jpeg((210, 120, 40)),
            vector_index=11,
        ),
        FixtureObject(
            BETA_ONLY_ITEM_ID,
            "Beta only fixture object",
            "Tools",
            Decimal("45.75"),
            _jpeg((150, 40, 160)),
            vector_index=12,
        ),
    )


def _store_document(store_id: str, *, host: str, label: str) -> dict[str, object]:
    """The committed fixture document with one store's identity substituted."""

    document = json.loads(fixture_document_text())
    document["store_id"] = store_id
    document["display_name"] = f"Isolation {label.title()}"
    document["domains"] = [host]
    presentation = dict(document["presentation"])
    presentation.update(
        {
            "wordmark_primary": label,
            "wordmark_aria_label": f"Isolation {label.title()} fixture home",
            "page_title_suffix": f"Isolation {label.title()} fixture",
            "meta_description": (
                f"Synthetic isolation fixture storefront ({label}) used by automated "
                "tests. Not a shop and not customer evidence."
            ),
            "demo_strip": f"Synthetic isolation fixture {label} · generated objects · not a store",
            "tagline": f"Synthetic isolation fixture {label}.",
            "hero_eyebrow": f"SYNTHETIC ISOLATION FIXTURE {label}",
            "hero_title_html": f"Isolation {label}.<br><em>Synthetic objects.</em>",
            "hero_description": (
                f"Generated storefront data for isolation fixture {label}. It proves that "
                "store-scoped catalog, media, search, telemetry and merchant access never "
                "cross between stores."
            ),
            "hero_footnote_template": "{count} synthetic fixture objects",
            "featured_heading": f"Synthetic objects for isolation fixture {label}.",
            "catalog_intro": f"Generated isolation fixture data for {label}.",
            "search_placeholder": f"Search isolation fixture {label}",
            "results_summary_template": f"{{count}} fixture objects in isolation store {label}",
            "catalog_disclaimer": (
                f"Synthetic isolation fixture {label}. Prices are generated test values and "
                "visual similarity does not confirm availability."
            ),
            "item_source_value": f"Generated isolation fixture ({label})",
            "public_claim": f"Synthetic isolation fixture ({label}); not store inventory",
            "coverage_disclosure_template": (
                f"Some {label} fixture objects ({{excluded}} of {{published}}) are not yet "
                "searchable by description."
            ),
        }
    )
    document["presentation"] = presentation
    return document


def _seed_catalog(
    catalog: CatalogRepository,
    image_store: LocalImageStore,
    store: Store,
    objects: tuple[FixtureObject, ...],
    catalog_version: str,
) -> None:
    store_timezone = ZoneInfo(store.timezone)
    for sort_order, fixture_object in enumerate(objects):
        derivative = render_display(fixture_object.source_image, store_timezone=store_timezone)
        display_sha = hashlib.sha256(derivative.data).hexdigest()
        image_store.put(store.scope, display_sha, DISPLAY_VARIANT, derivative.data)
        catalog.create_item(
            store.scope,
            item_id=fixture_object.item_id,
            title=fixture_object.title,
            category=fixture_object.category,
            price=fixture_object.price,
            price_kind="known",
            attributes={"source_title": fixture_object.title, "synthetic_fixture": True},
            provenance=(
                EvidenceRef(
                    ObservationSource.MANUAL,
                    f"isolation-fixture-{store.store_id}-{fixture_object.item_id}",
                    _OBSERVED_AT,
                ),
            ),
            catalog_version=catalog_version,
            sort_order=sort_order,
        )
        catalog.add_image(
            store.scope,
            item_id=fixture_object.item_id,
            sha256=display_sha,
            source_sha256=fixture_object.source_sha256,
            media_type=derivative.media_type,
            width=derivative.width,
            height=derivative.height,
            byte_size=len(derivative.data),
            capture_time=None,
            capture_time_source=CaptureTimeSource.UNKNOWN,
        )
        catalog.put_ready_embedding(
            store.scope,
            item_id=fixture_object.item_id,
            vector=_vector(fixture_object.vector_index),
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            image_sha256=display_sha,
        )


def _vector(index: int) -> tuple[float, ...]:
    return tuple(1.0 if position == index else 0.0 for position in range(EMBEDDING_DIMENSIONS))


def _jpeg(color: tuple[int, int, int], size: tuple[int, int] = (64, 48)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()
