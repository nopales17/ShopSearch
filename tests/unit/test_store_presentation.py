from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from apps.web import pitch_views as views
from backend.catalog.pitch import load_pitch_catalog
from backend.platform.paths import REPOSITORY_ROOT as ROOT
from backend.stores.demo import load_demo_store
from backend.stores.validation import StoreValidationError, validate_store
from contracts.store import Store

# SHA-256 of the four deterministic pages. These were captured at S1 commit 71aac18
# and pinned as the S2 byte-identity criterion; S11 deliberately revised the demo
# store's public-copy fields (meta description, footer disclosure, catalog disclaimer,
# credits copy, public claim) so that CMA/CC0 attribution is scoped to the committed
# museum collection and locally uploaded demo items are described separately. The
# museum detail body itself is unchanged: `item` differs only by the shared page
# meta description. Update these hashes only with a reviewed copy change like that one.
S1_PAGE_HASHES = {
    "home": "4748328b6f05c46e90a105ef06d78e24d475d75f35d27c40333aa37789743f94",
    "catalog": "f260dcecf99065f4924d0155ccea2f78ae2a6c342fcbd2b65ad062c5503c2c71",
    "credits": "f1b5c7c2849309f0ed218b0306225b75cbca809d47c97f8ba5be794049c057b7",
    "item": "9b63826d2089d09aeb206089a2e47e2d200b1b9c775b0dada18d70c8abad7f2c",
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


class MixedProvenanceRenderingTest(unittest.TestCase):
    """S11: a locally uploaded demo item never inherits museum attribution.

    `attributes["merchant_upload"] is True` is the explicit branch. The wording itself
    still comes from the store record, so the view module keeps no Form & Field copy.
    """

    def setUp(self) -> None:
        self.store = load_demo_store()
        self.catalog = load_pitch_catalog(
            ROOT / "data/pitch/catalog.json", self.store.configuration()
        )
        museum = self.catalog.get("pitch-128096")
        assert museum is not None
        self.uploaded = replace(
            museum,
            item_id="local-upload-1",
            title="Local uploaded bowl",
            category="Demo uploads",
            attributes={"source_title": "Local uploaded bowl", "merchant_upload": True},
        )

    def test_demo_upload_renders_only_the_local_demo_wording(self) -> None:
        page = views.item_page(self.uploaded, self.store, "", None)
        detail = page.split('<div class="detail-copy">')[1].split("</main>")[0]
        self.assertIn("Uploaded through the local merchant demo", detail)
        self.assertIn("not part of the committed museum collection", detail)
        for forbidden in (
            "Original title",
            "Dimensions",
            "Cleveland Museum of Art",
            "CC0",
            "View the original source",
            "accession",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, detail)

    def test_museum_item_keeps_its_attribution(self) -> None:
        museum = self.catalog.get("pitch-128096")
        assert museum is not None
        detail = (
            views.item_page(museum, self.store, "", None)
            .split('<div class="detail-copy">')[1]
            .split("</main>")[0]
        )
        self.assertIn("Original title", detail)
        self.assertIn("Dimensions", detail)
        self.assertIn("The Cleveland Museum of Art · CC0", detail)
        self.assertIn("View the original source", detail)
        self.assertNotIn("Uploaded through the local merchant demo", detail)

    def test_credits_list_stays_museum_source_only(self) -> None:
        catalog = replace(self.catalog, items=(*self.catalog.items, self.uploaded))
        page = views.credits(catalog, self.store)
        self.assertNotIn("Local uploaded bowl", page)
        self.assertIn(self.catalog.items[0].title, page)
        self.assertIn("committed museum collection", page)

    def test_other_stores_keep_their_configured_item_wording(self) -> None:
        presentation = replace(
            self.store.presentation, item_source_value="Photographed for this store"
        )
        other = replace(
            self.store, store_id="second-store", is_demo=False, presentation=presentation
        )
        page = views.item_page(self.uploaded, other, "", None)
        self.assertIn("Photographed for this store", page)
        self.assertNotIn("Uploaded through the local merchant demo", page)
