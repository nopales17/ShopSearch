-- S6 founder-provisioned merchant accounts and store-scoped sessions.
-- Passwords are PBKDF2-HMAC-SHA256 (salt + iterations stored per account); session
-- tokens are stored only as SHA-256 hex digests. Composite keys keep every row and
-- every session lookup inside one store.

CREATE TABLE IF NOT EXISTS merchants (
    store_id TEXT NOT NULL REFERENCES stores (store_id) ON DELETE RESTRICT,
    merchant_id TEXT NOT NULL,
    username TEXT NOT NULL,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    password_iterations INTEGER NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (store_id, merchant_id),
    UNIQUE (store_id, username)
);

CREATE TABLE IF NOT EXISTS merchant_sessions (
    store_id TEXT NOT NULL,
    token_sha256 TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (store_id, token_sha256),
    FOREIGN KEY (store_id, merchant_id)
        REFERENCES merchants (store_id, merchant_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS merchant_sessions_merchant_idx
    ON merchant_sessions (store_id, merchant_id);
