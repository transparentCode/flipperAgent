-- Append-only store for the v2 collector. Applied by
-- ``python -m apps.scraper_app.storage.bootstrap`` (operator step); the runtime
-- role ``scraper_app`` can only SELECT and INSERT.

CREATE SCHEMA IF NOT EXISTS scraper;

CREATE TABLE IF NOT EXISTS scraper.reads (
    read_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_id     text        NOT NULL,
    trigger        text        NOT NULL CHECK (trigger IN ('schedule', 'catchup', 'late_bar', 'job')),   -- 'job' is reserved for phase 2
    status         text        NOT NULL CHECK (status IN ('ok', 'failed')),
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    provider_time  timestamptz NULL,
    covered_from   timestamptz NULL,
    covered_to     timestamptz NULL,
    bars_seen      integer     NOT NULL DEFAULT 0,
    bars_written   integer     NOT NULL DEFAULT 0,
    gap_before     boolean     NOT NULL DEFAULT false,
    holes          integer     NOT NULL DEFAULT 0,
    error_code     text        NULL,
    error_detail   text        NULL,
    CHECK ((status = 'ok') = (covered_from IS NOT NULL AND covered_to IS NOT NULL)),
    CHECK ((status = 'failed') = (error_code IS NOT NULL))
);
-- Databases created before ``holes`` existed keep their data.
ALTER TABLE scraper.reads ADD COLUMN IF NOT EXISTS holes integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS reads_dataset_finished
    ON scraper.reads (dataset_id, finished_at DESC);

CREATE TABLE IF NOT EXISTS scraper.bar_observations (
    dataset_id   text        NOT NULL,
    bar_open     timestamptz NOT NULL,
    seq          integer     NOT NULL CHECK (seq >= 1),
    bar_close    timestamptz NOT NULL,
    open         numeric     NOT NULL,
    high         numeric     NOT NULL,
    low          numeric     NOT NULL,
    close        numeric     NOT NULL,
    volume       numeric     NULL,
    content_hash text        NOT NULL,
    observed_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    read_id      bigint      NOT NULL REFERENCES scraper.reads (read_id),
    backfilled   boolean     NOT NULL,
    PRIMARY KEY (dataset_id, bar_open, seq),
    CHECK (bar_close > bar_open)
);

-- Analyse soon after a bulk load; readiness and reads must not depend on it,
-- but a first load of a few thousand bars should not wait for the default
-- 10 percent-of-table threshold.
ALTER TABLE scraper.bar_observations
    SET (autovacuum_analyze_scale_factor = 0, autovacuum_analyze_threshold = 2000);

-- CoinGlass lane: free-form per-read metadata and one whole payload per ok read.
ALTER TABLE scraper.reads ADD COLUMN IF NOT EXISTS meta jsonb NULL;

CREATE TABLE IF NOT EXISTS scraper.payload_observations (
    read_id       bigint      PRIMARY KEY REFERENCES scraper.reads (read_id),
    dataset_id    text        NOT NULL,
    observed_at   timestamptz NOT NULL,   -- the read's finished_at
    provider_time timestamptz NULL,
    format        text        NOT NULL,   -- 'json+gzip;v1'
    raw_bytes     integer     NOT NULL,
    content_hash  text        NOT NULL,
    payload       bytea       NOT NULL
);
CREATE INDEX IF NOT EXISTS payload_observations_dataset_time
    ON scraper.payload_observations (dataset_id, observed_at DESC);
ALTER TABLE scraper.payload_observations
    SET (autovacuum_analyze_scale_factor = 0, autovacuum_analyze_threshold = 2000);

-- Lets the purge role find the reads a bar still references without a scan.
CREATE INDEX IF NOT EXISTS bar_observations_read
    ON scraper.bar_observations (read_id);
