-- S3 mutable catalog and durable media metadata.
-- Store-scoped composite keys so a child row cannot reference another store's
-- parent (ADR-0005 §2). Forward-only and re-runnable; the runner records the version.
--
-- The S2 `stores.catalog_path` column is intentionally left in place: SQLite has no
-- idempotent DROP COLUMN, and S3 no longer reads or writes it.

CREATE TABLE IF NOT EXISTS items (
    store_id TEXT NOT NULL REFERENCES stores (store_id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    price TEXT,
    price_kind TEXT NOT NULL CHECK (price_kind IN ('unknown', 'known', 'illustrative_demo')),
    listing_state TEXT NOT NULL CHECK (
        listing_state IN ('draft', 'published', 'hidden', 'sold')
    ),
    index_state TEXT NOT NULL DEFAULT 'pending' CHECK (
        index_state IN ('pending', 'ready', 'failed', 'stale')
    ),
    index_attempts INTEGER NOT NULL DEFAULT 0,
    index_error TEXT,
    sort_order INTEGER NOT NULL,
    attributes_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    catalog_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (store_id, item_id)
);

CREATE TABLE IF NOT EXISTS images (
    store_id TEXT NOT NULL,
    image_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    byte_size INTEGER NOT NULL,
    capture_time TEXT,
    capture_time_source TEXT NOT NULL CHECK (
        capture_time_source IN ('unknown', 'exif', 'merchant_attestation')
    ),
    created_at TEXT NOT NULL,
    PRIMARY KEY (store_id, image_id),
    UNIQUE (store_id, item_id, variant),
    FOREIGN KEY (store_id, item_id) REFERENCES items (store_id, item_id) ON DELETE RESTRICT,
    CHECK (
        (capture_time_source = 'unknown' AND capture_time IS NULL)
        OR (capture_time_source <> 'unknown' AND capture_time IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS images_store_sha_idx ON images (store_id, sha256, variant);

CREATE TABLE IF NOT EXISTS item_events (
    store_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT NOT NULL,
    PRIMARY KEY (store_id, event_id),
    FOREIGN KEY (store_id, item_id) REFERENCES items (store_id, item_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS item_events_item_idx
    ON item_events (store_id, item_id, occurred_at);
