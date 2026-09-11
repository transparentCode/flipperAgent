CREATE TABLE IF NOT EXISTS alert_incidents (
    incident_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    source_app TEXT NOT NULL,
    source_component TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    asset TEXT,
    timeframe TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurrence_count BIGINT NOT NULL DEFAULT 1,
    route_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at DOUBLE PRECISION NOT NULL,
    last_seen_at DOUBLE PRECISION NOT NULL,
    last_notified_at DOUBLE PRECISION,
    acknowledged_at DOUBLE PRECISION,
    resolved_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_incidents_state_updated_at
    ON alert_incidents (state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_incidents_source_app
    ON alert_incidents (source_app, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_incidents_asset_timeframe
    ON alert_incidents (asset, timeframe, updated_at DESC);

CREATE TABLE IF NOT EXISTS alert_notifications (
    delivery_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES alert_incidents (incident_id) ON DELETE CASCADE,
    route_name TEXT NOT NULL,
    transport TEXT NOT NULL,
    status TEXT NOT NULL,
    destination TEXT NOT NULL,
    error TEXT,
    attempted_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_notifications_incident_attempted_at
    ON alert_notifications (incident_id, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_notifications_status
    ON alert_notifications (status, attempted_at DESC);

CREATE TABLE IF NOT EXISTS alert_silences (
    silence_id TEXT PRIMARY KEY,
    match JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    created_by TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_alert_silences_expires_at
    ON alert_silences (expires_at);

