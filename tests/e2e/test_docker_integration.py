import asyncio
import os
import pytest
import asyncpg
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
