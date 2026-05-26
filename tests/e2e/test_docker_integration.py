import asyncio
import json
import os
import subprocess
import pytest
import asyncpg
import redis.asyncio as aioredis
from libs.common.db.pool_manager import DBPoolManager
from libs.common.config import ConfigManager

import pytest_asyncio

@pytest_asyncio.fixture(autouse=True)
async def db_pools():
    # Setup test-specific config values matching docker-compose defaults
    os.environ["POSTGRES_USER"] = "flipper"
    os.environ["POSTGRES_PASSWORD"] = "flipperpass"
    os.environ["POSTGRES_DB"] = "flipper_db"
    os.environ["POSTGRES_HOST"] = "localhost"
    os.environ["POSTGRES_PORT"] = "5432"
    
    # We patch the config manager to return the docker values
    class TestConfigManager(ConfigManager):
        def get(self, key_path: str, default: any = None) -> any:
            mapping = {
                "postgres.user": "flipper",
                "postgres.password": "flipperpass",
                "postgres.host": "localhost",
                "postgres.port": 5432,
                "postgres.database": "flipper_db",
                "postgres.pool.min_size": 1,
                "postgres.pool.max_size": 2,
            }
            return mapping.get(key_path, super().get(key_path, default))

    config_manager = TestConfigManager()
    await DBPoolManager.init_pools(config_manager=config_manager)
    yield
    await DBPoolManager.close_pools()


@pytest_asyncio.fixture
async def valkey_client():
    client = aioredis.from_url("redis://localhost:6380/0")
    yield client
    await client.aclose()

@pytest.mark.asyncio
async def test_timescaledb_initialization_and_gap_fill(db_pools):
    """
    Polls the TimescaleDB for ingestion of historical ticks, proving
    that the queue workers and gap-fill flows are operating properly.
    """
    pool = DBPoolManager.get_reader_pool()
    
    max_retries = 30
    delay_seconds = 2.0
    
    ticks_found = False
    
    print("Waiting for gap-fill routine to populate ohlcv...")
    for i in range(max_retries):
        async with pool.acquire() as conn:
            # Query the ohlcv table
            try:
                row = await conn.fetchrow('SELECT COUNT(*) as count FROM ohlcv;')
                count = row['count'] if row else 0
                if count > 0:
                    print(f"Gap-fill success! Found {count} rows.")
                    ticks_found = True
                    break
            except asyncpg.exceptions.UndefinedTableError:
                print("Table not defined yet...")
                
        print(f"No records found yet, retrying... ({i+1}/{max_retries})")
        await asyncio.sleep(delay_seconds)
        
    assert ticks_found, f"Timeout after {max_retries * delay_seconds}s waiting for records to be populated."

@pytest.mark.asyncio
async def test_websocket_live_streaming(db_pools):
    """
    Polls the TimescaleDB specifically for MAX(timestamp) on BTCUSDT using TimescaleReader.
    Proves gap-fill completes and WS live streaming brings us to within 5 mins of real-time.
    """
    import time
    from libs.common.db.timescale_reader import TimescaleReader
    
    pool = DBPoolManager.get_reader_pool()
    reader = TimescaleReader(pool)
    
    max_retries = 60
    delay_seconds = 2.0
    
    live_stream_active = False
    
    print("Waiting for gap-fill to complete and WS to begin pushing live ticks...")
    for i in range(max_retries):
        try:
            max_ts = await reader.get_max_timestamp("BTCUSDT", "1m")
            
            if max_ts > 0:
                now_ms = time.time() * 1000
                diff_ms = now_ms - max_ts
                
                if diff_ms <= 5 * 60 * 1000:
                    print(f"Live WS pipeline verified! Diff is {diff_ms} ms (<= 300,000). max_ts={max_ts}")
                    live_stream_active = True
                    break
                else:
                    print(f"Gap-fill running... lag is {diff_ms} ms. Retrying ({i+1}/{max_retries})")
            else:
                print(f"No ohlcv data yet... Retrying ({i+1}/{max_retries})")
        except asyncpg.exceptions.UndefinedTableError:
            print("Table/View not defined yet...")
            
        await asyncio.sleep(delay_seconds)
        
    assert live_stream_active, f"Timeout after {max_retries * delay_seconds}s waiting for live stream handoff."

@pytest.mark.asyncio
async def test_continuous_aggregates_exist(db_pools):
    """
    Verifies that the market_1m_bars continuous aggregate view is queried successfully.
    """
    pool = DBPoolManager.get_reader_pool()
    
    async with pool.acquire() as conn:
        # Just check if the table / materialized view exists and we can select from it
        try:
            row = await conn.fetchrow('SELECT COUNT(*) as count FROM market_1m_bars;')
            # We don't guarantee that the continuous aggregate has refreshed yet as it refreshes on a schedule, 
            # but we guarantee that the view exists.
            assert row is not None
        except asyncpg.exceptions.UndefinedTableError:
            pytest.fail("Continuous aggregate market_1m_bars does not exist.")


@pytest.mark.asyncio
async def test_signal_worker_consumes_and_produces(db_pools, valkey_client):
    """
    Verify signal_worker consumed from stream:ohlcv:btcusdt:1h and produced
    feature entries to features:BTCUSDT:1h.
    """
    stream_key = "stream:ohlcv:btcusdt:1h"
    features_key = "features:BTCUSDT:1h"
    max_retries = 60
    delay_seconds = 2.0

    # Check that signal_app_group consumer group exists on the OHLCV stream
    group_found = False
    for i in range(max_retries):
        try:
            groups = await valkey_client.xinfo_groups(stream_key)
            for g in groups:
                name = g.get("name") or g.get(b"name", b"")
                if isinstance(name, bytes):
                    name = name.decode()
                if name == "signal_app_group":
                    group_found = True
                    break
            if group_found:
                break
        except Exception:
            pass
        await asyncio.sleep(delay_seconds)

    assert group_found, (
        f"Timeout: signal_app_group not found on {stream_key} after {max_retries * delay_seconds}s"
    )

    # Poll features stream for produced entries
    features_found = False
    for i in range(max_retries):
        try:
            length = await valkey_client.xlen(features_key)
            if length > 0:
                entries = await valkey_client.xrange(features_key, count=1)
                if entries:
                    _, data = entries[0]
                    # Verify expected keys exist
                    decoded = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else v
                        )
                        for k, v in data.items()
                    }
                    assert "features" in decoded, f"Missing 'features' key in entry: {decoded.keys()}"
                    features_json = json.loads(decoded["features"])
                    assert len(features_json) > 0, "Features JSON is empty"
                    features_found = True
                    break
        except Exception:
            pass
        await asyncio.sleep(delay_seconds)

    assert features_found, (
        f"Timeout: no entries in {features_key} after {max_retries * delay_seconds}s"
    )


@pytest.mark.asyncio
async def test_strategy_worker_consumes_features(db_pools, valkey_client):
    """
    Verify strategy_worker created its consumer group on the features stream.
    """
    features_key = "features:BTCUSDT:1h"
    max_retries = 60
    delay_seconds = 2.0

    group_found = False
    for i in range(max_retries):
        try:
            groups = await valkey_client.xinfo_groups(features_key)
            for g in groups:
                name = g.get("name") or g.get(b"name", b"")
                if isinstance(name, bytes):
                    name = name.decode()
                if name == "strategy_app_group":
                    group_found = True
                    break
            if group_found:
                break
        except Exception:
            pass
        await asyncio.sleep(delay_seconds)

    assert group_found, (
        f"Timeout: strategy_app_group not found on {features_key} after {max_retries * delay_seconds}s"
    )


@pytest.mark.asyncio
async def test_downstream_workers_running_no_errors(db_pools):
    """
    Verify risk, execution, portfolio workers are running without crash loops.
    """
    result = subprocess.run(
        ["docker-compose", "ps"],
        capture_output=True,
        text=True,
    )
    output = result.stdout

    # Check that no worker container is in a restarting state
    for service in [
        "signal-worker",
        "strategy-worker",
        "risk-worker",
        "execution-worker",
        "portfolio-worker",
    ]:
        assert "restarting" not in output.lower() or service not in output, (
            f"{service} appears to be restarting. docker-compose ps output:\n{output}"
        )


@pytest.mark.asyncio
async def test_consumer_groups_exist(db_pools, valkey_client):
    """
    Verify each app created its expected consumer groups on the right streams.
    """
    required_groups = [
        ("stream:ohlcv:btcusdt:1h", "signal_app_group"),
        ("stream:ohlcv:btcusdt:4h", "signal_app_group"),
        ("features:BTCUSDT:1h", "strategy_app_group"),
        ("features:BTCUSDT:4h", "strategy_app_group"),
    ]
    optional_groups = [
        ("signals:BTCUSDT:1h", "risk_app_group"),
    ]

    max_retries = 60
    delay_seconds = 2.0

    for stream, expected_group in required_groups:
        found = False
        for i in range(max_retries):
            try:
                groups = await valkey_client.xinfo_groups(stream)
                for g in groups:
                    name = g.get("name") or g.get(b"name", b"")
                    if isinstance(name, bytes):
                        name = name.decode()
                    if name == expected_group:
                        found = True
                        break
                if found:
                    break
            except Exception:
                pass
            await asyncio.sleep(delay_seconds)
        assert found, (
            f"Required consumer group '{expected_group}' not found on stream '{stream}' "
            f"after {max_retries * delay_seconds}s"
        )

    # Optional groups — log but don't fail
    for stream, expected_group in optional_groups:
        try:
            groups = await valkey_client.xinfo_groups(stream)
            names = []
            for g in groups:
                name = g.get("name") or g.get(b"name", b"")
                if isinstance(name, bytes):
                    name = name.decode()
                names.append(name)
            if expected_group not in names:
                print(f"Optional group '{expected_group}' not yet on '{stream}' (OK)")
        except Exception:
            print(f"Stream '{stream}' does not exist yet (OK for optional check)")
