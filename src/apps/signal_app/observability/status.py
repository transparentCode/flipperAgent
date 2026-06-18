from __future__ import annotations

import json
import time
from typing import Any

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.models import SignalPairState, SignalRuntimeStatus
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.publishing.streams import feature_stream_key


class SignalObservabilityService:
    def __init__(self, redis_client: Any, catalog: SignalPairCatalog) -> None:
        self.redis_client = redis_client
        self.catalog = catalog
        self.state_store = SignalRuntimeStateStore(redis_client)

    async def latest_features(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        latest: dict[str, Any] = {}

        for pair in self.catalog.list_pairs():
            stream = feature_stream_key(
                pair.asset,
                pair.timeframe,
                trigger_timeframe=pair.trigger_timeframe,
            )
            latest[pair.key] = await self._latest_stream_entry(stream, now_ms)
        return latest

    async def status(self) -> dict[str, SignalRuntimeStatus]:
        latest = await self.latest_features()
        result: dict[str, SignalRuntimeStatus] = {}
        for pair in self.catalog.list_pairs():
            entry = latest.get(pair.key, {})
            stored = await self.state_store.read(pair)
            if stored is None:
                result[pair.key] = SignalRuntimeStatus(
                    pair=pair,
                    state=_infer_state_from_latest(entry),
                    last_feature_ts=_coerce_float(entry.get("timestamp")),
                    lag_ms=entry.get("lag_ms") if isinstance(entry.get("lag_ms"), int) else None,
                    detail={"latest_status": entry.get("status", "unknown")},
                )
                continue

            merged_detail = dict(stored.detail)
            merged_detail["latest_status"] = entry.get("status", "unknown")
            result[pair.key] = stored.model_copy(
                update={
                    "last_feature_ts": stored.last_feature_ts or _coerce_float(entry.get("timestamp")),
                    "lag_ms": (
                        entry.get("lag_ms")
                        if isinstance(entry.get("lag_ms"), int)
                        else stored.lag_ms
                    ),
                    "detail": merged_detail,
                }
            )
        return result

    async def _latest_stream_entry(self, stream: str, now_ms: int) -> dict[str, Any]:
        if self.redis_client is None:
            return {"stream": stream, "status": "unavailable"}

        try:
            messages = await self.redis_client.xrevrange(stream, count=1)
        except Exception as exc:
            return {"stream": stream, "status": "error", "error": str(exc)}

        if not messages:
            return {"stream": stream, "status": "no_data"}

        message_id, payload = messages[0]
        decoded = _decode_stream_payload(payload)
        timestamp = decoded.get("timestamp")
        lag_ms = _compute_lag_ms(timestamp, now_ms)
        return {
            "stream": stream,
            "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
            "timestamp": timestamp,
            "lag_ms": lag_ms,
            "status": "ok",
            "features": decoded.get("features", {}),
            "bar_data": decoded.get("bar_data", {}),
        }


def _decode_stream_payload(payload: dict[Any, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in payload.items():
        decoded_key = key.decode() if isinstance(key, bytes) else str(key)
        decoded_value = value.decode() if isinstance(value, bytes) else value
        if isinstance(decoded_value, str):
            try:
                decoded[decoded_key] = json.loads(decoded_value)
            except json.JSONDecodeError:
                decoded[decoded_key] = decoded_value
        else:
            decoded[decoded_key] = decoded_value
    return decoded


def _compute_lag_ms(timestamp: Any, now_ms: int) -> int | None:
    ts = _coerce_float(timestamp)
    if ts is None:
        return None
    ts_ms = ts * 1000 if ts < 1e12 else ts
    return now_ms - int(ts_ms)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_state_from_latest(entry: dict[str, Any]) -> SignalPairState:
    status = entry.get("status")
    if status == "ok":
        return SignalPairState.LIVE
    if status == "error":
        return SignalPairState.FAILED
    return SignalPairState.WARMING
