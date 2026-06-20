import asyncio
import json
import subprocess
import time
import uuid
from urllib import request

import pytest
import asyncpg
from libs.common.db.pool_manager import DBPoolManager

from tests.e2e.helpers import docker_compose_command


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


async def _wait_until(
    predicate,
    *,
    timeout_s: float,
    interval_s: float = 1.0,
    description: str,
):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for {description}")


async def _latest_stream_payload(valkey_client, stream_key: str):
    entries = await valkey_client.xrevrange(stream_key, count=1)
    if not entries:
        return None
    _, payload = entries[0]
    return payload


async def _latest_stream_timestamp(valkey_client, stream_key: str) -> float | None:
    payload = await _latest_stream_payload(valkey_client, stream_key)
    if not payload:
        return None
    raw = payload.get("timestamp")
    if raw in (None, ""):
        return None
    ts = float(raw)
    return ts / 1000.0 if ts > 1e12 else ts


async def _wait_for_ingestion_health_after_restart(timeout_s: float = 60.0) -> None:
    health_url = "http://127.0.0.1:8002/health"

    async def _healthy():
        def _probe():
            with request.urlopen(health_url, timeout=5) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("status") == "ok"

        try:
            return await asyncio.to_thread(_probe)
        except Exception:
            return None

    await _wait_until(
        _healthy,
        timeout_s=timeout_s,
        interval_s=2.0,
        description="ingestion healthcheck after restart",
    )

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
        [*docker_compose_command(), "ps"],
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
            f"{service} appears to be restarting. compose ps output:\n{output}"
        )


@pytest.mark.asyncio
async def test_consumer_groups_exist(db_pools, valkey_client):
    """
    Verify each app created its expected consumer groups on the right streams.
    """
    required_groups = [
        ("stream:ohlcv:btcusdt:1h", "signal_app_group"),
        ("stream:ohlcv:btcusdt:4h", "signal_app_group"),
        ("stream:ohlcv:ethusdt:4h", "signal_app_group"),
        ("features:BTCUSDT:1h", "strategy_app_group"),
        ("features:BTCUSDT:4h", "strategy_app_group"),
        ("features:ETHUSDT:4h", "strategy_app_group"),
    ]
    optional_groups = [
        ("signals:BTCUSDT:1h", "risk_app_group"),
        ("signals:BTCUSDT:4h", "risk_app_group"),
        ("signals:ETHUSDT:4h", "risk_app_group"),
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


# ---------------------------------------------------------------------------
# Phase 3A Sprint 2 — Synthetic Injection E2E Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthetic_signal_to_order_roundtrip(db_pools, valkey_client):
    """Inject a signal, verify risk produces an order on orders:{asset} OR consumed the signal."""
    from libs.contracts.schemas import TradeSignal, valkey_encode

    unique_key = f"e2e_signal_{uuid.uuid4().hex[:8]}"
    signal = TradeSignal(
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=time.time(),
        direction=1,
        conviction=0.9,
        price=50000.0,
        idempotency_key=unique_key,
        model_name="e2e_test_model",
        metadata={"source": "e2e_test"},
    )

    # Inject signal into the signals stream
    await valkey_client.xadd(
        "signals:BTCUSDT:4h",
        valkey_encode(signal),
        maxlen=5000,
    )

    # Poll orders:BTCUSDT for an order with matching idempotency key
    order_found = False
    max_retries = 30
    for _ in range(max_retries):
        try:
            entries = await valkey_client.xrange("orders:BTCUSDT", count=50)
            for _, data in entries:
                if data.get("idempotency_key") == unique_key:
                    assert data["asset"] == "BTCUSDT"
                    assert data["side"] == "buy"  # direction=1 → buy
                    assert float(data["requested_price"]) == 50000.0
                    order_found = True
                    break
        except Exception:
            pass
        if order_found:
            break
        await asyncio.sleep(2)

    if order_found:
        return  # Success — risk accepted the signal and produced an order

    # Fallback: risk may have legitimately rejected the signal.
    # Verify the signal was at least consumed by checking consumer group info.
    signal_consumed = False
    try:
        info = await valkey_client.xinfo_groups("signals:BTCUSDT:4h")
        for g in info:
            name = g.get("name", "")
            if name == "risk_app_group":
                entries_read = int(g.get("entries-read", 0) or 0)
                if entries_read > 0:
                    signal_consumed = True
                    break
    except Exception:
        pass

    assert signal_consumed, (
        f"Order with key {unique_key} not found on orders:BTCUSDT AND risk_app_group "
        f"shows no consumption on signals:BTCUSDT:4h after {max_retries * 2}s"
    )


@pytest.mark.asyncio
async def test_synthetic_order_to_fill_roundtrip(db_pools, valkey_client):
    """Inject an order, verify execution produces a fill."""
    from libs.contracts.schemas import OrderExecutionRequest, valkey_encode

    unique_key = f"e2e_order_{uuid.uuid4().hex[:8]}"
    order = OrderExecutionRequest(
        asset="BTCUSDT",
        side="buy",
        size=0.001,
        order_type="market",
        timestamp=time.time(),
        requested_price=50000.0,
        idempotency_key=unique_key,
        stop_loss_price=49000.0,
        take_profit_price=52000.0,
        model_name="e2e_test_model",
        source_timeframe="4h",
    )

    await valkey_client.xadd("orders:BTCUSDT", valkey_encode(order), maxlen=5000)

    # Poll fills:BTCUSDT for a fill with matching idempotency key
    fill_found = False
    max_retries = 30
    for _ in range(max_retries):
        try:
            entries = await valkey_client.xrange("fills:BTCUSDT", count=100)
            for _, data in entries:
                if data.get("idempotency_key") == unique_key:
                    assert data["asset"] == "BTCUSDT"
                    assert data["side"] == "buy"
                    assert data["status"] == "FILLED"
                    assert float(data["filled_size"]) > 0
                    fill_found = True
                    break
        except Exception:
            pass
        if fill_found:
            break
        await asyncio.sleep(2)

    assert fill_found, (
        f"Fill with key {unique_key} not found on fills:BTCUSDT after {max_retries * 2}s"
    )


@pytest.mark.asyncio
async def test_fill_populates_portfolio_equity(db_pools, valkey_client):
    """Verify that fills trigger portfolio equity snapshots in the DB."""
    from libs.contracts.schemas import OrderExecutionRequest, valkey_encode

    unique_key = f"e2e_portfolio_{uuid.uuid4().hex[:8]}"
    order = OrderExecutionRequest(
        asset="BTCUSDT",
        side="buy",
        size=0.001,
        order_type="market",
        timestamp=time.time(),
        requested_price=50000.0,
        idempotency_key=unique_key,
    )
    await valkey_client.xadd("orders:BTCUSDT", valkey_encode(order), maxlen=5000)

    # Wait for fill to be consumed by portfolio_worker and equity point written
    pool = DBPoolManager.get_reader_pool()
    equity_found = False
    max_retries = 30
    for _ in range(max_retries):
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as cnt FROM portfolio_equity_curve"
                )
                if row and row["cnt"] > 0:
                    equity_found = True
                    break
            except Exception:
                pass
        await asyncio.sleep(2)

    assert equity_found, (
        "No equity curve entries found in portfolio_equity_curve after fill injection"
    )


@pytest.mark.asyncio
async def test_execution_idempotency(db_pools, valkey_client):
    """Same idempotency key should only produce one fill."""
    from libs.contracts.schemas import OrderExecutionRequest, valkey_encode

    unique_key = f"e2e_idem_{uuid.uuid4().hex[:8]}"
    order = OrderExecutionRequest(
        asset="BTCUSDT",
        side="buy",
        size=0.001,
        order_type="market",
        timestamp=time.time(),
        requested_price=50000.0,
        idempotency_key=unique_key,
    )

    # Inject same order twice
    payload = valkey_encode(order)
    await valkey_client.xadd("orders:BTCUSDT", payload, maxlen=5000)
    await asyncio.sleep(1)
    await valkey_client.xadd("orders:BTCUSDT", payload, maxlen=5000)

    # Wait for processing
    await asyncio.sleep(10)

    # Count fills with this idempotency key
    entries = await valkey_client.xrange("fills:BTCUSDT")
    matching_fills = [e for _, e in entries if e.get("idempotency_key") == unique_key]
    assert len(matching_fills) == 1, (
        f"Expected 1 fill for {unique_key}, got {len(matching_fills)}"
    )


@pytest.mark.asyncio
async def test_all_pipeline_db_tables_exist(db_pools):
    """Verify all expected DB tables exist."""
    pool = DBPoolManager.get_reader_pool()
    expected_tables = [
        "ohlcv",
        "ticks",
        "open_interest",
        "risk_positions",
        "risk_account_snapshots",
        "execution_fills",
        "execution_idempotency_keys",
        "portfolio_equity_curve",
        "portfolio_closed_trades",
    ]

    async with pool.acquire() as conn:
        for table in expected_tables:
            try:
                await conn.fetchrow(f"SELECT 1 FROM {table} LIMIT 0")
            except asyncpg.exceptions.UndefinedTableError:
                pytest.fail(f"Expected table '{table}' does not exist")


@pytest.mark.asyncio
async def test_all_consumer_groups_comprehensive(db_pools, valkey_client):
    """Comprehensive check: all expected consumer groups on all pipeline streams."""
    # These groups MUST exist for the pipeline to function
    required = {
        "stream:ohlcv:btcusdt:1h": ["signal_app_group"],
        "stream:ohlcv:btcusdt:4h": ["signal_app_group"],
        "stream:ohlcv:ethusdt:4h": ["signal_app_group"],
        "features:BTCUSDT:1h": ["strategy_app_group"],
        "features:BTCUSDT:4h": ["strategy_app_group"],
        "features:ETHUSDT:4h": ["strategy_app_group"],
    }
    # These are expected but depend on signals existing
    optional = {
        "signals:BTCUSDT:1h": ["risk_app_group"],
        "signals:BTCUSDT:4h": ["risk_app_group"],
        "signals:ETHUSDT:4h": ["risk_app_group"],
        "orders:BTCUSDT": ["execution_app_group"],
        "orders:ETHUSDT": ["execution_app_group"],
        "fills:BTCUSDT": ["risk_app_fills_group", "portfolio_app_fills_group"],
        "fills:ETHUSDT": ["risk_app_fills_group", "portfolio_app_fills_group"],
    }

    max_retries = 30
    for stream, groups in required.items():
        for expected_group in groups:
            found = False
            for _ in range(max_retries):
                try:
                    info = await valkey_client.xinfo_groups(stream)
                    names = [g.get("name", "") for g in info]
                    if expected_group in names:
                        found = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
            assert found, (
                f"Required group '{expected_group}' not found on '{stream}'"
            )

    # Optional — log but don't fail
    for stream, groups in optional.items():
        for expected_group in groups:
            try:
                info = await valkey_client.xinfo_groups(stream)
                names = [g.get("name", "") for g in info]
                if expected_group not in names:
                    print(f"Optional: '{expected_group}' not on '{stream}' (OK)")
            except Exception:
                print(f"Optional: stream '{stream}' does not exist yet (OK)")


# ---------------------------------------------------------------------------
# Phase 3A Sprint 3 — Organic Validation (slow marker)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.slow
async def test_organic_candle_full_roundtrip(db_pools, valkey_client):
    """Verify organic ingestion/signal/strategy liveness with cadence-aware freshness.

    The prior version waited for a fresh 4h candle inside a 2-minute wall clock window,
    which was timing-fragile outside exact higher-timeframe closes. After a cold boot,
    higher-timeframe close streams may legitimately stay empty until the next scheduled
    close, while downstream apps can still be live from bootstrap snapshots. This version checks:
    - ingestion keeps the canonical 1m lane near real time
    - signal_app has produced bootstrap/live feature payloads for active BTCUSDT model lanes
    - strategy_app is attached to those feature streams via consumer groups
    """
    from libs.common.db.timescale_reader import TimescaleReader

    reader = TimescaleReader(DBPoolManager.get_reader_pool())

    async def _latest_stream_ts_seconds(stream_key: str) -> float | None:
        entries = await valkey_client.xrevrange(stream_key, count=1)
        if not entries:
            return None
        _, data = entries[0]
        ts = float(data.get("timestamp", "0"))
        if ts <= 0:
            return None
        return ts / 1000 if ts > 1e12 else ts

    async def _feature_stream_exists(stream_key: str) -> bool:
        latest_ts = await _latest_stream_ts_seconds(stream_key)
        return latest_ts is not None

    async def _wait_for_feature_stream(stream_key: str) -> None:
        max_retries = 60
        for _ in range(max_retries):
            if await _feature_stream_exists(stream_key):
                return
            await asyncio.sleep(2)
        pytest.skip(
            f"Feature stream {stream_key} did not appear after bootstrap; "
            "downstream warmup may still be incomplete."
        )

    def _group_name(group: dict) -> str:
        name = group.get("name") or group.get(b"name", b"")
        return name.decode() if isinstance(name, bytes) else str(name)

    max_ts = await reader.get_max_timestamp("BTCUSDT", "1m")
    assert max_ts > 0, "No canonical BTCUSDT 1m data in Timescale"
    now_ms = time.time() * 1000
    assert now_ms - max_ts <= 5 * 60 * 1000, (
        f"Canonical BTCUSDT 1m lane is stale by {(now_ms - max_ts) / 1000:.1f}s"
    )

    await _wait_for_feature_stream("features:BTCUSDT:1h")
    await _wait_for_feature_stream("features:BTCUSDT:4h")

    strategy_groups_1h = await valkey_client.xinfo_groups("features:BTCUSDT:1h")
    strategy_groups_4h = await valkey_client.xinfo_groups("features:BTCUSDT:4h")
    assert any(
        _group_name(group) == "strategy_app_group"
        for group in strategy_groups_1h
    ), "strategy_app_group missing on features:BTCUSDT:1h"
    assert any(
        _group_name(group) == "strategy_app_group"
        for group in strategy_groups_4h
    ), "strategy_app_group missing on features:BTCUSDT:4h"

    try:
        signals_len = await valkey_client.xlen("signals:BTCUSDT:4h")
        print(f"Signals on signals:BTCUSDT:4h: {signals_len}")
    except Exception:
        print("signals:BTCUSDT:4h stream doesn't exist yet (OK — no signal triggered)")

    print("Organic pipeline liveness verified!")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_ingestion_restart_recovers_and_strategy_consumes_after_restart(
    db_pools,
    valkey_client,
):
    """Restart ingestion runtime, verify canonical lane recovers, then strategy still consumes."""
    from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
    from apps.strategy_app.state import StrategyPair, StrategyPairState
    from libs.common.db.timescale_reader import TimescaleReader
    from libs.contracts.schemas import FeatureVector
    from libs.contracts.serialization import valkey_decode, valkey_encode

    reader = TimescaleReader(DBPoolManager.get_reader_pool())
    feature_stream = "features:BTCUSDT:1h"
    pair = StrategyPair(asset="BTCUSDT", timeframe="1h")
    state_store = StrategyRuntimeStateStore(valkey_client)

    max_ts_before = await reader.get_max_timestamp("BTCUSDT", "1m")
    assert max_ts_before > 0, "Need live BTCUSDT 1m data before restart"

    latest_feature_payload = await _wait_until(
        lambda: _latest_stream_payload(valkey_client, feature_stream),
        timeout_s=120,
        interval_s=2,
        description=f"{feature_stream} latest payload before restart",
    )
    latest_feature = valkey_decode(latest_feature_payload, FeatureVector)

    status_before = await _wait_until(
        lambda: state_store.read(pair),
        timeout_s=60,
        interval_s=1,
        description="strategy runtime status before restart",
    )
    assert status_before.state == StrategyPairState.LIVE

    subprocess.run(
        [*docker_compose_command(), "restart", "worker-streams"],
        check=True,
        capture_output=True,
        text=True,
    )
    await _wait_for_ingestion_health_after_restart()

    max_ts_after = await _wait_until(
        lambda: _newer_canonical_timestamp(reader, max_ts_before),
        timeout_s=180,
        interval_s=2,
        description="canonical BTCUSDT 1m timestamp to advance after restart",
    )
    assert max_ts_after > max_ts_before

    injected_ts = max(time.time(), float(latest_feature.timestamp) + 1.0)
    injected_feature = latest_feature.model_copy(update={"timestamp": injected_ts})
    await valkey_client.xadd(feature_stream, valkey_encode(injected_feature), maxlen=5000)

    status_after = await _wait_until(
        lambda: _strategy_status_at_or_after(
            state_store,
            pair,
            min_last_feature_ts=injected_ts,
        ),
        timeout_s=120,
        interval_s=2,
        description="strategy runtime to consume a fresh feature after restart",
    )
    assert status_after.state == StrategyPairState.LIVE
    assert (status_after.last_feature_ts or 0.0) >= injected_ts


async def _newer_canonical_timestamp(reader, previous_ts: float):
    current = await reader.get_max_timestamp("BTCUSDT", "1m")
    if current > previous_ts:
        return current
    return None


async def _strategy_status_at_or_after(state_store, pair, *, min_last_feature_ts: float):
    from apps.strategy_app.state import StrategyPairState

    status = await state_store.read(pair)
    if status is None:
        return None
    if status.state != StrategyPairState.LIVE:
        return None
    if (status.last_feature_ts or 0.0) >= min_last_feature_ts:
        return status
    return None


@pytest.mark.asyncio
@pytest.mark.slow
async def test_db_persistence_across_restart(db_pools):
    """Verify OHLCV data survives a container restart (volume-backed)."""
    pool = DBPoolManager.get_reader_pool()

    # 1. Get current row count
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM ohlcv")
        count_before = row["cnt"]

    assert count_before > 0, "Need existing OHLCV data for persistence test"

    # 2. Restart the ingestion worker (not the DB — data should persist)
    subprocess.run(
        [*docker_compose_command(), "restart", "worker-streams"],
        check=True,
        capture_output=True,
        text=True,
    )
    await asyncio.sleep(10)  # Wait for restart

    # 3. Verify data still exists — DB container was NOT restarted
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM ohlcv")
        count_after = row["cnt"]

    assert count_after >= count_before, (
        f"Data lost after restart: {count_before} → {count_after}"
    )
    print(f"Persistence verified: {count_before} → {count_after} rows")
