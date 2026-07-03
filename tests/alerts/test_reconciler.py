from __future__ import annotations

import pytest
from types import SimpleNamespace

from apps.alert_app.runtime.reconciler import AlertFreshnessReconciler
from apps.alert_app.contracts import AlertIncidentState
from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapePriority,
    ScraperProvider,
    ScrapeRequest,
)


class _FakeIncidentService:
    def __init__(self) -> None:
        self.events = []
        self.by_dedupe = {}

    async def record_event(self, event, *, route_names):
        self.events.append((event, route_names))
        return object(), True

    async def incident_for_dedupe(self, dedupe_key: str):
        return self.by_dedupe.get(dedupe_key)


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes = {
            "ingestion:runtime_status:SOLUSDT:1m": {
                "runtime_state": "WARMING",
                "updated_at": "100.0",
            },
            "signal:status:BTCUSDT:1h": {
                "pair": '{"asset":"BTCUSDT","timeframe":"1h"}',
                "last_feature_ts": "100.0",
            },
            "strategy:status:ETHUSDT:4h": {
                "pair": '{"asset":"ETHUSDT","timeframe":"4h"}',
                "last_signal_ts": "100.0",
            },
        }
        failed_job = ScrapeJobRecord(
            job_id="scrape-coinglass-heatmap-1",
            status=ScrapeJobStatus.FAILED,
            request=ScrapeRequest(
                provider=ScraperProvider.COINGLASS,
                dataset=ScrapeDataset.HEATMAP,
                intent=ScrapeIntent.ON_DEMAND_REFRESH,
                priority=ScrapePriority.NORMAL,
                coin="SOL",
                short_name="SOLUSDT",
            ),
            created_at=100.0,
            updated_at=100.0,
            error="provider timeout",
        )
        self.values = {
            "scraper:job:scrape-coinglass-heatmap-1": failed_job.model_dump_json(),
        }

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def keys(self, pattern: str):
        prefix = pattern.rstrip("*")
        return [key for key in [*self.hashes, *self.values] if key.startswith(prefix)]

    async def get(self, key: str):
        return self.values.get(key)


class _FakeConfig:
    def get(self, key: str, default=None):
        values = {
            "alerts.freshness.ingestion.warming_timeout_seconds": 50,
            "alerts.freshness.signal.max_lag_seconds": 50,
            "alerts.freshness.strategy.max_lag_seconds": 50,
            "alerts.health_checks": {
                "ingestion_runtime": {
                    "enabled": True,
                    "url": "http://ingestion:8002/health",
                    "source_app": "ingestion_app",
                    "healthy_statuses": ["ok"],
                }
            },
            "alerts.policies.default": {"routes": ["system_alerts"]},
            "alerts.routes.system_alerts": None,
        }
        return values.get(key, default)


@pytest.mark.asyncio
async def test_reconciler_emits_stale_events() -> None:
    incident_service = _FakeIncidentService()
    reconciler = AlertFreshnessReconciler(
        redis_client=_FakeRedis(),
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    async def _unhealthy(_config):
        return {
            "healthy": False,
            "http_status": None,
            "status": "request_failed",
            "error": "connection failed",
        }

    reconciler._probe_health_check = _unhealthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    original = reconciler_module.time.time
    reconciler_module.time.time = lambda: 200.0
    try:
        await reconciler.reconcile_once()
    finally:
        reconciler_module.time.time = original

    event_types = [event.event_type.value for event, _routes in incident_service.events]
    assert "ingestion_runtime_failure" in event_types
    assert "signal_freshness_breach" in event_types
    assert "strategy_freshness_breach" in event_types
    assert "scraper_failure" in event_types
    assert "system_health_breach" in event_types


@pytest.mark.asyncio
async def test_reconciler_skips_recovery_without_open_incident() -> None:
    incident_service = _FakeIncidentService()
    redis = _FakeRedis()
    redis.hashes = {
        "signal:status:BTCUSDT:1h": {
            "pair": '{"asset":"BTCUSDT","timeframe":"1h"}',
            "last_feature_ts": "190.0",
        },
        "strategy:status:ETHUSDT:4h": {
            "pair": '{"asset":"ETHUSDT","timeframe":"4h"}',
            "last_signal_ts": "190.0",
        },
    }
    redis.values = {}
    reconciler = AlertFreshnessReconciler(
        redis_client=redis,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    async def _healthy(_config):
        return {
            "healthy": True,
            "http_status": 200,
            "status": "ok",
            "error": None,
        }

    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    original = reconciler_module.time.time
    reconciler_module.time.time = lambda: 200.0
    try:
        await reconciler.reconcile_once()
    finally:
        reconciler_module.time.time = original

    assert incident_service.events == []


@pytest.mark.asyncio
async def test_reconciler_emits_ingestion_recovery_when_incident_exists() -> None:
    incident_service = _FakeIncidentService()
    incident_service.by_dedupe["ingestion_transition:SOLUSDT:1m"] = SimpleNamespace(
        state=AlertIncidentState.OPEN,
    )
    redis = _FakeRedis()
    redis.hashes = {
        "ingestion:runtime_status:SOLUSDT:1m": {
            "runtime_state": "LIVE",
            "updated_at": "190.0",
        },
    }
    redis.values = {}
    reconciler = AlertFreshnessReconciler(
        redis_client=redis,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    async def _healthy(_config):
        return {
            "healthy": True,
            "http_status": 200,
            "status": "ok",
            "error": None,
        }

    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    original = reconciler_module.time.time
    reconciler_module.time.time = lambda: 200.0
    try:
        await reconciler.reconcile_once()
    finally:
        reconciler_module.time.time = original

    event_types = [event.event_type.value for event, _routes in incident_service.events]
    assert event_types == ["recovery"]


@pytest.mark.asyncio
async def test_reconciler_emits_scraper_recovery_when_job_recovers() -> None:
    incident_service = _FakeIncidentService()
    incident_service.by_dedupe["scraper_job:scrape-coinglass-heatmap-1"] = SimpleNamespace(
        state=AlertIncidentState.OPEN,
    )
    redis = _FakeRedis()
    recovered_job = ScrapeJobRecord(
        job_id="scrape-coinglass-heatmap-1",
        status=ScrapeJobStatus.SUCCEEDED,
        request=ScrapeRequest(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            priority=ScrapePriority.NORMAL,
            coin="SOL",
            short_name="SOLUSDT",
        ),
        created_at=100.0,
        updated_at=190.0,
    )
    redis.hashes = {}
    redis.values = {
        "scraper:job:scrape-coinglass-heatmap-1": recovered_job.model_dump_json(),
    }
    reconciler = AlertFreshnessReconciler(
        redis_client=redis,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    async def _healthy(_config):
        return {
            "healthy": True,
            "http_status": 200,
            "status": "ok",
            "error": None,
        }

    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    original = reconciler_module.time.time
    reconciler_module.time.time = lambda: 200.0
    try:
        await reconciler.reconcile_once()
    finally:
        reconciler_module.time.time = original

    event_types = [event.event_type.value for event, _routes in incident_service.events]
    assert event_types == ["recovery"]


@pytest.mark.asyncio
async def test_reconciler_emits_health_recovery_when_check_recovers() -> None:
    incident_service = _FakeIncidentService()
    incident_service.by_dedupe["health_check:ingestion_runtime"] = SimpleNamespace(
        state=AlertIncidentState.OPEN,
    )
    redis = _FakeRedis()
    redis.hashes = {}
    redis.values = {}
    reconciler = AlertFreshnessReconciler(
        redis_client=redis,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    async def _healthy(_config):
        return {
            "healthy": True,
            "http_status": 200,
            "status": "ok",
            "error": None,
        }

    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    original = reconciler_module.time.time
    reconciler_module.time.time = lambda: 200.0
    try:
        await reconciler.reconcile_once()
    finally:
        reconciler_module.time.time = original

    event_types = [event.event_type.value for event, _routes in incident_service.events]
    assert event_types == ["recovery"]
