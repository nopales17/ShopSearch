-- S4 per-item embeddings and the two store generation counters (ADR-0005 §5).
-- Vectors are opaque little-endian float32 BLOBs with explicit dim/model binding,
-- valid only while (model_id, model_revision, image_sha256) match the item's current
-- stored image. Forward-only and re-runnable; the runner records the version.

CREATE TABLE IF NOT EXISTS store_generations (
    store_id TEXT PRIMARY KEY REFERENCES stores (store_id) ON DELETE RESTRICT,
    catalog_generation INTEGER NOT NULL DEFAULT 0,
    index_generation INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    store_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    dim INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (store_id, item_id),
    FOREIGN KEY (store_id, item_id) REFERENCES items (store_id, item_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS embeddings_binding_idx
    ON embeddings (store_id, model_id, model_revision, image_sha256);
