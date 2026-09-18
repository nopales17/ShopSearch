"""Store-scoped platform contracts.

`StoreScope` is the mandatory store scope for catalog, media, embedding and
telemetry operations (ADR-0005). `Store` plus `StorePresentation` carry the
founder-provisioned store record, including the public claim wording that
ADR-0005 moved out of code and into store configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from contracts.catalog import StoreConfiguration

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")


@dataclass(frozen=True)
class StoreScope:
    """The one store a catalog, media, embedding or telemetry operation applies to."""

    store_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.store_id, str) or not _IDENTIFIER.fullmatch(self.store_id):
            raise ValueError("store_id must be a safe identifier")


@dataclass(frozen=True)
class HeroImage:
    """A configured storefront hero image reference, by item ID rather than path."""

    role: str
    item_id: str
    src: str
    alt: str
    label: str
    width: int
    height: int


@dataclass(frozen=True)
class StorePresentation:
    """Store-specific public presentation and claim wording.

    These strings were Form & Field literals in `apps/web/pitch_views.py` before
    S2. They now live in the store record so a second store never inherits another
    store's branding, chips, categories, credits or disclosures.
    """

    wordmark_primary: str
    wordmark_accent: str
    wordmark_suffix: str
    wordmark_aria_label: str
    page_title_suffix: str
    meta_description: str
    demo_strip: str
    catalog_nav_label: str
    about_nav_label: str
    tagline: str
    footer_disclosure: str
    footer_credits_label: str
    dialog_eyebrow: str
    dialog_title: str
    dialog_copy: str
    dialog_done_label: str
    hero_eyebrow: str
    hero_title_html: str
    hero_description: str
    hero_cta_label: str
    hero_footnote_template: str
    hero_images: tuple[HeroImage, ...]
    discover_heading_html: str
    discover_example_query: str
    featured_eyebrow: str
    featured_heading: str
    featured_link_label: str
    catalog_eyebrow: str
    catalog_title_html: str
    catalog_intro: str
    search_placeholder: str
    query_chips_label: str
    example_queries: tuple[str, ...]
    categories: tuple[str, ...]
    results_summary_template: str
    catalog_disclaimer: str
    noscript_notice: str
    card_price_label: str
    price_unknown_label: str
    item_collection_suffix: str
    item_price_label: str
    item_description_template: str
    item_source_value: str
    item_fine_print_html: str
    item_source_link_label: str
    credits_eyebrow: str
    credits_title_html: str
    credits_copy_html: str
    credits_policy_url: str
    credits_policy_label: str
    public_claim: str


@dataclass(frozen=True)
class Store:
    """A founder-provisioned store record resolved by hostname."""

    store_id: str
    display_name: str
    currency: str
    timezone: str
    is_demo: bool
    presentation: StorePresentation
    created_at: str | None = None

    @property
    def scope(self) -> StoreScope:
        return StoreScope(self.store_id)

    def configuration(self) -> StoreConfiguration:
        return StoreConfiguration(
            store_id=self.store_id,
            display_name=self.display_name,
            currency=self.currency,
            timezone=self.timezone,
            public_claim=self.presentation.public_claim,
        )
