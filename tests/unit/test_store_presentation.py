from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from apps.web import pitch_views as views
from apps.web.server import ROOT
from backend.catalog.pitch import load_pitch_catalog
from backend.stores.demo import load_demo_store
from backend.stores.validation import StoreValidationError, validate_store
from contracts.store import Store

# SHA-256 of the four deterministic pages rendered at S1 commit 71aac18, captured
# before pitch_views.py was changed. Byte-identity is a documented S2 criterion.
S1_PAGE_HASHES = {
    "home": "d7d863ff4d775e0f9b0cbe1e75f007252077483f04b0ef6a50f763dcbde16ac2",
    "catalog": "72728b9e964018027b5a52d8f88b24b7636a1da1c964cb24a8db04b1bf691d94",
    "credits": "369b0906200cda396b4bb867a26ea8b032c943371e2456c89282eb80d2cc6754",
    "item": "c7477db76113da22188db5dac07ac35c6144695ae463a20e0d4d6dca1c4f9ce3",
}

# Distinctive demo-store strings that must now live in the store record, not the
# view module. Structural markup and generic UX labels intentionally stay there.
DEMO_VIEW_LITERALS = [
    "FORM",
    "Form & Field",
    "GLASS, VESSELS",
    "pitch-128096",
    "pitch-160044",
    "Vases",
    "Drinkware",
    "small blue one",
    "small blue under $50",
    "Cleveland Museum of Art",
    "An imagined shop",
    "THE DEMO COLLECTION",
    "illustrative demo price",
    "SEE WHAT'S IN STORE",
    "Good things.",
    "A few things to fall for",
    "this local demo",
    "Curated photo demo",
]


def demo_pages() -> tuple[Store, dict[str, str]]:
    store = load_demo_store()
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json", store.configuration())
    item = catalog.get("pitch-128096")
    assert item is not None
    pages = {
        "home": views.home(catalog, store),
        "catalog": views.catalog_page(catalog, store),
        "credits": views.credits(catalog, store),
        "item": views.item_page(item, store, "", None),
    }
    return store, pages


class S1ByteParityTest(unittest.TestCase):
    def test_demo_pages_match_s1_bytes(self) -> None:
        _, pages = demo_pages()
        self.assertEqual(
            {name: hashlib.sha256(html.encode()).hexdigest() for name, html in pages.items()},
            S1_PAGE_HASHES,
        )

    def test_enumerated_store_elements_still_render(self) -> None:
        _, pages = demo_pages()
        home = pages["home"]
        catalog = pages["catalog"]
        self.assertIn('class="wordmark"', home)
        self.assertIn("FORM <span>&</span> FIELD", home)
        self.assertIn('src="/images/pitch-128096.jpg"', home)
        self.assertIn('src="/images/pitch-160044.jpg"', home)
        for category in ["Vases", "Bowls", "Drinkware", "Curios"]:
            self.assertIn(f"<option>{category}</option>", catalog)
        self.assertIn('data-query="small blue one"', catalog)
        self.assertIn("not offered for sale", home)
        self.assertIn("Visual similarity does not confirm availability", catalog)


class StoreSourcedPresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = load_demo_store()
        self.catalog = load_pitch_catalog(
            ROOT / "data/pitch/catalog.json", self.store.configuration()
        )

    def test_second_store_branding_replaces_demo_copy(self) -> None:
        presentation = replace(
            self.store.presentation,
            wordmark_primary="NORTH",
            wordmark_accent="+",
            wordmark_suffix="STAR",
            footer_disclosure="Configured disclosure for another store.",
            catalog_disclaimer="Configured disclaimer for another store.",
            example_queries=("bright thing",),
            categories=("Lamps",),
        )
        other = replace(self.store, store_id="second-store", presentation=presentation)
        home = views.home(self.catalog, other)
        catalog = views.catalog_page(self.catalog, other)
        self.assertIn("NORTH <span>+</span> STAR", home)
        self.assertNotIn("FORM", home)
        self.assertIn("Configured disclosure for another store.", home)
        self.assertNotIn("not offered for sale", home)
        self.assertIn("<option>Lamps</option>", catalog)
        self.assertNotIn("<option>Vases</option>", catalog)
        self.assertIn('data-query="bright thing"', catalog)
        self.assertNotIn('data-query="small blue one"', catalog)
        self.assertIn("Configured disclaimer for another store.", catalog)

    def test_demo_mandatory_disclosures_cannot_be_removed_by_branding(self) -> None:
        for field, value in [
            ("footer_disclosure", "Configured branding copy."),
            ("catalog_disclaimer", "Configured branding disclaimer."),
            ("item_fine_print_html", "Configured item footer."),
            ("dialog_copy", "Configured dialog copy."),
            ("credits_copy_html", "Configured credits copy."),
            ("public_claim", "Configured public claim."),
        ]:
            with self.subTest(field=field), self.assertRaises(StoreValidationError):
                validate_store(
                    replace(
                        self.store,
                        presentation=replace(self.store.presentation, **{field: value}),
                    )
                )


class StoreLiteralScanTest(unittest.TestCase):
    def test_view_module_keeps_no_demo_specific_literals(self) -> None:
        source = (ROOT / "apps/web/pitch_views.py").read_text(encoding="utf-8")
        for literal in DEMO_VIEW_LITERALS:
            with self.subTest(literal=literal):
                self.assertNotIn(literal, source)
