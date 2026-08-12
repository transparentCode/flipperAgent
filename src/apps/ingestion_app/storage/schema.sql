CREATE SCHEMA IF NOT EXISTS ingestion;

CREATE TABLE IF NOT EXISTS ingestion.candles (
    venue TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,

    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,

    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    taker_buy_base NUMERIC,

    source_type TEXT NOT NULL,
    source_provider TEXT,
    source_timeframe TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT candles_identity_non_blank CHECK (
        btrim(venue) <> ''
        AND btrim(instrument_id) <> ''
        AND btrim(timeframe) <> ''
    ),
    CONSTRAINT candles_close_after_open CHECK (close_time > open_time),
    CONSTRAINT candles_low_not_above_high CHECK (low <= high),
    CONSTRAINT candles_open_within_range CHECK (low <= open AND open <= high),
    CONSTRAINT candles_close_within_range CHECK (low <= close AND close <= high),
    CONSTRAINT candles_volume_non_negative CHECK (volume >= 0),
    CONSTRAINT candles_taker_buy_base_non_negative CHECK (
        taker_buy_base IS NULL OR taker_buy_base >= 0
    ),
    CONSTRAINT candles_source_type_valid CHECK (
        source_type IN ('provider', 'derived')
    ),
    CONSTRAINT candles_source_provenance_valid CHECK (
        (
            source_type = 'provider'
            AND source_provider IS NOT NULL
            AND btrim(source_provider) <> ''
            AND source_timeframe IS NULL
        )
        OR (
            source_type = 'derived'
            AND source_provider IS NULL
            AND source_timeframe IS NOT NULL
            AND btrim(source_timeframe) <> ''
        )
    ),

    PRIMARY KEY (venue, instrument_id, timeframe, open_time)
);

SELECT create_hypertable(
    'ingestion.candles',
    'open_time',
    if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS ingestion.outbox (
    event_id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    schema_version SMALLINT NOT NULL,
    producer TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT outbox_event_type_non_blank CHECK (btrim(event_type) <> ''),
    CONSTRAINT outbox_schema_version_positive CHECK (schema_version > 0),
    CONSTRAINT outbox_producer_non_blank CHECK (btrim(producer) <> '')
);

CREATE INDEX IF NOT EXISTS ingestion_outbox_pending_idx
    ON ingestion.outbox (occurred_at, event_id)
    WHERE published_at IS NULL;

CREATE INDEX IF NOT EXISTS ingestion_outbox_published_idx
    ON ingestion.outbox (published_at, event_id)
    WHERE published_at IS NOT NULL;
