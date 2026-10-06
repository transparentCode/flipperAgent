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

CREATE TABLE IF NOT EXISTS decision.shadow_progress (
    progress_schema_version integer NOT NULL,
    lane_id text NOT NULL,
    effective_lane_revision text NOT NULL,
    feature_plan_fingerprint text NOT NULL,
    data_plan_fingerprint text NOT NULL,
    market_as_of timestamptz NOT NULL,
    last_disposition text NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (
        lane_id,
        effective_lane_revision,
        feature_plan_fingerprint,
        data_plan_fingerprint
    ),
    CHECK (
        last_disposition IS NULL
        OR last_disposition IN ('shadow', 'published', 'no_signal')
    )
);

-- Upgrade the already-certified C4B table in place.  CREATE TABLE IF NOT
-- EXISTS does not alter a constraint on an existing relation.
DO $$
DECLARE
    constraint_definition text;
    check_constraint_count integer;
BEGIN
    SELECT count(*)
      INTO check_constraint_count
      FROM pg_constraint AS constraint_row
      JOIN pg_class AS relation_row
        ON relation_row.oid = constraint_row.conrelid
      JOIN pg_namespace AS namespace_row
        ON namespace_row.oid = relation_row.relnamespace
     WHERE namespace_row.nspname = 'decision'
       AND relation_row.relname = 'shadow_progress'
       AND constraint_row.contype = 'c';

    IF check_constraint_count <> 1 THEN
        RAISE EXCEPTION
            'decision.shadow_progress must have exactly one CHECK constraint, found %',
            check_constraint_count;
    END IF;

    SELECT pg_get_constraintdef(constraint_row.oid)
      INTO constraint_definition
      FROM pg_constraint AS constraint_row
      JOIN pg_class AS relation_row
        ON relation_row.oid = constraint_row.conrelid
      JOIN pg_namespace AS namespace_row
        ON namespace_row.oid = relation_row.relnamespace
     WHERE namespace_row.nspname = 'decision'
       AND relation_row.relname = 'shadow_progress'
       AND constraint_row.conname = 'shadow_progress_last_disposition_check'
       AND constraint_row.contype = 'c';

    IF constraint_definition IS NULL THEN
        RAISE EXCEPTION
            'known decision.shadow_progress disposition constraint is missing';
    END IF;

    IF constraint_definition ILIKE '%published%'
       AND constraint_definition ILIKE '%no_signal%'
       AND constraint_definition ILIKE '%last_disposition%' THEN
        RETURN;
    END IF;

    IF constraint_definition ILIKE '%last_disposition IS NULL%'
       AND constraint_definition ILIKE '%last_disposition = ''shadow''%'
       AND constraint_definition NOT ILIKE '%published%'
       AND constraint_definition NOT ILIKE '%no_signal%' THEN
        ALTER TABLE decision.shadow_progress
            DROP CONSTRAINT shadow_progress_last_disposition_check;
        ALTER TABLE decision.shadow_progress
            ADD CONSTRAINT shadow_progress_last_disposition_check
            CHECK (
                last_disposition IS NULL
                OR last_disposition IN ('shadow', 'published', 'no_signal')
            );
        RETURN;
    END IF;

    RAISE EXCEPTION
        'unsupported decision.shadow_progress disposition constraint: %',
        constraint_definition;
END
$$;

CREATE TABLE IF NOT EXISTS decision.lane_effect_skips (
    lane_id text NOT NULL,
    effective_lane_revision text NOT NULL,
    feature_plan_fingerprint text NOT NULL,
    skipped_from timestamptz NOT NULL,
    skipped_through timestamptz NOT NULL,
    cutoff_count integer NOT NULL CHECK (cutoff_count > 0),
    reason text NOT NULL CONSTRAINT lane_effect_skips_reason_check CHECK (
        reason IN ('restart', 'restart_rewarm', 'stale', 'foreign_entry', 'lane_fault')
    ),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        lane_id,
        effective_lane_revision,
        feature_plan_fingerprint,
        skipped_from
    ),
    CHECK (skipped_through >= skipped_from)
);

-- Upgrade an existing lane_effect_skips table to admit the lane_fault reason.
-- CREATE TABLE IF NOT EXISTS does not alter a constraint on an existing
-- relation.  This table carries three CHECK constraints, so the reason
-- constraint is addressed by name rather than counted.
DO $$
DECLARE
    constraint_definition text;
BEGIN
    SELECT pg_get_constraintdef(constraint_row.oid)
      INTO constraint_definition
      FROM pg_constraint AS constraint_row
      JOIN pg_class AS relation_row
        ON relation_row.oid = constraint_row.conrelid
      JOIN pg_namespace AS namespace_row
        ON namespace_row.oid = relation_row.relnamespace
     WHERE namespace_row.nspname = 'decision'
       AND relation_row.relname = 'lane_effect_skips'
       AND constraint_row.conname = 'lane_effect_skips_reason_check'
       AND constraint_row.contype = 'c';

    IF constraint_definition IS NULL THEN
        RAISE EXCEPTION
            'known decision.lane_effect_skips reason constraint is missing';
    END IF;

    IF constraint_definition ILIKE '%lane_fault%' THEN
        RETURN;
    END IF;

    IF constraint_definition ILIKE '%foreign_entry%'
       AND constraint_definition NOT ILIKE '%lane_fault%' THEN
        ALTER TABLE decision.lane_effect_skips
            DROP CONSTRAINT lane_effect_skips_reason_check;
        ALTER TABLE decision.lane_effect_skips
            ADD CONSTRAINT lane_effect_skips_reason_check
            CHECK (
                reason IN (
                    'restart', 'restart_rewarm', 'stale', 'foreign_entry', 'lane_fault'
                )
            );
        RETURN;
    END IF;

    RAISE EXCEPTION
        'unsupported decision.lane_effect_skips reason constraint: %',
        constraint_definition;
END
$$;
