-- SR v2 owns one latest semantic state row per lane/config identity.
-- Applying this file is a caller/deployment responsibility; the runtime never
-- creates a pool, opens a connection, or bootstraps schema implicitly.

CREATE SCHEMA IF NOT EXISTS sr_v2;

CREATE TABLE IF NOT EXISTS sr_v2.checkpoints (
    venue TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    state_schema_version INTEGER NOT NULL,
    generation BIGINT NOT NULL CHECK (generation > 0),
    cutoff TIMESTAMPTZ NOT NULL,
    state_checksum CHAR(64) NOT NULL,
    state_payload BYTEA NOT NULL,
    PRIMARY KEY (venue, instrument_id, asset, config_fingerprint),
    CHECK (length(state_checksum) = 64),
    CHECK (octet_length(state_payload) > 0),
    CONSTRAINT state_payload_size_check
        CHECK (octet_length(state_payload) <= 16 * 1024 * 1024)
);

-- ``CREATE TABLE IF NOT EXISTS`` does not amend a table created by an earlier
-- schema version.  Keep the payload bound present and bootstrap idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'sr_v2.checkpoints'::regclass
           AND conname = 'state_payload_size_check'
    ) THEN
        ALTER TABLE sr_v2.checkpoints
            ADD CONSTRAINT state_payload_size_check
            CHECK (octet_length(state_payload) <= 16 * 1024 * 1024);
    END IF;
END
$$;
