"""Run the frozen P1 benchmark without changing judgments or tuning retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import time
from datetime import datetime, timezone

from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ROOT, ClipEncoder
from backend.catalog.pitch import load_pitch_catalog
from backend.search.multimodal import MultimodalSearchService
from backend.search.price import parse_price
from contracts.search import SearchQuery


def quality(ids: list[str], judgments: dict[str, int]) -> dict[str, float | bool]:
    grades = [judgments.get(item_id.removeprefix("pitch-"), 0) for item_id in ids[:5]]
    ideal = sorted(judgments.values(), reverse=True)[:5]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return {
        "strong_hit_at_3": 2 in grades[:3],
        "precision_at_5": sum(g > 0 for g in grades) / 5,
        "ndcg_at_5": dcg / idcg if idcg else 0.0,
    }


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def main() -> None:
    evaluation_path = ROOT / "experiments/search_v0/pitch_evaluation.json"
    evaluation = json.loads(evaluation_path.read_text())
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
    start = time.perf_counter()
    encoder = ClipEncoder()
    service = MultimodalSearchService(catalog, ROOT / "data/pitch/image_index.json", encoder)
    cold_seconds = time.perf_counter() - start
    rows = []
    for case in evaluation["queries"]:
        start = time.perf_counter()
        response = service.search(SearchQuery(text=case["query"], limit=5))
        elapsed = (time.perf_counter() - start) * 1000
        ids = [r.item_id for r in response.results]
        parsed = parse_price(case["query"])
        violations = [i for i in ids if not parsed.accepts(catalog.items_by_result(i).price)]
        row = {
            "query": case["query"],
            "top5": ids,
            "first_ms": elapsed,
            "price_violations": violations,
        }
        if case.get("price_only"):
            row.update({"passed": bool(ids) and not violations})
        else:
            row.update(quality(ids, case["relevance"]))
            row["passed"] = row["strong_hit_at_3"] and not violations
            # A manually tagged lexical comparator; not used by the CLIP runtime.
            tokens = parsed.visual.lower().split()
            eligible = [item for item in catalog.items if parsed.accepts(item.price)]
            lexical = sorted(
                eligible,
                key=lambda item: (
                    -sum(
                        token in (item.title + " " + " ".join(item.attributes["tags"])).lower()
                        for token in tokens
                    ),
                    item.item_id,
                ),
            )[:5]
            lexical_ids = [i.item_id for i in lexical]
            row["lexical"] = {"top5": lexical_ids, **quality(lexical_ids, case["relevance"])}
        rows.append(row)
    uncached, cached = [], []
    for _ in range(10):
        for case in evaluation["queries"]:
            encoder.text.cache_clear()
            start = time.perf_counter()
            service.search(SearchQuery(text=case["query"]))
            uncached.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            service.search(SearchQuery(text=case["query"]))
            cached.append((time.perf_counter() - start) * 1000)
    controls = {
        query: [r.item_id for r in service.search(SearchQuery(text=query, limit=5)).results]
        for query in evaluation["controls"]
    }
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "catalog_version": catalog.version,
        "evaluation_sha256": hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device": "cpu",
            "threads": 4,
        },
        "cold_init_seconds": cold_seconds,
        "queries": rows,
        "controls": controls,
        "passed_queries": sum(bool(r["passed"]) for r in rows),
        "query_count": len(rows),
        "mean_ndcg_at_5": statistics.mean(r["ndcg_at_5"] for r in rows if "ndcg_at_5" in r),
        "mean_precision_at_5": statistics.mean(
            r["precision_at_5"] for r in rows if "precision_at_5" in r
        ),
        "uncached_warm_ms": {
            "n": len(uncached),
            "p50": statistics.median(uncached),
            "p95": percentile(uncached, 0.95),
        },
        "cached_ms": {
            "n": len(cached),
            "p50": statistics.median(cached),
            "p95": percentile(cached, 0.95),
        },
    }
    output = ROOT / "data/local/pitch-evaluations"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
