-- S2 store registry: stores and hostname-to-store domains.
-- Forward-only and re-runnable; the runner records the applied version.

CREATE TABLE IF NOT EXISTS stores (
    store_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    timezone TEXT NOT NULL,
    is_demo INTEGER NOT NULL CHECK (is_demo IN (0, 1)),
    catalog_path TEXT,
    presentation_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store_domains (
    hostname TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores (store_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS store_domains_store_id_idx ON store_domains (store_id);
