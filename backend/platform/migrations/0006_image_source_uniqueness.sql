-- S7 concurrency hardening: one store cannot represent the same source bytes twice
-- for the same variant. Store-scoped on purpose (another store may publish the same
-- photo), and variant-scoped so one source image may back different future variants.

CREATE UNIQUE INDEX IF NOT EXISTS images_store_source_idx
    ON images (store_id, source_sha256, variant);
