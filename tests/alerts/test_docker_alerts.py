from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from urllib import request

import pytest
import pytest_asyncio
import valkey.asyncio as avalkey

from apps.execution_app.state import ExecutionFailureEvent
from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapePriority,
    ScraperProvider,
    ScrapeRequest,
)
from libs.contracts.serialization import valkey_encode


def _docker_compose_command() -> list[str]:
    override = os.getenv("E2E_DOCKER_COMPOSE_COMMAND")
    if override:
        return shlex.split(override)
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    raise RuntimeError("Docker Compose CLI not found for alert Docker tests")


def _docker_compose_exec(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_docker_compose_command(), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _alerts_url(path: str) -> str:
    suffix = path if path.startswith("/") else f"/{path}"
    return f"http://127.0.0.1:8096{suffix}"


def _http_json(
    method: str,
    url: str,
    *,
    data: dict | None = None,
) -> dict:
    payload = None
    headers = {}
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=payload, headers=headers, method=method)
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


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


async def _wait_for_alert_api() -> None:
    async def _healthy():
        try:
            payload = await asyncio.to_thread(_http_json, "GET", _alerts_url("/alerts/health"))
        except Exception:
            return None
        return payload if payload.get("status") in {"ok", "degraded"} else None

    await _wait_until(
        _healthy,
        timeout_s=30.0,
        interval_s=1.0,
        description="alert API health",
    )


async def _wait_for_incident(
    *,
    asset: str | None = None,
    source_app: str | None = None,
    event_type: str | None = None,
    predicate=None,
    timeout_s: float = 30.0,
):
    query: list[str] = ["limit=20"]
    if asset:
        query.append(f"asset={asset}")
    if source_app:
        query.append(f"source_app={source_app}")
    url = _alerts_url(f"/alerts/incidents?{'&'.join(query)}")

    async def _find():
        payload = await asyncio.to_thread(_http_json, "GET", url)
        for item in payload.get("items", []):
            if event_type and item.get("event_type") != event_type:
                continue
            if predicate and not predicate(item):
                continue
            return item
        return None

    return await _wait_until(
        _find,
        timeout_s=timeout_s,
        interval_s=1.0,
        description=f"alert incident for asset={asset} source_app={source_app}",
    )


def _trigger_alert_reconcile_once() -> None:
    script = """
import asyncio
from apps.alert_app.settings import create_alert_config_manager, AlertAppSettings
from apps.alert_app.incidents import AlertIncidentRepository, AlertIncidentService, AlertIncidentStore
from apps.alert_app.runtime.reconciler import AlertFreshnessReconciler
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager

async def main():
    config_mgr = create_alert_config_manager()
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    db_pool = DBPoolManager.get_writer_pool()
    settings = AlertAppSettings.from_config(config_mgr)
    service = AlertIncidentService(
        AlertIncidentRepository(db_pool),
        AlertIncidentStore(
            redis_client,
            dedupe_ttl_seconds=settings.dedupe_ttl_seconds,
            open_state_ttl_seconds=settings.open_state_ttl_seconds,
            hot_summary_ttl_seconds=settings.hot_summary_ttl_seconds,
        ),
        renotify_seconds=settings.renotify_seconds,
    )
    reconciler = AlertFreshnessReconciler(
        redis_client=redis_client,
        incident_service=service,
        notification_dispatcher=None,
        config_manager=config_mgr,
    )
    try:
        await reconciler.reconcile_once()
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()
        config_mgr.shutdown()

asyncio.run(main())
"""
    _docker_compose_exec("exec", "-T", "alert-worker", "python", "-c", script)


@pytest_asyncio.fixture
async def alert_valkey_client():
    client = avalkey.Valkey.from_url("redis://localhost:6380/0", decode_responses=True)
    await _wait_for_alert_api()
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_alert_api_controls_end_to_end(alert_valkey_client):
    from libs.common.asset_manifest import (
        ASSET_LIFECYCLE_STREAM,
        AssetLifecycleEvent,
        AssetLifecycleEventType,
    )

    symbol = f"ALERT{uuid.uuid4().hex[:6]}".upper()
    asset_version = int(time.time())
    event = AssetLifecycleEvent(
        event_id=f"e2e-alert-{symbol}-{asset_version}",
        event_type=AssetLifecycleEventType.ASSET_PAUSED,
        command_id=f"e2e-command-{asset_version}",
        command_type="pause_asset",
        symbol=symbol,
        exchange="binance",
        provider="binance_native",
        base_timeframe="1m",
        publish_timeframes=["30m"],
        timeframes=["1m", "30m"],
        enabled=True,
        desired_state="PAUSED",
        request_id=f"e2e-request-{asset_version}",
        asset_version=asset_version,
        timeframe_version=asset_version,
        requested_by="pytest_e2e",
        reason="alert_api_controls_e2e",
        emitted_at=time.time(),
    )
    await alert_valkey_client.xadd(
        ASSET_LIFECYCLE_STREAM,
        valkey_encode(event, inject_trace=False),
        maxlen=10000,
        approximate=True,
    )

    incident = await _wait_for_incident(
        asset=symbol,
        source_app="ingestion_app",
        event_type="lifecycle_event",
    )
    incident_id = incident["incident_id"]

    detail = await asyncio.to_thread(_http_json, "GET", _alerts_url(f"/alerts/incidents/{incident_id}"))
    assert detail["incident"]["incident_id"] == incident_id

    acked = await asyncio.to_thread(
        _http_json,
        "POST",
        _alerts_url(f"/alerts/incidents/{incident_id}/ack"),
    )
    assert acked["incident"]["state"] == "acked"

    resolved = await asyncio.to_thread(
        _http_json,
        "POST",
        _alerts_url(f"/alerts/incidents/{incident_id}/resolve"),
    )
    assert resolved["incident"]["state"] == "resolved"

    silence = await asyncio.to_thread(
        _http_json,
        "POST",
        _alerts_url("/alerts/silences"),
        data={
            "match": {"asset": symbol},
            "reason": "e2e silence delete",
            "created_by": "pytest_e2e",
        },
    )
    silence_id = silence["silence"]["silence_id"]

    deleted = await asyncio.to_thread(
        _http_json,
        "DELETE",
        _alerts_url(f"/alerts/silences/{silence_id}"),
    )
    assert deleted["status"] == "ok"


@pytest.mark.asyncio
async def test_alert_execution_failure_creates_incident(alert_valkey_client):
    event = ExecutionFailureEvent(
        asset="BTCUSDT",
        stream="execution:orders:BTCUSDT",
        consumer_group="execution_app_group",
        consumer_name="pytest_e2e",
        message_id=f"exec-{uuid.uuid4().hex[:8]}",
        idempotency_key=f"exec-idem-{uuid.uuid4().hex[:8]}",
        timestamp=time.time(),
        error_type="OrderValidationError",
        error_message="simulated execution failure",
        order_side="buy",
        order_size=1.0,
        requested_price=12345.0,
        order_type="market",
    )
    await alert_valkey_client.xadd(
        "execution:failures:BTCUSDT",
        valkey_encode(event, inject_trace=False),
        maxlen=1000,
        approximate=True,
    )

    incident = await _wait_for_incident(
        asset="BTCUSDT",
        source_app="execution_app",
        event_type="execution_failure",
        predicate=lambda item: item.get("detail", {}).get("idempotency_key") == event.idempotency_key,
        timeout_s=30.0,
    )
    assert incident["severity"] == "critical"
    assert "execution_alerts" in incident["route_names"]


@pytest.mark.asyncio
async def test_alert_signal_freshness_breach_and_recovery(alert_valkey_client):
    asset = f"FRESH{uuid.uuid4().hex[:6]}".upper()
    timeframe = "5m"
    runtime_key = f"signal:status:{asset}:{timeframe}"
    now_ts = time.time()

    await alert_valkey_client.hset(
        runtime_key,
        mapping={
            "pair": json.dumps({"asset": asset, "timeframe": timeframe}),
            "last_feature_ts": str(now_ts - 4000),
        },
    )
    await asyncio.to_thread(_trigger_alert_reconcile_once)

    stale = await _wait_for_incident(
        asset=asset,
        source_app="signal_app",
        event_type="signal_freshness_breach",
        predicate=lambda item: item.get("state") == "open",
        timeout_s=20.0,
    )
    assert stale["state"] == "open"

    await alert_valkey_client.hset(
        runtime_key,
        mapping={
            "pair": json.dumps({"asset": asset, "timeframe": timeframe}),
            "last_feature_ts": str(time.time()),
        },
    )
    await asyncio.to_thread(_trigger_alert_reconcile_once)

    async def _resolved():
        payload = await asyncio.to_thread(
            _http_json,
            "GET",
            _alerts_url(f"/alerts/incidents/{stale['incident_id']}"),
        )
        incident = payload.get("incident")
        if incident and incident.get("state") == "resolved":
            return incident
        return None

    resolved = await _wait_until(
        _resolved,
        timeout_s=20.0,
        interval_s=1.0,
        description="signal freshness recovery incident resolution",
    )
    assert resolved["resolved_at"] is not None


@pytest.mark.asyncio
async def test_alert_ingestion_transition_timeout_and_recovery(alert_valkey_client):
    asset = f"WARM{uuid.uuid4().hex[:6]}".upper()
    timeframe = "1m"
    runtime_key = f"ingestion:runtime_status:{asset}:{timeframe}"

    await alert_valkey_client.hset(
        runtime_key,
        mapping={
            "runtime_state": "WARMING",
            "updated_at": str(time.time() - 4000),
        },
    )
    await asyncio.to_thread(_trigger_alert_reconcile_once)

    stale = await _wait_for_incident(
        asset=asset,
        source_app="ingestion_app",
        event_type="ingestion_runtime_failure",
        predicate=lambda item: item.get("state") == "open"
        and item.get("detail", {}).get("runtime_state") == "WARMING",
        timeout_s=20.0,
    )
    assert stale["state"] == "open"

    await alert_valkey_client.hset(
        runtime_key,
        mapping={
            "runtime_state": "LIVE",
            "updated_at": str(time.time()),
        },
    )
    await asyncio.to_thread(_trigger_alert_reconcile_once)

    async def _resolved():
        payload = await asyncio.to_thread(
            _http_json,
            "GET",
            _alerts_url(f"/alerts/incidents/{stale['incident_id']}"),
        )
        incident = payload.get("incident")
        if incident and incident.get("state") == "resolved":
            return incident
        return None

    resolved = await _wait_until(
        _resolved,
        timeout_s=20.0,
        interval_s=1.0,
        description="ingestion transition recovery incident resolution",
    )
    assert resolved["resolved_at"] is not None


@pytest.mark.asyncio
async def test_alert_scraper_failure_creates_incident(alert_valkey_client):
    job_id = f"scrape-coinglass-heatmap-{uuid.uuid4().hex[:8]}"
    record = ScrapeJobRecord(
        job_id=job_id,
        status=ScrapeJobStatus.FAILED,
        request=ScrapeRequest(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            priority=ScrapePriority.NORMAL,
            coin="SOL",
            short_name="SOLUSDT",
        ),
        created_at=time.time(),
        updated_at=time.time(),
        error="provider timeout",
    )
    await alert_valkey_client.set(
        f"scraper:job:{job_id}",
        record.model_dump_json(),
        ex=3600,
    )
    await asyncio.to_thread(_trigger_alert_reconcile_once)

    incident = await _wait_for_incident(
        asset="SOLUSDT",
        source_app="scraper_app",
        event_type="scraper_failure",
        predicate=lambda item: item.get("detail", {}).get("job_id") == job_id,
        timeout_s=20.0,
    )
    assert incident["state"] == "open"
