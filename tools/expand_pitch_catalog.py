"""Mechanical CC0 expansion using the existing downloader/publisher, no models."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from tools.prepare_pitch_photos import CANDIDATES, ROOT, candidates, publish_selection


def category(title: str) -> str:
    if re.search(r"bowl|dish|plate", title, re.I):
        return "Bowls"
    if re.search(r"cup|goblet|tumbler|beaker|mug", title, re.I):
        return "Drinkware"
    if re.search(r"vase|bottle|jug|pitcher|flask|amphor", title, re.I):
        return "Vases"
    return "Curios"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    args = parser.parse_args()
    selection_path = ROOT / "data/pitch/selection.json"
    selection = json.loads(selection_path.read_text())
    old_ids = {r["source_id"] for r in selection}
    buckets = defaultdict(list)
    for record in sorted(json.load(open(args.source))["data"], key=lambda r: r["id"]):
        if (
            record["id"] not in old_ids
            and record["share_license_status"] == "CC0"
            and record["type"] == "Glass"
            and record.get("images", {}).get("web")
            and re.search(
                r"vase|bowl|cup|flask|bottle|goblet|tumbler|beaker|jug|amphoriskos|box|inkwell",
                record["title"],
                re.I,
            )
            and not record["title"].startswith("Cover for")
        ):
            buckets[category(record["title"])].append(record)
    chosen = []
    while len(chosen) < 90 - len(selection) and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(chosen) < 90 - len(selection):
                chosen.append(buckets[key].pop(0))
    if len(chosen) + len(selection) != 90:
        raise ValueError("not enough permitted distinct candidates")
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    batch = CANDIDATES / "expansion-source.json"
    batch.write_text(json.dumps({"data": chosen}))
    candidates(batch)
    for record in chosen:
        source_text = record["title"] + " " + (record["technique"] or "")
        selection.append(
            {
                "source_id": record["id"],
                "title": record["title"],
                "category": category(record["title"]),
                "price": None if record["id"] % 17 == 0 else str(15 + (record["id"] % 18) * 5),
                "tags": sorted(set(re.findall(r"[a-z]+", source_text.lower()))),
            }
        )
    selection_path.write_text(json.dumps(selection, indent=2) + "\n")
    publish_selection()
    (ROOT / "data/pitch/expansion_manifest.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "original_ids": sorted(old_ids),
                "added_ids": [r["id"] for r in chosen],
                "selection": "CC0 Glass; vessel/object title filter; ascending source ID, round-robin category; preserve original 30; add 60",
                "price_rule": "illustrative USD 15 + (source_id % 18)*5; null if source_id %17 == 0",
                "tags_rule": "unique lowercase words from source title + technique; no agent descriptions",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
