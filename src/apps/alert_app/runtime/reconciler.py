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
from apps.scraper_app.runtime_status import ScraperRuntimeStatus
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
        started_at: float | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.incident_service = incident_service
        self.notification_dispatcher = notification_dispatcher
        self.config_manager = create_alert_config_manager(config_manager)
        self.interval_seconds = interval_seconds
        self.started_at = time.time() if started_at is None else float(started_at)

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
        await self._reconcile_signal_statuses(now_ts, signal_threshold)
        await self._reconcile_strategy_statuses(now_ts, strategy_threshold)
        await self._reconcile_scraper_runtime_statuses(now_ts)
        await self._reconcile_scraper_jobs(now_ts)
        await self._reconcile_health_checks(now_ts)

    async def _reconcile_scraper_runtime_statuses(self, now_ts: float) -> None:
        running_timeout_seconds = float(
            self.config_manager.get("alerts.freshness.scraper.worker_running_timeout_seconds", 1200),
        )
        success_stale_threshold_seconds = float(
            self.config_manager.get("alerts.freshness.scraper.success_stale_threshold_seconds", 3600),
        )
        async for key, payload in self._iter_values("scraper:runtime_status:*"):
            try:
                status = ScraperRuntimeStatus.model_validate_json(payload)
            except Exception:
                continue
            last_started_at = status.last_started_at
            last_success_at = status.last_success_at
            last_finished_at = status.last_finished_at
            dedupe_key = f"scraper_runtime:{status.worker_name}:{status.job_name}"
            event: NormalizedAlertEvent | None = None

            if status.status == "failed":
                event = NormalizedAlertEvent(
                    event_id=f"scraper_runtime_failed:{status.worker_name}:{status.job_name}",
                    event_type=AlertEventType.SCRAPER_FAILURE,
                    source_app=AlertSourceApp.SCRAPER,
                    source_component=f"scraper_runtime:{status.job_name}",
                    severity=AlertSeverity.WARNING,
                    asset=None,
                    timeframe=None,
                    title=f"Scraper runtime failed for {status.job_name}",
                    summary=(
                        f"Scraper worker {status.worker_name}/{status.job_name} reported failure: "
                        f"{status.last_error or 'unknown error'}"
                    ),
                    detail={
                        "runtime_key": key,
                        "worker_name": status.worker_name,
                        "provider": status.provider,
                        "job_name": status.job_name,
                        "status": status.status,
                        "last_error": status.last_error,
                        "consecutive_failures": status.consecutive_failures,
                        "last_started_at": last_started_at,
                        "last_finished_at": last_finished_at,
                    },
                    dedupe_key=dedupe_key,
                    emitted_at=status.updated_at or now_ts,
                )
            elif last_started_at is not None and status.status == "running":
                running_age_seconds = now_ts - last_started_at
                if running_age_seconds > running_timeout_seconds:
                    event = NormalizedAlertEvent(
                        event_id=f"scraper_runtime_running_timeout:{status.worker_name}:{status.job_name}",
                        event_type=AlertEventType.SCRAPER_FAILURE,
                        source_app=AlertSourceApp.SCRAPER,
                        source_component=f"scraper_runtime:{status.job_name}",
                        severity=AlertSeverity.WARNING,
                        asset=None,
                        timeframe=None,
                        title=f"Scraper runtime delayed for {status.job_name}",
                        summary=(
                            f"Scraper worker {status.worker_name}/{status.job_name} has been running for "
                            f"{int(running_age_seconds)}s (threshold={int(running_timeout_seconds)}s)"
                        ),
                        detail={
                            "runtime_key": key,
                            "worker_name": status.worker_name,
                            "provider": status.provider,
                            "job_name": status.job_name,
                            "status": status.status,
                            "running_age_seconds": running_age_seconds,
                            "running_timeout_seconds": running_timeout_seconds,
                            "consecutive_failures": status.consecutive_failures,
                        },
                        dedupe_key=dedupe_key,
                        emitted_at=now_ts,
                    )
            elif last_success_at is not None:
                success_age_seconds = now_ts - last_success_at
                if success_age_seconds > success_stale_threshold_seconds:
                    event = NormalizedAlertEvent(
                        event_id=f"scraper_runtime_stale:{status.worker_name}:{status.job_name}",
                        event_type=AlertEventType.SCRAPER_FAILURE,
                        source_app=AlertSourceApp.SCRAPER,
                        source_component=f"scraper_runtime:{status.job_name}",
                        severity=AlertSeverity.WARNING,
                        asset=None,
                        timeframe=None,
                        title=f"Scraper output stale for {status.job_name}",
                        summary=(
                            f"Scraper worker {status.worker_name}/{status.job_name} has not reported a success for "
                            f"{int(success_age_seconds)}s (threshold={int(success_stale_threshold_seconds)}s)"
                        ),
                        detail={
                            "runtime_key": key,
                            "worker_name": status.worker_name,
                            "provider": status.provider,
                            "job_name": status.job_name,
                            "status": status.status,
                            "success_age_seconds": success_age_seconds,
                            "success_stale_threshold_seconds": success_stale_threshold_seconds,
                            "last_error": status.last_error,
                            "consecutive_failures": status.consecutive_failures,
                        },
                        dedupe_key=dedupe_key,
                        emitted_at=now_ts,
                    )

            if event is None:
                existing = await self.incident_service.incident_for_dedupe(dedupe_key)
                if (
                    existing is None
                    or existing.state == AlertIncidentState.RESOLVED
                    or last_success_at is None
                ):
                    continue
                recovery_age_seconds = now_ts - last_success_at
                if status.status == "succeeded" and recovery_age_seconds <= success_stale_threshold_seconds:
                    event = NormalizedAlertEvent(
                        event_id=f"scraper_runtime_recovery:{status.worker_name}:{status.job_name}",
                        event_type=AlertEventType.RECOVERY,
                        source_app=AlertSourceApp.SCRAPER,
                        source_component=f"scraper_runtime:{status.job_name}",
                        severity=AlertSeverity.INFO,
                        asset=None,
                        timeframe=None,
                        title=f"Scraper runtime recovered for {status.job_name}",
                        summary=(
                            f"Scraper worker {status.worker_name}/{status.job_name} last succeeded "
                            f"{int(recovery_age_seconds)}s ago"
                        ),
                        detail={
                            "runtime_key": key,
                            "worker_name": status.worker_name,
                            "provider": status.provider,
                            "job_name": status.job_name,
                            "status": status.status,
                            "last_success_at": last_success_at,
                        },
                        dedupe_key=f"scraper_runtime_recovery:{status.worker_name}:{status.job_name}",
                        recovery_key=dedupe_key,
                        emitted_at=now_ts,
                    )
            if event is None:
                continue
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
                provider = record.request.provider.value
                dataset = record.request.dataset.value
                target_ref = _scraper_target_ref(record)
                event = NormalizedAlertEvent(
                    event_id=f"scraper_failed:{record.job_id}",
                    event_type=AlertEventType.SCRAPER_FAILURE,
                    source_app=AlertSourceApp.SCRAPER,
                    source_component="scraper_job",
                    severity=AlertSeverity.WARNING,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Scraper job failed for {target_ref}",
                    summary=(
                        f"Async scraper job {provider}/{dataset} for {target_ref} failed: "
                        f"{record.error or 'unknown error'}"
                    ),
                    detail={
                        "job_id": record.job_id,
                        "provider": provider,
                        "dataset": dataset,
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
                provider = record.request.provider.value
                dataset = record.request.dataset.value
                target_ref = _scraper_target_ref(record)
                event = NormalizedAlertEvent(
                    event_id=f"scraper_recovery:{record.job_id}",
                    event_type=AlertEventType.RECOVERY,
                    source_app=AlertSourceApp.SCRAPER,
                    source_component="scraper_job",
                    severity=AlertSeverity.INFO,
                    asset=asset,
                    timeframe=timeframe,
                    title=f"Scraper job recovered for {target_ref}",
                    summary=(
                        f"Async scraper job {provider}/{dataset} for {target_ref} "
                        f"is now {record.status.value}"
                    ),
                    detail={
                        "job_id": record.job_id,
                        "provider": provider,
                        "dataset": dataset,
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
            existing = await self.incident_service.incident_for_dedupe(dedupe_key)
            startup_grace_seconds = max(
                float(raw_config.get("startup_grace_seconds", 0) or 0),
                0.0,
            )
            if (
                startup_grace_seconds > 0
                and now_ts - self.started_at < startup_grace_seconds
                and (existing is None or existing.state == AlertIncidentState.RESOLVED)
            ):
                continue
            result = await self._probe_health_check(raw_config)
            if result["healthy"]:
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
                title, summary = _health_breach_message(
                    name=name,
                    url=url,
                    result=result,
                )
                event = NormalizedAlertEvent(
                    event_id=f"health_breach:{name}",
                    event_type=AlertEventType.SYSTEM_HEALTH_BREACH,
                    source_app=_source_app_from_value(raw_config.get("source_app")),
                    source_component=f"health_check:{name}",
                    severity=severity,
                    asset=None,
                    timeframe=None,
                    title=title,
                    summary=summary,
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


def _health_breach_message(
    *,
    name: str,
    url: str,
    result: dict[str, Any],
) -> tuple[str, str]:
    status = str(result.get("status") or "").strip().lower()
    http_status = result.get("http_status")
    if status == "request_failed" and http_status is None:
        return (
            f"Health probe failed for {name}",
            f"No HTTP response from {url}. Service may still be starting or unreachable.",
        )
    if http_status is None:
        return (
            f"Health degraded for {name}",
            f"Health check at {url} failed before a response was returned.",
        )
    return (
        f"Health degraded for {name}",
        f"Health check at {url} returned HTTP {http_status} with status {status or 'unknown'}.",
    )


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


def _scraper_target_ref(record: ScrapeJobRecord) -> str:
    asset = _scraper_asset(record)
    timeframe = str(record.request.timeframe or "").strip()
    if asset and timeframe:
        return f"{asset} {timeframe}"
    if asset:
        return asset
    provider = str(record.request.provider.value).strip()
    dataset = str(record.request.dataset.value).strip()
    return f"{provider}/{dataset}"


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
