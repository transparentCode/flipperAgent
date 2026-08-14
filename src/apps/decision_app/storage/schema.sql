CREATE SCHEMA IF NOT EXISTS decision;

CREATE TABLE IF NOT EXISTS decision.state_checkpoints (
    checkpoint_schema_version integer NOT NULL,
    lane_id text NOT NULL,
    effective_lane_revision text NOT NULL,
    feature_plan_fingerprint text NOT NULL,
    data_plan_fingerprint text NOT NULL,
    market_as_of timestamptz NOT NULL,
    state_inception_at timestamptz NOT NULL,
    state_payload text NOT NULL,
    state_payload_sha256 text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (
        lane_id,
        effective_lane_revision,
        feature_plan_fingerprint,
        data_plan_fingerprint
    )
);
