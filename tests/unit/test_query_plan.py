import unittest
from decimal import Decimal

from apps.web.server import ROOT
from backend.catalog.pitch import load_pitch_catalog
from backend.search.multimodal import MultimodalSearchService
from backend.search.price import parse_price
from contracts.search import SearchQuery
from tests.unit.test_pitch import StubEncoder


class QueryPlanTest(unittest.TestCase):
    def test_semantics_and_operators(self) -> None:
        self.assertEqual(parse_price("cool fantasy beer mug").visual, "cool fantasy beer mug")
        for query, value, accepts in [
            ("under $50", "50", False),
            ("up to $50", "50", True),
            ("over $25", "25", False),
            ("at least $25", "25", True),
            ("between $25 and $50", "25", True),
            ("between $25 and $50", "50", True),
            ("between $25 and $50", "50.01", False),
        ]:
            with self.subTest(query=query, value=value):
                plan = parse_price(query)
                self.assertEqual(plan.accepts(Decimal(value)), accepts)
                self.assertFalse(plan.accepts(None))
        for phrase in ("cheapest", "lowest price"):
            plan = parse_price(phrase + " blue one under $50")
            self.assertEqual(
                (plan.visual, plan.sort, plan.maximum), ("blue one", "price_asc", Decimal("50"))
            )
        for phrase in ("most expensive", "highest price"):
            self.assertEqual(parse_price(phrase + " one").visual, "")
            self.assertEqual(parse_price(phrase + " floral one").visual, "floral one")
            self.assertEqual(parse_price(phrase).sort, "price_desc")
            self.assertFalse(parse_price(phrase).accepts(None))
        self.assertTrue(parse_price("blue").accepts(None))
        self.assertEqual(parse_price("over $25 under $50").minimum, Decimal("25"))
        with self.assertRaises(ValueError):
            parse_price("between $50 and $25")
        with self.assertRaises(ValueError):
            parse_price("cheapest most expensive")

    def test_deterministic_sort_composition_and_ties(self) -> None:
        catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
        service = MultimodalSearchService(
            catalog, ROOT / "data/pitch/image_index.json", StubEncoder()
        )
        for query in (
            "cheapest one",
            "most expensive one",
            "cheapest blue one under $50",
            "most expensive blue one",
            "cheapest clear one",
        ):
            plan = parse_price(query)
            eligible = [i for i in catalog.items if plan.accepts(i.price)]
            if plan.visual:
                relevant = service.search(
                    SearchQuery(
                        text=plan.visual + (" under $50" if plan.maximum else ""), limit=100
                    )
                )
                by_id = {i.item_id: i for i in eligible}
                eligible = [by_id[r.item_id] for r in relevant.results if r.item_id in by_id][:12]
            direction = 1 if plan.sort == "price_asc" else -1
            expected = sorted(eligible, key=lambda i: (direction * i.price, i.item_id))[:12]
            result = service.search(SearchQuery(text=query))
            self.assertEqual([r.item_id for r in result.results], [i.item_id for i in expected])
            self.assertEqual(result.results, service.search(SearchQuery(text=query)).results)
        known = [i for i in catalog.items if i.price is not None]
        self.assertLess(len({i.price for i in known}), len(known))  # Actual ties exercised.
