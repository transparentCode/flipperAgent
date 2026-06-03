"""Trial persistence in TimescaleDB for optimization results."""

from __future__ import annotations

import time
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import TrialResult

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# SQL for creating the optimization_trials table (run once during DB migration).
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS optimization_trials (
    id              BIGSERIAL PRIMARY KEY,
    study_name      TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    asset           TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    trial_number    INT NOT NULL,
    params          JSONB NOT NULL,
    objective_values JSONB NOT NULL,
    state           TEXT NOT NULL,
    duration_s      FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (study_name, trial_number)
);
"""

INSERT_TRIAL_SQL = """
INSERT INTO optimization_trials
    (study_name, model_name, asset, timeframe, trial_number, params, objective_values, state, duration_s)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
ON CONFLICT (study_name, trial_number) DO UPDATE SET
    params = EXCLUDED.params,
    objective_values = EXCLUDED.objective_values,
    state = EXCLUDED.state,
    duration_s = EXCLUDED.duration_s;
"""

QUERY_BEST_TRIALS_SQL = """
SELECT study_name, trial_number, params, objective_values, state, duration_s, created_at
FROM optimization_trials
WHERE study_name = $1 AND state = 'COMPLETE'
ORDER BY (objective_values->>$2)::float DESC
LIMIT $3;
"""


class TrialStore:
    """Async persistence layer for Optuna trial results in TimescaleDB."""

    def __init__(self, pool: Any) -> None:
        """*pool* is an asyncpg connection pool."""
        self.pool = pool

    async def ensure_table(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            logger.info("optimization_trials table ensured.")

    async def save_trial(
        self,
        model_name: str,
        asset: str,
        timeframe: str,
        result: TrialResult,
    ) -> None:
        import json
        async with self.pool.acquire() as conn:
            await conn.execute(
                INSERT_TRIAL_SQL,
                result.study_name,
                model_name,
                asset,
                timeframe,
                result.trial_number,
                json.dumps(result.params),
                json.dumps(result.values),
                result.state,
                result.duration_seconds,
            )

    async def query_best(
        self,
        study_name: str,
        objective_key: str = "sharpe",
        limit: int = 5,
        direction: str = "maximize",
    ) -> list[dict[str, Any]]:
        order = "DESC" if direction.lower() != "minimize" else "ASC"
        query = QUERY_BEST_TRIALS_SQL.replace("DESC", order)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, study_name, objective_key, limit)
            return [dict(r) for r in rows]
