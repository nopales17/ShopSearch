"""Local, pinned off-the-shelf CLIP encoder. No catalog truth lives here."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

MODEL_ID = "openai/clip-vit-base-patch32"
MODEL_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "data/local/clip-vit-base-patch32"


class ClipEncoder:
    def __init__(self, path: Path = MODEL_PATH) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        torch.set_num_threads(4)
        self._torch = torch
        self._lock = Lock()
        self.processor = CLIPProcessor.from_pretrained(str(path), local_files_only=True)
        self.model = CLIPModel.from_pretrained(str(path), local_files_only=True).eval()

    @lru_cache(maxsize=128)
    def text(self, text: str) -> tuple[float, ...]:
        with self._lock, self._torch.inference_mode():
            inputs = self.processor(
                text=[text], return_tensors="pt", padding=True, truncation=True, max_length=77
            )
            vector = self.model.get_text_features(**inputs)
            vector = vector / vector.norm(dim=-1, keepdim=True)
            return tuple(vector[0].tolist())

    def images(self, images: list[Any]) -> list[list[float]]:
        with self._lock, self._torch.inference_mode():
            inputs = self.processor(images=images, return_tensors="pt")
            vectors = self.model.get_image_features(**inputs)
            vectors = vectors / vectors.norm(dim=-1, keepdim=True)
            return vectors.tolist()


def download_model() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(MODEL_PATH),
        allow_patterns=["*.json", "merges.txt", "vocab.json", "pytorch_model.bin", "README.md"],
        max_workers=2,
    )


if __name__ == "__main__":
    download_model()
