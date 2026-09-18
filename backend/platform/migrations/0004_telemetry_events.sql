-- S5 store-scoped append-only telemetry. The event contract lives in the payload
-- snapshot; columns carry the store/search/time context the contract requires.

CREATE TABLE IF NOT EXISTS telemetry_events (
    store_id TEXT NOT NULL REFERENCES stores (store_id) ON DELETE RESTRICT,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    search_id TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (store_id, event_id)
);

CREATE INDEX IF NOT EXISTS telemetry_events_search_idx
    ON telemetry_events (store_id, search_id);

CREATE INDEX IF NOT EXISTS telemetry_events_time_idx
    ON telemetry_events (store_id, occurred_at);
