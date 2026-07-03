from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp
from apps.alert_app.contracts import (
    AlertEventType,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
    NormalizedAlertEvent,
)
from apps.alert_app.incidents.service import AlertIncidentService
from apps.alert_app.notifications import AlertNotificationDispatcher
from apps.alert_app.rules import resolve_routes_for_event
from apps.alert_app.settings import create_alert_config_manager
from apps.scraper_app.core.models import ScrapeJobRecord, ScrapeJobStatus
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component="ALERTING")


class AlertFreshnessReconciler:
    def __init__(
        self,
        *,
        redis_client: Any,
        incident_service: AlertIncidentService,
        notification_dispatcher: AlertNotificationDispatcher | None = None,
        config_manager: Any | None = None,
        interval_seconds: float = 30.0,
    ) -> None:
        self.redis_client = redis_client
        self.incident_service = incident_service
        self.notification_dispatcher = notification_dispatcher
        self.config_manager = create_alert_config_manager(config_manager)
        self.interval_seconds = interval_seconds

    async def run(self) -> None:
        while True:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Alert freshness reconciler failed: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_seconds)

    async def reconcile_once(self) -> None:
        now_ts = time.time()
        signal_threshold = float(
            self.config_manager.get("alerts.freshness.signal.max_lag_seconds", 1200),
        )
        strategy_threshold = float(
            self.config_manager.get("alerts.freshness.strategy.max_lag_seconds", 1800),
        )
        ingestion_threshold = float(
            self.config_manager.get("alerts.freshness.ingestion.warming_timeout_seconds", 900),
        )
        await self._reconcile_ingestion_statuses(now_ts, ingestion_threshold)
        await self._reconcile_signal_statuses(now_ts, signal_threshold)
        await self._reconcile_strategy_statuses(now_ts, strategy_threshold)
        await self._reconcile_scraper_jobs(now_ts)
        await self._reconcile_health_checks(now_ts)

    async def _reconcile_ingestion_statuses(self, now_ts: float, threshold_seconds: float) -> None:
        async for key, payload in self._iter_hashes("ingestion:runtime_status:*"):
            asset = _asset_from_key(key).upper().strip()
            timeframe = _timeframe_from_key(key).strip()
            runtime_state = str(payload.get("runtime_state") or "").upper().strip()
            updated_at = _coerce_float(payload.get("updated_at"))
            if updated_at is None or not asset or not timeframe:
                continue
            dedupe_key = f"ingestion_transition:{asset}:{timeframe}"
            lag_seconds = now_ts - updated_at
            if runtime_state in {"WARMING", "BACKFILLING"} and lag_seconds > threshold_seconds:
                event = NormalizedAlertEvent(
                    event_id=f"ingestion_transition_timeout:{asset}:{timeframe}",
                    event_type=AlertEventType.INGESTION_RUNTIME_FAILURE,
                    source_app=AlertSourceApp.INGESTION,
                    source_component="ingestion_runtime",
                    severity=AlertSeverity.WARNING,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Ingestion transition timeout for {asset} {timeframe}",
                    summary=(
                        f"Ingestion lane {asset}/{timeframe} stuck in {runtime_state} for "
                        f"{int(lag_seconds)}s (threshold={int(threshold_seconds)}s)"
                    ),
                    detail={
                        "runtime_state": runtime_state,
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=now_ts,
                )
            else:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if existing is None or existing.state == AlertIncidentState.RESOLVED:
                    continue
                event = NormalizedAlertEvent(
                    event_id=f"ingestion_transition_recovery:{asset}:{timeframe}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=AlertSourceApp.INGESTION,
                    source_component="ingestion_runtime",
                    severity=AlertSeverity.INFO,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Ingestion transition recovered for {asset} {timeframe}",
                    summary=(
                        f"Ingestion lane {asset}/{timeframe} recovered to state "
                        f"{runtime_state or 'UNKNOWN'} with lag {int(lag_seconds)}s"
                    ),
                    detail={
                        "runtime_state": runtime_state,
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=f"ingestion_recovery:{asset}:{timeframe}",
                    recovery_key=dedupe_key,
                    emitted_at=now_ts,
                )
            routes = resolve_routes_for_event(event, config_manager=self.config_manager)
            incident, should_notify = await self.incident_service.record_event(
                event,
                route_names=routes,
            )
            if should_notify and self.notification_dispatcher is not None:
                await self.notification_dispatcher.enqueue_incident(
                    incident,
                    route_names=routes,
                )

    async def _reconcile_signal_statuses(self, now_ts: float, threshold_seconds: float) -> None:
        async for key, payload in self._iter_hashes("signal:status:*"):
            pair = _decode_embedded_json(payload.get("pair"))
            asset = str(pair.get("asset") or _asset_from_key(key)).upper().strip()
            timeframe = str(pair.get("timeframe") or _timeframe_from_key(key)).strip()
            last_feature_ts = _coerce_float(payload.get("last_feature_ts"))
            if last_feature_ts is None:
                continue
            dedupe_key = f"signal_freshness:{asset}:{timeframe}"
            lag_seconds = now_ts - last_feature_ts
            if lag_seconds > threshold_seconds:
                event = NormalizedAlertEvent(
                    event_id=f"signal_stale:{asset}:{timeframe}",
                    event_type=AlertEventType.SIGNAL_FRESHNESS_BREACH,
                    source_app=AlertSourceApp.SIGNAL,
                    source_component="signal_runtime",
                    severity=AlertSeverity.WARNING,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Signal freshness breach for {asset} {timeframe}",
                    summary=(
                        f"Signal lane {asset}/{timeframe} stale for {int(lag_seconds)}s "
                        f"(threshold={int(threshold_seconds)}s)"
                    ),
                    detail={
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=now_ts,
                )
            else:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if existing is None or existing.state == AlertIncidentState.RESOLVED:
                    continue
                event = NormalizedAlertEvent(
                    event_id=f"signal_recovery:{asset}:{timeframe}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=AlertSourceApp.SIGNAL,
                    source_component="signal_runtime",
                    severity=AlertSeverity.INFO,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Signal freshness recovered for {asset} {timeframe}",
                    summary=(
                        f"Signal lane {asset}/{timeframe} recovered with lag "
                        f"{int(lag_seconds)}s"
                    ),
                    detail={
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=f"signal_recovery:{asset}:{timeframe}",
                    recovery_key=dedupe_key,
                    emitted_at=now_ts,
                )
            routes = resolve_routes_for_event(event, config_manager=self.config_manager)
            incident, should_notify = await self.incident_service.record_event(
                event,
                route_names=routes,
            )
            if should_notify and self.notification_dispatcher is not None:
                await self.notification_dispatcher.enqueue_incident(
                    incident,
                    route_names=routes,
                )

    async def _reconcile_strategy_statuses(self, now_ts: float, threshold_seconds: float) -> None:
        async for key, payload in self._iter_hashes("strategy:status:*"):
            pair = _decode_embedded_json(payload.get("pair"))
            asset = str(pair.get("asset") or _asset_from_key(key)).upper().strip()
            timeframe = str(pair.get("timeframe") or _timeframe_from_key(key)).strip()
            last_signal_ts = _coerce_float(payload.get("last_signal_ts"))
            if last_signal_ts is None:
                continue
            dedupe_key = f"strategy_freshness:{asset}:{timeframe}"
            lag_seconds = now_ts - last_signal_ts
            if lag_seconds > threshold_seconds:
                event = NormalizedAlertEvent(
                    event_id=f"strategy_stale:{asset}:{timeframe}",
                    event_type=AlertEventType.STRATEGY_FRESHNESS_BREACH,
                    source_app=AlertSourceApp.STRATEGY,
                    source_component="strategy_runtime",
                    severity=AlertSeverity.WARNING,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Strategy freshness breach for {asset} {timeframe}",
                    summary=(
                        f"Strategy lane {asset}/{timeframe} stale for {int(lag_seconds)}s "
                        f"(threshold={int(threshold_seconds)}s)"
                    ),
                    detail={
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=now_ts,
                )
            else:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if existing is None or existing.state == AlertIncidentState.RESOLVED:
                    continue
                event = NormalizedAlertEvent(
                    event_id=f"strategy_recovery:{asset}:{timeframe}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=AlertSourceApp.STRATEGY,
                    source_component="strategy_runtime",
                    severity=AlertSeverity.INFO,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Strategy freshness recovered for {asset} {timeframe}",
                    summary=(
                        f"Strategy lane {asset}/{timeframe} recovered with lag "
                        f"{int(lag_seconds)}s"
                    ),
                    detail={
                        "lag_seconds": lag_seconds,
                        "threshold_seconds": threshold_seconds,
                        "runtime_key": key,
                    },
                    dedupe_key=f"strategy_recovery:{asset}:{timeframe}",
                    recovery_key=dedupe_key,
                    emitted_at=now_ts,
                )
            routes = resolve_routes_for_event(event, config_manager=self.config_manager)
            incident, should_notify = await self.incident_service.record_event(
                event,
                route_names=routes,
            )
            if should_notify and self.notification_dispatcher is not None:
                await self.notification_dispatcher.enqueue_incident(
                    incident,
                    route_names=routes,
                )

    async def _reconcile_scraper_jobs(self, now_ts: float) -> None:
        async for key, payload in self._iter_values("scraper:job:scrape-*"):
            if ":result:" in key:
                continue
            try:
                record = ScrapeJobRecord.model_validate_json(payload)
            except Exception:
                continue
            dedupe_key = f"scraper_job:{record.job_id}"
            asset = _scraper_asset(record)
            timeframe = str(record.request.timeframe or "").strip() or None
            if record.status == ScrapeJobStatus.FAILED:
                event = NormalizedAlertEvent(
                    event_id=f"scraper_failed:{record.job_id}",
                    event_type=AlertEventType.SCRAPER_FAILURE,
                    source_app=AlertSourceApp.SCRAPER,
                    source_component="scraper_job",
                    severity=AlertSeverity.WARNING,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Scraper job failed for {record.request.provider.value}",
                    summary=(
                        f"Scraper job {record.job_id} failed for "
                        f"{record.request.provider.value}/{record.request.dataset.value}"
                    ),
                    detail={
                        "job_id": record.job_id,
                        "provider": record.request.provider.value,
                        "dataset": record.request.dataset.value,
                        "intent": record.request.intent.value,
                        "priority": record.request.priority.value,
                        "updated_at": record.updated_at,
                        "error": record.error,
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=record.updated_at or now_ts,
                )
            else:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if existing is None or existing.state == AlertIncidentState.RESOLVED:
                    continue
                event = NormalizedAlertEvent(
                    event_id=f"scraper_recovery:{record.job_id}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=AlertSourceApp.SCRAPER,
                    source_component="scraper_job",
                    severity=AlertSeverity.INFO,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Scraper job recovered for {record.request.provider.value}",
                    summary=f"Scraper job {record.job_id} is now {record.status.value}",
                    detail={
                        "job_id": record.job_id,
                        "provider": record.request.provider.value,
                        "dataset": record.request.dataset.value,
                        "status": record.status.value,
                        "updated_at": record.updated_at,
                    },
                    dedupe_key=f"scraper_recovery:{record.job_id}",
                    recovery_key=dedupe_key,
                    emitted_at=record.updated_at or now_ts,
                )
            routes = resolve_routes_for_event(event, config_manager=self.config_manager)
            incident, should_notify = await self.incident_service.record_event(
                event,
                route_names=routes,
            )
            if should_notify and self.notification_dispatcher is not None:
                await self.notification_dispatcher.enqueue_incident(
                    incident,
                    route_names=routes,
                )

    async def _reconcile_health_checks(self, now_ts: float) -> None:
        checks = self.config_manager.get("alerts.health_checks", {}) or {}
        if not isinstance(checks, dict):
            return
        for name, raw_config in checks.items():
            if not isinstance(raw_config, dict) or not bool(raw_config.get("enabled", True)):
                continue
            url = str(raw_config.get("url", "")).strip()
            if not url:
                continue
            dedupe_key = f"health_check:{name}"
            result = await self._probe_health_check(raw_config)
            if result["healthy"]:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if existing is None or existing.state == AlertIncidentState.RESOLVED:
                    continue
                event = NormalizedAlertEvent(
                    event_id=f"health_recovery:{name}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=_source_app_from_value(raw_config.get("source_app")),
                    source_component=f"health_check:{name}",
                    severity=AlertSeverity.INFO,
                    asset=None,
                    timeframe=None,
                    title=f"Health recovered for {name}",
                    summary=f"Health check {name} recovered with status {result['status']}",
                    detail={
                        "url": url,
                        "http_status": result["http_status"],
                        "status": result["status"],
                    },
                    dedupe_key=f"health_recovery:{name}",
                    recovery_key=dedupe_key,
                    emitted_at=now_ts,
                )
            else:
                severity = AlertSeverity.WARNING
                if result["http_status"] is None or result["http_status"] >= 500:
                    severity = AlertSeverity.CRITICAL
                event = NormalizedAlertEvent(
                    event_id=f"health_breach:{name}",
                    event_type=AlertEventType.SYSTEM_HEALTH_BREACH,
                    source_app=_source_app_from_value(raw_config.get("source_app")),
                    source_component=f"health_check:{name}",
                    severity=severity,
                    asset=None,
                    timeframe=None,
                    title=f"Health degraded for {name}",
                    summary=(
                        f"Health check {name} unhealthy: status={result['status']} "
                        f"http_status={result['http_status']}"
                    ),
                    detail={
                        "url": url,
                        "http_status": result["http_status"],
                        "status": result["status"],
                        "error": result["error"],
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=now_ts,
                )
            routes = resolve_routes_for_event(event, config_manager=self.config_manager)
            incident, should_notify = await self.incident_service.record_event(
                event,
                route_names=routes,
            )
            if should_notify and self.notification_dispatcher is not None:
                await self.notification_dispatcher.enqueue_incident(
                    incident,
                    route_names=routes,
                )

    async def _iter_hashes(self, pattern: str):
        scan_iter = getattr(self.redis_client, "scan_iter", None)
        if callable(scan_iter):
            async for raw_key in scan_iter(match=pattern):
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                payload = dict(await self.redis_client.hgetall(key))
                if payload:
                    yield key, payload
            return
        for raw_key in await self.redis_client.keys(pattern):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
            payload = dict(await self.redis_client.hgetall(key))
            if payload:
                yield key, payload

    async def _iter_values(self, pattern: str):
        scan_iter = getattr(self.redis_client, "scan_iter", None)
        if callable(scan_iter):
            async for raw_key in scan_iter(match=pattern):
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                payload = await self.redis_client.get(key)
                if payload:
                    yield key, payload
            return
        for raw_key in await self.redis_client.keys(pattern):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
            payload = await self.redis_client.get(key)
            if payload:
                yield key, payload

    async def _probe_health_check(self, config: dict[str, Any]) -> dict[str, Any]:
        url = str(config.get("url", "")).strip()
        timeout_seconds = float(config.get("timeout_seconds", 5))
        healthy_statuses = {
            str(value).strip().lower()
            for value in config.get("healthy_statuses", ["ok"])
            if str(value).strip()
        }
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    http_status = int(response.status)
                    status_value = "http_error"
                    error = None
                    try:
                        payload = await response.json()
                        status_value = str(payload.get("status", status_value)).strip().lower()
                    except Exception:
                        payload = None
                        if 200 <= http_status < 300:
                            status_value = "ok"
                    healthy = 200 <= http_status < 300 and status_value in healthy_statuses
                    if not healthy and payload is None and 200 <= http_status < 300:
                        error = "missing_json_status"
                    return {
                        "healthy": healthy,
                        "http_status": http_status,
                        "status": status_value,
                        "error": error,
                    }
        except Exception as exc:
            return {
                "healthy": False,
                "http_status": None,
                "status": "request_failed",
                "error": str(exc),
            }


def _decode_embedded_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            return {}
    return {}


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _asset_from_key(key: str) -> str:
    parts = key.split(":")
    return parts[2] if len(parts) > 2 else ""


def _timeframe_from_key(key: str) -> str:
    parts = key.split(":")
    return parts[3].split("@")[0] if len(parts) > 3 else ""


def _scraper_asset(record: ScrapeJobRecord) -> str | None:
    for candidate in (
        record.request.short_name,
        record.request.symbol,
        record.request.coin,
    ):
        normalized = str(candidate or "").strip().upper()
        if normalized:
            return normalized
    return None


def _source_app_from_value(value: Any) -> AlertSourceApp:
    normalized = str(value or "").strip().lower()
    for candidate in (
        normalized,
        normalized.removesuffix("_app"),
        f"{normalized}_app" if normalized else "",
    ):
        try:
            return AlertSourceApp(candidate)
        except ValueError:
            continue
    return AlertSourceApp.SYSTEM
