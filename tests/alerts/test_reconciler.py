from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.alert_app.contracts import AlertIncidentState, AlertSourceApp
from apps.alert_app.runtime.reconciler import (
    AlertFreshnessReconciler,
    _source_app_from_value,
)
from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapePriority,
    ScrapeRequest,
    ScraperProvider,
)
from apps.scraper_app.runtime_status import ScraperRuntimeStatus


class _FakeIncidentService:
    def __init__(self) -> None:
        self.events = []
        self.by_dedupe = {}

    async def record_event(self, event, *, route_names):
        self.events.append((event, route_names))
        return object(), True

    async def incident_for_dedupe(self, dedupe_key: str):
        return self.by_dedupe.get(dedupe_key)


class _HealthIncidentService(_FakeIncidentService):
    async def record_event(self, event, *, route_names):
        self.events.append((event, route_names))
        self.by_dedupe[event.dedupe_key] = SimpleNamespace(
            state=AlertIncidentState.OPEN
        )
        return object(), True


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes = {
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
    def __init__(self) -> None:
        self.values = {
            "alerts.freshness.scraper.worker_running_timeout_seconds": 50,
            "alerts.freshness.scraper.success_stale_threshold_seconds": 50,
            "alerts.freshness.signal.max_lag_seconds": 50,
            "alerts.freshness.strategy.max_lag_seconds": 50,
            "alerts.health_checks": {
                "ingestion_runtime": {
                    "enabled": True,
                    "url": "http://ingestion:8003/health/ready",
                    "source_app": "ingestion",
                    "startup_grace_seconds": 0,
                    "healthy_statuses": ["ready"],
                }
            },
            "alerts.policies": {"default": {"routes": ["system_alerts"]}},
            "alerts.policies.default": {"routes": ["system_alerts"]},
            "alerts.routes": {
                "system_alerts": {
                    "enabled": True,
                    "transport": "webhook",
                    "destination": "system",
                }
            },
            "alerts.routes.system_alerts": None,
        }

    def get(self, key: str, default=None):
        return self.values.get(key, default)


async def _healthy(_config):
    return {"healthy": True, "http_status": 200, "status": "ready", "error": None}


class _FakeHealthResponse:
    status = 200

    def __init__(self, payload: dict[str, str]) -> None:
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def json(self):
        return self.payload


class _FakeHealthSession:
    def __init__(self, payload: dict[str, str]) -> None:
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def get(self, _url):
        return _FakeHealthResponse(self.payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("healthy_statuses", "expected_healthy"),
    [(["ready"], True), (["ok"], False)],
)
async def test_probe_health_check_uses_v2_ready_status(
    monkeypatch,
    healthy_statuses,
    expected_healthy,
) -> None:
    import apps.alert_app.runtime.reconciler as reconciler_module

    monkeypatch.setattr(
        reconciler_module.aiohttp,
        "ClientSession",
        lambda **_kwargs: _FakeHealthSession({"status": "ready"}),
    )
    reconciler = AlertFreshnessReconciler(
        redis_client=_FakeRedis(),
        incident_service=_FakeIncidentService(),
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )

    result = await reconciler._probe_health_check(
        {
            "url": "http://ingestion:8003/health/ready",
            "healthy_statuses": healthy_statuses,
        }
    )

    assert result == {
        "healthy": expected_healthy,
        "http_status": 200,
        "status": "ready",
        "error": None,
    }


def test_decision_health_source_identity_normalizes_without_system_fallback() -> None:
    assert _source_app_from_value("decision") is AlertSourceApp.DECISION
    assert _source_app_from_value("decision_app") is AlertSourceApp.DECISION


@pytest.mark.asyncio
async def test_decision_health_breach_and_recovery_preserve_source_identity() -> None:
    incident_service = _HealthIncidentService()
    config = _FakeConfig()
    config.values["alerts.health_checks"] = {
        "decision_runtime": {
            "enabled": True,
            "url": "http://decision:8004/health/ready",
            "source_app": "decision",
            "startup_grace_seconds": 0,
            "healthy_statuses": ["ready"],
        }
    }
    reconciler = AlertFreshnessReconciler(
        redis_client=_FakeRedis(),
        incident_service=incident_service,
        config_manager=config,
        interval_seconds=1,
    )
    probe_results = iter(
        (
            {
                "healthy": False,
                "http_status": 503,
                "status": "not_ready",
                "error": None,
            },
            {
                "healthy": True,
                "http_status": 200,
                "status": "ready",
                "error": None,
            },
        )
    )

    async def probe_health_check(_config):
        return next(probe_results)

    reconciler._probe_health_check = probe_health_check

    await reconciler._reconcile_health_checks(200.0)
    await reconciler._reconcile_health_checks(201.0)

    assert [event.source_app for event, _routes in incident_service.events] == [
        AlertSourceApp.DECISION,
        AlertSourceApp.DECISION,
    ]
    assert incident_service.events[0][1] == ["system_alerts"]


@pytest.mark.asyncio
async def test_reconciler_emits_signal_strategy_scraper_and_health_events(
    monkeypatch,
) -> None:
    incident_service = _FakeIncidentService()
    reconciler = AlertFreshnessReconciler(
        redis_client=_FakeRedis(),
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )
    reconciler._probe_health_check = lambda config: _unhealthy(config)

    import apps.alert_app.runtime.reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module.time, "time", lambda: 200.0)
    await reconciler.reconcile_once()

    event_types = [event.event_type.value for event, _routes in incident_service.events]
    assert "ingestion_runtime_failure" not in event_types
    assert "signal_freshness_breach" in event_types
    assert "strategy_freshness_breach" in event_types
    assert "scraper_failure" in event_types
    assert "system_health_breach" in event_types
    health_event = next(
        event
        for event, _routes in incident_service.events
        if event.event_type.value == "system_health_breach"
    )
    assert "ingestion:8003/health/ready" in health_event.summary


async def _unhealthy(_config):
    return {
        "healthy": False,
        "http_status": None,
        "status": "request_failed",
        "error": "connection failed",
    }


@pytest.mark.asyncio
async def test_reconciler_skips_recovery_without_open_incident(monkeypatch) -> None:
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
    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module.time, "time", lambda: 200.0)
    await reconciler.reconcile_once()

    assert incident_service.events == []


@pytest.mark.asyncio
async def test_reconciler_emits_scraper_runtime_failure(monkeypatch) -> None:
    incident_service = _FakeIncidentService()
    redis = _FakeRedis()
    redis.values = {
        "scraper:runtime_status:tradingview:fetch_tv_indices": ScraperRuntimeStatus(
            worker_name="tradingview",
            provider="tradingview",
            job_name="fetch_tv_indices",
            status="failed",
            updated_at=100.0,
            last_started_at=90.0,
            last_finished_at=100.0,
            consecutive_failures=2,
            last_error="TradingView index refresh degraded",
        ).model_dump_json(),
    }
    reconciler = AlertFreshnessReconciler(
        redis_client=redis,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        interval_seconds=1,
    )
    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module.time, "time", lambda: 200.0)
    await reconciler.reconcile_once()

    assert any(
        event.title == "Scraper runtime failed for fetch_tv_indices"
        for event, _ in incident_service.events
    )


@pytest.mark.asyncio
async def test_reconciler_emits_health_recovery_for_open_incident(monkeypatch) -> None:
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
    reconciler._probe_health_check = _healthy

    import apps.alert_app.runtime.reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module.time, "time", lambda: 200.0)
    await reconciler.reconcile_once()

    assert [event.event_type.value for event, _ in incident_service.events] == [
        "recovery"
    ]
