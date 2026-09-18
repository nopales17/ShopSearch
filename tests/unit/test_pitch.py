from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.catalog.pitch import load_pitch_catalog
from backend.platform.paths import REPOSITORY_ROOT as ROOT
from backend.search.multimodal import MultimodalSearchService
from backend.search.price import parse_price
from backend.search.vector_source import CommittedIndexVectorSource
from backend.stores.demo import demo_store_configuration
from contracts.search import SearchQuery


class StubEncoder:
    """Transport/constraint tests only; never reported as model-quality evidence."""

    def text(self, text: str) -> tuple[float, ...]:
        return (1.0,) + (0.0,) * 511


def pitch_vector_source(catalog) -> CommittedIndexVectorSource:
    """Compatibility source over the committed index, keyed by item ID."""

    return CommittedIndexVectorSource(
        ROOT / "data/pitch/image_index.json",
        expected_catalog_version=catalog.version,
        expected_model_id=MODEL_ID,
        expected_model_revision=MODEL_REVISION,
    )


class PitchBoundaryTest(unittest.TestCase):
    def test_frozen_evaluation_matches_built_index(self) -> None:
        index = json.loads((ROOT / "data/pitch/image_index.json").read_text())
        self.assertEqual(
            index["evaluation_sha256"],
            hashlib.sha256(
                (ROOT / "experiments/search_v0/pitch_evaluation.json").read_bytes()
            ).hexdigest(),
        )
        catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json", demo_store_configuration())
        self.assertEqual(len(catalog.items), 90)
        self.assertEqual(
            index["expanded_evaluation_sha256"],
            hashlib.sha256(
                (ROOT / "experiments/search_v0/expanded_evaluation.json").read_bytes()
            ).hexdigest(),
        )
        for item in catalog.items:
            self.assertEqual(item.attributes["license"], "CC0")
            self.assertIsNone(item.attributes["photo_captured_at"])
            self.assertIn("not store inventory", catalog.public_snapshot(item)["public_claim"])

    def test_price_boundaries_and_unknowns(self) -> None:
        for query, inclusive in [
            ("small blue under $50", False),
            ("up to $50", True),
            ("less than 50", False),
            ("at most $50", True),
        ]:
            with self.subTest(query=query):
                parsed = parse_price(query)
                self.assertEqual(parsed.maximum, Decimal("50"))
                self.assertEqual(parsed.accepts(Decimal("50")), inclusive)
                self.assertTrue(parsed.accepts(Decimal("49.99")))
                self.assertFalse(parsed.accepts(None))
                self.assertFalse(parsed.accepts(Decimal("50.01")))
        self.assertEqual(parse_price("small blue under $50").visual, "small blue")
        self.assertEqual(parse_price("under $50 up to $40").maximum, Decimal("40"))
        self.assertFalse(parse_price("up to $50 under $50").inclusive)

    def test_search_enforces_constraints_and_does_not_use_tags(self) -> None:
        catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json", demo_store_configuration())
        service = MultimodalSearchService(catalog, pitch_vector_source(catalog), StubEncoder())
        query = SearchQuery(text="under $50", limit=100)
        before = service.search(query)
        self.assertTrue(before.results)
        for result in before.results:
            self.assertLess(catalog.items_by_result(result.item_id).price, Decimal("50"))
        self.assertNotIn("pitch-159994", [r.item_id for r in before.results])
        inclusive = service.search(SearchQuery(text="up to $50", limit=100))
        self.assertIn("pitch-159994", [r.item_id for r in inclusive.results])
        self.assertEqual(service.search(SearchQuery(text="under $1")).results, ())
        for item in catalog.items:
            item.attributes["tags"] = ["arbitrary"]
            item.title = "changed label"
        self.assertEqual(before.results, service.search(query).results)

    def test_stale_or_mismatched_index_is_rejected(self) -> None:
        catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json", demo_store_configuration())
        original = json.loads((ROOT / "data/pitch/image_index.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            changes = [
                {"catalog_version": "wrong"},
                {"model_revision": "wrong"},
                {"item_ids": original["item_ids"][:-1]},
                {"vectors": original["vectors"][:-1]},
            ]
            for change in changes:
                index = dict(original)
                index.update(change)
                path.write_text(json.dumps(index))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    CommittedIndexVectorSource(
                        path,
                        expected_catalog_version=catalog.version,
                        expected_model_id=MODEL_ID,
                        expected_model_revision=MODEL_REVISION,
                    )

    def test_index_missing_a_catalog_item_is_excluded_and_reported(self) -> None:
        catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json", demo_store_configuration())
        original = json.loads((ROOT / "data/pitch/image_index.json").read_text())
        missing_item = original["item_ids"][-1]
        with tempfile.TemporaryDirectory() as directory:
            index = dict(original)
            index["item_ids"] = original["item_ids"][:-1]
            index["vectors"] = original["vectors"][:-1]
            path = Path(directory) / "index.json"
            path.write_text(json.dumps(index))
            source = CommittedIndexVectorSource(
                path,
                expected_catalog_version=catalog.version,
                expected_model_id=MODEL_ID,
                expected_model_revision=MODEL_REVISION,
            )
            response = MultimodalSearchService(catalog, source, StubEncoder()).search(
                SearchQuery(text="blue", limit=100)
            )
        self.assertNotIn(missing_item, [result.item_id for result in response.results])
        coverage = response.coverage
        assert coverage is not None
        self.assertEqual(coverage.published, 90)
        self.assertEqual(coverage.ready, 89)
        self.assertEqual(coverage.excluded_unindexed, 1)
        self.assertTrue(coverage.visual_text)
