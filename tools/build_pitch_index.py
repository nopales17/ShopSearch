"""Precompute images once, preserving evaluation and catalog fingerprints."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from PIL import Image

from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ROOT, ClipEncoder
from backend.catalog.pitch import load_pitch_catalog


def main() -> None:
    start = time.perf_counter()
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
    encoder = ClipEncoder()
    vectors = []
    for start_index in range(0, len(catalog.items), 8):
        images = [
            Image.open(ROOT / "data/pitch/images" / f"{item.item_id}.jpg").convert("RGB")
            for item in catalog.items[start_index : start_index + 8]
        ]
        vectors.extend(encoder.images(images))
        for image in images:
            image.close()
    output = {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "catalog_version": catalog.version,
        "item_ids": [i.item_id for i in catalog.items],
        "vectors": vectors,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_sha256": hashlib.sha256(
            (ROOT / "experiments/search_v0/pitch_evaluation.json").read_bytes()
        ).hexdigest(),
        "build_seconds": time.perf_counter() - start,
    }
    (ROOT / "data/pitch/image_index.json").write_text(json.dumps(output) + "\n")
    print(f"Precomputed {len(vectors)} image embeddings in {output['build_seconds']:.2f}s")


if __name__ == "__main__":
    main()
