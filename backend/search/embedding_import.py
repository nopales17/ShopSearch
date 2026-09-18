"""Import the committed demo vectors into per-item embedding rows (S4).

The committed index file is an import/compatibility source after S4: its vectors
are written unchanged (little-endian float32) and bound to each item's current
stored image, so ranking stays identical while the runtime reads the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.catalog.store_repository import CatalogRepository
from backend.search.vector_source import EMBEDDING_DIMENSIONS, CommittedIndexVectorSource
from contracts.store import Store


@dataclass(frozen=True)
class EmbeddingImportResult:
    store_id: str
    embeddings_created: int
    embeddings_unchanged: int
    published_without_vectors: int


def import_pitch_embeddings(
    repository: CatalogRepository,
    index_path: Path,
    store: Store,
    *,
    model_id: str,
    model_revision: str,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> EmbeddingImportResult:
    """Import committed vectors idempotently, bound to each item's stored image."""

    scope = store.scope
    source = CommittedIndexVectorSource(
        index_path,
        expected_catalog_version=repository.catalog_version(scope),
        expected_model_id=model_id,
        expected_model_revision=model_revision,
        dimensions=dimensions,
    )
    vectors = source.current().vectors
    created = unchanged = missing = 0
    for item in repository.published(scope):
        image = repository.display_image(scope, item.item_id)
        vector = vectors.get(item.item_id)
        reviewed_sha = item.attributes.get("image_sha256")
        if (
            image is None
            or vector is None
            or not isinstance(reviewed_sha, str)
            or image.source_sha256 != reviewed_sha
        ):
            # No reviewed-vector binding for this item: leave it to the indexer
            # rather than binding a committed vector to a changed image.
            missing += 1
            continue
        if repository.put_ready_embedding(
            scope,
            item_id=item.item_id,
            vector=vector,
            model_id=model_id,
            model_revision=model_revision,
            image_sha256=image.sha256,
        ):
            created += 1
        else:
            unchanged += 1
    return EmbeddingImportResult(scope.store_id, created, unchanged, missing)
