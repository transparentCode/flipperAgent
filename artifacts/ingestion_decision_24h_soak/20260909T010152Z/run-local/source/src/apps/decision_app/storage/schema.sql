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
