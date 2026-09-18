"""Single-purpose embedding indexer with bounded retries and backoff.

ADR-0005 §5 asks for one small component that maintains `index_state`, never a
generic job framework. It only writes embeddings and index-state fields: listing
state is never touched, so publication never depends on indexing.

    python -m backend.search.indexer --store-id pitch-demo [--reset-failed]
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from PIL import Image

from backend.catalog.store_repository import CatalogRepository, IndexSummary
from backend.media.image_store import ImageStore, LocalImageStore
from backend.platform.paths import DEFAULT_DATABASE_PATH, DEFAULT_MEDIA_ROOT
from backend.search.vector_source import EMBEDDING_DIMENSIONS
from contracts.catalog import IndexState
from contracts.store import StoreScope

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_MAX_BACKOFF_SECONDS = 8.0
DEFAULT_BATCH_LIMIT = 100


class IndexingError(ValueError):
    """Raised when one item cannot be indexed from its stored image."""


class ImageEncoder(Protocol):
    def images(self, images: list[Any]) -> list[list[float]]: ...


@dataclass(frozen=True)
class IndexerConfig:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS
    batch_limit: int = DEFAULT_BATCH_LIMIT


@dataclass(frozen=True)
class IndexRunReport:
    store_id: str
    candidates: int
    attempted: int
    ready: int
    failed: int
    summary: IndexSummary


class EmbeddingIndexer:
    """Indexes published items that lack a valid, ready embedding."""

    def __init__(
        self,
        repository: CatalogRepository,
        image_store: ImageStore,
        encoder: ImageEncoder,
        *,
        model_id: str,
        model_revision: str,
        config: IndexerConfig | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._repository = repository
        self._image_store = image_store
        self._encoder = encoder
        self._model_id = model_id
        self._model_revision = model_revision
        self._dimensions = dimensions
        self._config = config or IndexerConfig()
        self._sleep = sleep

    def run(self, scope: StoreScope) -> IndexRunReport:
        candidates = self._repository.index_candidates(
            scope,
            model_id=self._model_id,
            model_revision=self._model_revision,
            dimensions=self._dimensions,
            max_attempts=self._config.max_attempts,
            limit=self._config.batch_limit,
        )
        attempted = ready = failed = 0
        for candidate in candidates:
            # A stale binding means the input changed, so its retry budget is fresh.
            attempts = 0 if candidate.state is IndexState.STALE else candidate.attempts
            if attempts >= self._config.max_attempts:
                continue
            attempted += 1
            for attempt in range(attempts + 1, self._config.max_attempts + 1):
                try:
                    vector, image_sha256 = self._encode(scope, candidate.item_id)
                except Exception as error:  # Any indexing failure is recorded, never raised on.
                    self._repository.mark_index_failed(
                        scope,
                        item_id=candidate.item_id,
                        attempts=attempt,
                        error=f"{type(error).__name__}: {error}",
                    )
                    if attempt >= self._config.max_attempts:
                        failed += 1
                        break
                    self._sleep(self._backoff(attempt))
                    continue
                self._repository.put_ready_embedding(
                    scope,
                    item_id=candidate.item_id,
                    vector=vector,
                    model_id=self._model_id,
                    model_revision=self._model_revision,
                    image_sha256=image_sha256,
                )
                ready += 1
                break
        return IndexRunReport(
            store_id=scope.store_id,
            candidates=len(candidates),
            attempted=attempted,
            ready=ready,
            failed=failed,
            summary=self._repository.index_summary(
                scope,
                model_id=self._model_id,
                model_revision=self._model_revision,
                dimensions=self._dimensions,
            ),
        )

    def _encode(self, scope: StoreScope, item_id: str) -> tuple[tuple[float, ...], str]:
        image = self._repository.display_image(scope, item_id)
        if image is None:
            raise IndexingError(f"item {item_id} has no stored display image")
        data = self._image_store.read(scope, image.sha256, image.variant)
        try:
            with Image.open(BytesIO(data)) as opened:
                rgb = opened.convert("RGB")
        except OSError as error:
            raise IndexingError(f"could not decode the stored image for {item_id}") from error
        try:
            encoded = self._encoder.images([rgb])
        finally:
            rgb.close()
        if len(encoded) != 1 or len(encoded[0]) != self._dimensions:
            raise IndexingError("encoder returned an unexpected embedding shape")
        return tuple(float(value) for value in encoded[0]), image.sha256

    def _backoff(self, attempt: int) -> float:
        return min(
            self._config.backoff_seconds * float(2 ** (attempt - 1)),
            self._config.max_backoff_seconds,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.search.indexer",
        description="Index published items that lack a valid embedding.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--backoff-seconds", type=float, default=DEFAULT_BACKOFF_SECONDS)
    parser.add_argument("--max-backoff-seconds", type=float, default=DEFAULT_MAX_BACKOFF_SECONDS)
    parser.add_argument("--batch-limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument(
        "--reset-failed",
        action="store_true",
        help="return items that hit the attempt cap to pending before indexing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ClipEncoder
    from backend.stores.repository import StoreRepository

    with StoreRepository.open(arguments.database) as stores:
        store = stores.get_store(StoreScope(arguments.store_id))
        with CatalogRepository.open(arguments.database) as catalog:
            if arguments.reset_failed:
                reset = catalog.reset_index_failures(store.scope)
                print(f"reset {reset} failed items to pending")
            indexer = EmbeddingIndexer(
                catalog,
                LocalImageStore(arguments.media_root),
                ClipEncoder(),
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
                config=IndexerConfig(
                    max_attempts=arguments.max_attempts,
                    backoff_seconds=arguments.backoff_seconds,
                    max_backoff_seconds=arguments.max_backoff_seconds,
                    batch_limit=arguments.batch_limit,
                ),
            )
            report = indexer.run(store.scope)
    print(
        f"indexed {report.store_id}: {report.ready} ready, {report.failed} failed; "
        f"published={report.summary.published} ready={report.summary.ready} "
        f"pending={report.summary.pending} failed={report.summary.failed} "
        f"stale={report.summary.stale}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
