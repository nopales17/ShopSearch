"""Store-record validation, including the mandatory demo-store disclosures.

ADR-0005 §7 moves public claim wording and disclosures into the store record.
ADR-0005 §8 additionally makes the demo store's CC0/illustrative-price/not-for-sale
disclosures mandatory. Branding configuration therefore cannot remove them: a
demo store record missing any required assertion is rejected before persistence
and before rendering.
"""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from contracts.store import Store, StorePresentation, StoreScope

_CURRENCY = re.compile(r"[A-Z]{3}")

# Required assertions per presentation field. Word-for-word wording still comes
# from the store record; these substrings are the invariant that must survive.
DEMO_REQUIRED_DISCLOSURES: dict[str, tuple[str, ...]] = {
    "footer_disclosure": (
        "CC0",
        "not offered for sale",
        "Prices are illustrative",
        "No shop adoption",
    ),
    "catalog_disclaimer": (
        "Illustrative prices",
        "Visual similarity does not confirm availability",
    ),
    "item_fine_print_html": ("not for sale",),
    "dialog_copy": ("sends no calls", "opens no directions"),
    "credits_copy_html": ("CC0",),
    "public_claim": ("not store inventory",),
}

_REQUIRED_TEXT_FIELDS = tuple(
    name
    for name in StorePresentation.__dataclass_fields__
    if name not in {"hero_images", "example_queries", "categories"}
)


class StoreValidationError(ValueError):
    """Raised when a store record cannot safely enter the registry."""


def validate_store(store: Store) -> None:
    StoreScope(store.store_id)
    if not isinstance(store.display_name, str) or not store.display_name.strip():
        raise StoreValidationError("display_name must be a non-empty string")
    if not isinstance(store.currency, str) or not _CURRENCY.fullmatch(store.currency):
        raise StoreValidationError("currency must be a three-letter uppercase code")
    try:
        ZoneInfo(store.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise StoreValidationError("timezone must be a valid IANA timezone") from error
    presentation = store.presentation
    for name in _REQUIRED_TEXT_FIELDS:
        value = getattr(presentation, name)
        if not isinstance(value, str) or not value.strip():
            raise StoreValidationError(f"presentation.{name} must be a non-empty string")
    for name in ("example_queries", "categories"):
        values = getattr(presentation, name)
        if (
            not isinstance(values, tuple)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise StoreValidationError(f"presentation.{name} must be a non-empty string list")
    template = presentation.coverage_disclosure_template
    for token in ("{excluded}", "{published}"):
        if token not in template:
            raise StoreValidationError(
                "coverage_disclosure_template must state the excluded and published counts"
            )
    try:
        template.format(excluded=1, published=2)
    except (KeyError, IndexError, ValueError) as error:
        raise StoreValidationError("coverage_disclosure_template is not formattable") from error
    roles = [image.role for image in presentation.hero_images]
    if sorted(roles) != ["inset", "main"]:
        raise StoreValidationError("presentation.hero_images needs exactly one main and one inset")
    for image in presentation.hero_images:
        if not image.item_id or not image.src.startswith("/images/"):
            raise StoreValidationError("hero images must reference a store item and media path")

    if store.is_demo:
        for field, required in DEMO_REQUIRED_DISCLOSURES.items():
            text = getattr(presentation, field)
            for phrase in required:
                if phrase not in text:
                    raise StoreValidationError(
                        f"demo store is missing a mandatory disclosure phrase "
                        f"({phrase!r} not in presentation.{field})"
                    )
