from __future__ import annotations

import asyncio
import copy
import os
import shutil
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import valkey.asyncio as valkey
import yaml

from apps.ingestion_app.bootstrap import create_application
from apps.ingestion_app.runtime.supervisor import RuntimeState
from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from tests.ingestion._asgi import request

if os.getenv("INGESTION_RUN_APPLICATION_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_APPLICATION_INTEGRATION=1 to run the full ingestion application test",
        allow_module_level=True,
    )


def _dsn() -> str:
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )


def _valkey_uri() -> str:
    return os.getenv("VALKEY_URI", "redis://localhost:6380/0")


def _prepare_config(
    *,
    repository_root: Path,
    config_root: Path,
    instrument_id: str,
) -> None:
    shutil.copytree(
        repository_root / "configs" / "ingestion",
        config_root / "ingestion",
    )
    asset_path = config_root / "ingestion" / "assets" / "BTC.yaml"
    asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
    instrument = copy.deepcopy(asset["instruments"].pop("BTC-USDT-PERP"))
    instrument["timeframes"] = ["1m"]
    asset["instruments"] = {instrument_id: instrument}
    asset_path.write_text(
        yaml.safe_dump(asset, sort_keys=False),
        encoding="utf-8",
    )


async def _counts(pool: asyncpg.Pool, instrument_id: str) -> tuple[int, int]:
    async with pool.acquire() as connection:
        candle_count = await connection.fetchval(
            "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
            instrument_id,
        )
        pending_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
              AND published_at IS NULL
            """,
            instrument_id,
        )
    return int(candle_count), int(pending_count)


async def _event_ids(pool: asyncpg.Pool, instrument_id: str) -> set[str]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT event_id
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
              AND published_at IS NOT NULL
            ORDER BY occurred_at ASC, event_id ASC
            """,
            instrument_id,
        )
    return {str(row["event_id"]) for row in rows}


async def _published_candle_evidence(
    pool: asyncpg.Pool,
    instrument_id: str,
) -> tuple[int, dict[str, str] | None]:
    async with pool.acquire() as connection:
        outbox_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
              AND published_at IS NOT NULL
            """,
            instrument_id,
        )
        row = await connection.fetchrow(
            """
            SELECT source_type, source_provider
            FROM ingestion.candles
            WHERE instrument_id = $1
            ORDER BY open_time DESC
            LIMIT 1
            """,
            instrument_id,
        )
    return int(outbox_count), None if row is None else dict(row)


async def _cleanup_database(instrument_id: str) -> None:
    pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
                instrument_id,
            )
            await connection.execute(
                "DELETE FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
                    instrument_id,
                )
                == 0
            )
            assert (
                await connection.fetchval(
                    """
                SELECT COUNT(*)
                FROM ingestion.outbox
                WHERE payload->>'instrument_id' = $1
                """,
                    instrument_id,
                )
                == 0
            )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_full_application_composition_live_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).parents[3]
    instrument_id = f"package_k_{uuid4().hex}"
    stream_key = f"stream:ohlcv:ingestion:binance:{instrument_id}:1m"
    config_root = tmp_path / "configs"
    _prepare_config(
        repository_root=repository_root,
        config_root=config_root,
        instrument_id=instrument_id,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POSTGRES_URI", _dsn())
    monkeypatch.setenv("VALKEY_URI", _valkey_uri())

    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(config_root))
    observer = valkey.Valkey.from_url(_valkey_uri(), decode_responses=True)
    controller = None
    publisher_task: asyncio.Task[None] | None = None

    try:
        await observer.ping()
        app = create_application(config_manager=manager)
        async with app.router.lifespan_context(app):
            controller = app.state.runtime_controller
            publisher_task = app.state.publisher_task
            assert controller.is_started is True
            assert (await request(app, "GET", "/health/live")).status_code == 200
            assert (await request(app, "GET", "/health/ready")).status_code == 200
            assert (await request(app, "GET", "/runtime")).status_code == 200
            assets_response = await request(app, "GET", "/assets")
            assert assets_response.status_code == 200
            assert assets_response.body["assets"][0]["asset"] == "BTC"

            pool = DBPoolManager.get_writer_pool()
            live_observed = False
            async with asyncio.timeout(180):
                while True:
                    snapshot = controller.snapshot()
                    live_observed |= snapshot.state is RuntimeState.LIVE
                    if snapshot.state is RuntimeState.ERROR:
                        pytest.fail(f"runtime entered ERROR: {snapshot.last_error}")
                    candle_count, pending_count = await _counts(pool, instrument_id)
                    stream_entries = await observer.xrange(stream_key, "-", "+")
                    if (
                        live_observed
                        and candle_count > 0
                        and pending_count == 0
                        and stream_entries
                    ):
                        break
                    await asyncio.sleep(0.5)

            assert live_observed is True
            assert controller.snapshot().state is RuntimeState.LIVE
            assert publisher_task.done() is False
            published_count, candle_provenance = await _published_candle_evidence(
                pool,
                instrument_id,
            )
            assert published_count > 0
            assert candle_provenance == {
                "source_type": "provider",
                "source_provider": "binance_native",
            }
            durable_event_ids = await _event_ids(pool, instrument_id)
            assert durable_event_ids
            stream_entries = await observer.xrange(stream_key, "-", "+")
            published_event_ids = {fields["event_id"] for _, fields in stream_entries}
            assert durable_event_ids & published_event_ids

        assert controller.is_started is False
        assert publisher_task.done() is True
    finally:
        await observer.delete(stream_key)
        assert await observer.exists(stream_key) == 0
        await observer.aclose()
        if controller is not None and controller.is_started:
            await controller.close()
        await _cleanup_database(instrument_id)
        ConfigManager.reset_singleton()
