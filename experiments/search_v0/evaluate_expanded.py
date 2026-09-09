"""One fixed comparison; --freeze creates proxy judgments BEFORE embedding/ranking."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from datetime import datetime, timezone

from backend.adapters.clip import ROOT, ClipEncoder
from backend.catalog.pitch import load_pitch_catalog
from backend.search.multimodal import MultimodalSearchService
from backend.search.price import parse_price
from contracts.search import SearchQuery
from experiments.search_v0.evaluate_pitch import quality

DIRECTORY = ROOT / "experiments/search_v0"
# Predeclared proxy concepts, not descriptions inferred from retrieval output.
PROXIES = {
    "small blue one": [["blue", "aqua", "turquoise"]],
    "colorful": [["mosaic", "millefiori", "iridescent", "enameled", "enamel"]],
    "simple clear one": [["clear", "transparent"]],
    "dark and weird": [["black", "dark"], ["face", "janus", "snake", "serpent"]],
    "small blue under $50": [["blue", "aqua", "turquoise"]],
    "green jug": [["green"], ["jug", "pitcher"]],
    "red goblet": [["red", "ruby"], ["goblet"]],
    "gold vase": [["gold", "gilt"], ["vase"]],
    "clear drinking glass": [
        ["clear", "transparent"],
        ["goblet", "cup", "tumbler", "beaker", "glass"],
    ],
}


def freeze() -> None:
    path = DIRECTORY / "expanded_evaluation.json"
    if path.exists():
        raise ValueError("expanded judgments already frozen; do not overwrite")
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
    original = json.loads((DIRECTORY / "pitch_evaluation.json").read_text())
    manifest = json.loads((ROOT / "data/pitch/expansion_manifest.json").read_text())
    for case in original["queries"]:
        if case.get("price_only"):
            continue
        for item in catalog.items:
            if item.attributes["source_id"] in manifest["original_ids"]:
                continue
            text = (
                item.attributes["source_title"] + " " + (item.attributes["materials"] or "")
            ).lower()
            groups = PROXIES[case["query"]]
            hits = sum(any(word in text for word in group) for group in groups)
            # Color-only evidence cannot establish smallness, simplicity or mood.
            grade = 2 if hits == len(groups) and len(groups) > 1 else int(hits > 0)
            if case["query"] == "colorful" and hits:
                grade = 2
            case["relevance"][str(item.attributes["source_id"])] = grade
    path.write_text(
        json.dumps(
            {
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "catalog_version": catalog.version,
                "hybrid": "0.70 minmax CLIP + 0.30 minmax lexical",
                "label_scope": "original P1 agent judgments plus incomplete source-metadata proxies for new items; not independent human truth",
                "proxy_rules": PROXIES,
                "queries": original["queries"],
            },
            indent=2,
        )
        + "\n"
    )
    print("Frozen expanded proxy judgments before retrieval")


def normalized(scores: dict[str, float]) -> dict[str, float]:
    low, high = min(scores.values()), max(scores.values())
    return {i: (v - low) / (high - low) if high > low else 0.0 for i, v in scores.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze()
        return
    output = DIRECTORY / "expanded_results.json"
    if output.exists():
        raise ValueError("results exist; this bounded experiment must not overwrite history")
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
    evaluation = json.loads((DIRECTORY / "expanded_evaluation.json").read_text())
    assert evaluation["catalog_version"] == catalog.version
    original = json.loads((DIRECTORY / "pitch_evaluation.json").read_text())
    old_ids = {
        f"pitch-{i}"
        for i in json.loads((ROOT / "data/pitch/expansion_manifest.json").read_text())[
            "original_ids"
        ]
    }
    start = time.perf_counter()
    encoder = ClipEncoder()
    service = MultimodalSearchService(catalog, ROOT / "data/pitch/image_index.json", encoder)
    initialization = time.perf_counter() - start
    scopes = {}
    for name, benchmark, allowed in (
        ("original_30_replay", original, old_ids),
        ("expanded_90_proxy", evaluation, {i.item_id for i in catalog.items}),
    ):
        rows = []
        for case in benchmark["queries"]:
            plan = parse_price(case["query"])
            start = time.perf_counter()
            response = service.search(SearchQuery(text=case["query"], limit=100))
            elapsed = (time.perf_counter() - start) * 1000
            clip = {r.item_id: r.semantic_score for r in response.results if r.item_id in allowed}
            tokens = plan.visual.lower().split()
            lexical = {
                i: float(
                    sum(
                        token
                        in (
                            catalog.items_by_result(i).title
                            + " "
                            + " ".join(catalog.items_by_result(i).attributes["tags"])
                        ).lower()
                        for token in tokens
                    )
                )
                for i in clip
            }
            nc, nl = normalized(clip), normalized(lexical)
            hybrid = {i: 0.70 * nc[i] + 0.30 * nl[i] for i in clip}
            row = {"query": case["query"], "clip_ms": elapsed, "rankings": {}}
            for method, scores in (("clip", clip), ("lexical", lexical), ("hybrid", hybrid)):
                ids = sorted(scores, key=lambda i: (-scores[i], i))[:5]
                metrics = {} if case.get("price_only") else quality(ids, case["relevance"])
                row["rankings"][method] = {
                    "top5": ids,
                    **metrics,
                    "price_violations": [
                        i for i in ids if not plan.accepts(catalog.items_by_result(i).price)
                    ],
                }
            rows.append(row)
        summary = {}
        for method in ("clip", "lexical", "hybrid"):
            visual = [r["rankings"][method] for r in rows if "ndcg_at_5" in r["rankings"][method]]
            summary[method] = {
                "mean_ndcg_at_5": statistics.mean(r["ndcg_at_5"] for r in visual),
                "mean_precision_at_5": statistics.mean(r["precision_at_5"] for r in visual),
                "strong_top3_count": sum(r["strong_hit_at_3"] for r in visual),
                "visual_query_count": len(visual),
                "hard_price_violations": sum(
                    len(r["rankings"][method]["price_violations"]) for r in rows
                ),
            }
        scopes[name] = {"summary": summary, "queries": rows}
    checks = []
    for query in (
        "most expensive blue one",
        "cheapest clear one",
        "colorful under $50",
        "most expensive floral one",
        "cheapest blue one under $50",
        "blue one over $25",
        "between $25 and $50",
        "most expensive one",
        "cool fantasy beer mug",
    ):
        plan = parse_price(query)
        response = service.search(SearchQuery(text=query))
        items = [catalog.items_by_result(r.item_id) for r in response.results]
        prices = [i.price for i in items]
        ordered = plan.sort == "relevance" or prices == sorted(
            prices, reverse=plan.sort == "price_desc"
        )
        checks.append(
            {
                "query": query,
                "semantic": plan.visual,
                "filters": plan.filters(),
                "ordered": ordered,
                "hard_price_violations": [i.item_id for i in items if not plan.accepts(i.price)],
                "ids": [i.item_id for i in items],
                "prices": [str(p) for p in prices],
            }
        )
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "catalog_version": catalog.version,
        "evaluation_sha256": hashlib.sha256(
            (DIRECTORY / "expanded_evaluation.json").read_bytes()
        ).hexdigest(),
        "index_sha256": hashlib.sha256(
            (ROOT / "data/pitch/image_index.json").read_bytes()
        ).hexdigest(),
        "initialization_seconds": initialization,
        "scopes": scopes,
        "composition_checks": checks,
        "hybrid_promoted": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: data["summary"] for name, data in scopes.items()}, indent=2))
    assert all(c["ordered"] and not c["hard_price_violations"] for c in checks)


if __name__ == "__main__":
    main()
