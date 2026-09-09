"""Download only explicitly CC0 museum photographs for manual pitch curation.

Images are documentary photographs of glass objects, not items offered for sale.
No image generation, segmentation or automatic publication occurs here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data/local/pitch-candidates"


def candidates(source: Path) -> None:
    from PIL import Image, ImageDraw

    records = json.loads(source.read_text())["data"]
    allowed_titles = (
        "vase",
        "bowl",
        "cup",
        "flask",
        "bottle",
        "goblet",
        "tumbler",
        "beaker",
        "jug",
        "amphoriskos",
        "box",
        "inkwell",
    )
    selected = [
        r
        for r in records
        if r["share_license_status"] == "CC0"
        and any(word in r["title"].lower() for word in allowed_titles)
        and not r["title"].startswith("Cover for")
    ][:60]
    CANDIDATES.mkdir(parents=True, exist_ok=True)

    def download(record: dict) -> None:
        path = CANDIDATES / f"{record['id']}.jpg"
        if not path.exists():
            request = Request(
                record["images"]["web"]["url"],
                headers={"User-Agent": "ShopSearch-demo/0.1 (CC0 research)"},
            )
            with urlopen(request, timeout=40) as response:
                path.write_bytes(response.read())
        with Image.open(path) as image:
            image.verify()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, selected))
    previous = (
        json.loads((CANDIDATES / "sources.json").read_text())
        if (CANDIDATES / "sources.json").exists()
        else []
    )
    merged = {r["id"]: r for r in previous + selected}
    (CANDIDATES / "sources.json").write_text(json.dumps(list(merged.values()), indent=2))
    for start in range(0, len(selected), 24):
        batch = selected[start : start + 24]
        sheet = Image.new("RGB", (1200, 290 * ((len(batch) + 5) // 6)), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        for index, record in enumerate(batch):
            with Image.open(CANDIDATES / f"{record['id']}.jpg") as image:
                image = image.convert("RGB")
                image.thumbnail((188, 230))
                x, y = (index % 6) * 200, (index // 6) * 290
                sheet.paste(image, (x + (200 - image.width) // 2, y))
                draw.text((x + 5, y + 235), str(record["id"]), fill="black")
                draw.text((x + 5, y + 251), record["title"][:26], fill="black")
        sheet.save(CANDIDATES / f"sheet-{start // 24}.jpg")
    print(f"Downloaded {len(selected)} CC0 candidates for visual selection")


def publish_selection() -> None:
    selection = json.loads((ROOT / "data/pitch/selection.json").read_text())
    sources = {r["id"]: r for r in json.loads((CANDIDATES / "sources.json").read_text())}
    photo_dir = ROOT / "data/pitch/images"
    photo_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for chosen in selection:
        source = sources[chosen["source_id"]]
        assert source["share_license_status"] == "CC0"
        item_id = f"pitch-{source['id']}"
        path = photo_dir / f"{item_id}.jpg"
        shutil.copyfile(CANDIDATES / f"{source['id']}.jpg", path)
        records.append(
            {
                **chosen,
                "item_id": item_id,
                "store_id": "pitch-demo",
                "demo": True,
                "image_uri": f"/images/{item_id}.jpg",
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "price_kind": "illustrative_demo" if chosen["price"] is not None else "unknown",
                "source_title": source["title"],
                "source_url": source["url"],
                "image_source_url": source["images"]["web"]["url"],
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "credit": "The Cleveland Museum of Art",
                "accession_number": source["accession_number"],
                "materials": source["technique"],
                "measurements": source.get("measurements"),
                "photo_captured_at": None,
                "source_reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    document = {
        "dataset_kind": "pitch_demo",
        "not_customer_zero_inventory": True,
        "store_id": "pitch-demo",
        "currency": "USD",
        "items": records,
    }
    (ROOT / "data/pitch/catalog.json").write_text(json.dumps(document, indent=2) + "\n")
    print(f"Published {len(records)} manually selected documentary photos; demo prices only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.publish:
        publish_selection()
    elif args.source:
        candidates(args.source)
    else:
        parser.error("provide --source or --publish")
