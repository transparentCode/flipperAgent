from __future__ import annotations

import json
import time
from typing import Any

from apps.execution_app.observability.runtime_state import ExecutionRuntimeStateStore
from apps.execution_app.state import ExecutionAsset, ExecutionAssetState, ExecutionRuntimeStatus


def fill_stream_key(asset: str) -> str:
    return f"fills:{asset.upper()}"


def failure_stream_key(asset: str) -> str:
    return f"execution:failures:{asset.upper()}"


class ExecutionObservabilityService:
    def __init__(self, redis_client: Any, assets: list[ExecutionAsset]) -> None:
        self.redis_client = redis_client
        self.assets = assets
        self.state_store = ExecutionRuntimeStateStore(redis_client)

    async def latest_fills(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        latest: dict[str, Any] = {}
        for asset in self.assets:
            latest[asset.key] = await self._latest_fill_entry(fill_stream_key(asset.asset), now_ms)
        return latest

    async def latest_failures(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        latest: dict[str, Any] = {}
        for asset in self.assets:
            latest[asset.key] = await self._latest_failure_entry(
                failure_stream_key(asset.asset),
                now_ms,
            )
        return latest

    async def summary(self) -> dict[str, Any]:
        latest_fills = await self.latest_fills()
        latest_failures = await self.latest_failures()
        status = await self._status_from_entries(latest_fills, latest_failures)
        return {
            "status": status,
            "fills": latest_fills,
            "failures": latest_failures,
        }

    async def status(self) -> dict[str, ExecutionRuntimeStatus]:
        latest_fills = await self.latest_fills()
        latest_failures = await self.latest_failures()
        return await self._status_from_entries(latest_fills, latest_failures)

    async def _status_from_entries(
        self,
        latest_fills: dict[str, Any],
        latest_failures: dict[str, Any],
    ) -> dict[str, ExecutionRuntimeStatus]:
        result: dict[str, ExecutionRuntimeStatus] = {}
        for asset in self.assets:
            fill_entry = latest_fills.get(asset.key, {})
            failure_entry = latest_failures.get(asset.key, {})
            stored = await self.state_store.read(asset)
            latest_fill_ts = _coerce_float(fill_entry.get("timestamp"))
            latest_failure_ts = _coerce_float(failure_entry.get("timestamp"))

            if stored is None:
                result[asset.key] = ExecutionRuntimeStatus(
                    asset=asset,
                    state=_infer_state(fill_entry, failure_entry),
                    last_fill_ts=latest_fill_ts,
                    last_failure_ts=latest_failure_ts,
                    last_error=failure_entry.get("error_message"),
                    detail={
                        "latest_fill_status": fill_entry.get("status", "unknown"),
                        "latest_failure_status": failure_entry.get("status", "unknown"),
                    },
                )
                continue

            merged_detail = dict(stored.detail)
            merged_detail["latest_fill_status"] = fill_entry.get("status", "unknown")
            merged_detail["latest_failure_status"] = failure_entry.get("status", "unknown")
            if failure_entry.get("message_id"):
                merged_detail["latest_failure_message_id"] = failure_entry.get("message_id")
            result[asset.key] = stored.model_copy(
                update={
                    "last_fill_ts": latest_fill_ts or stored.last_fill_ts,
                    "last_failure_ts": latest_failure_ts or stored.last_failure_ts,
                    "last_error": stored.last_error or failure_entry.get("error_message"),
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
        payload_status = decoded.pop("status", None)
        return {
            "stream": stream,
            "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
            "timestamp": timestamp,
            "lag_ms": lag_ms,
            "status": "ok",
            "payload_status": payload_status,
            **decoded,
        }

    async def _latest_fill_entry(self, stream: str, now_ms: int) -> dict[str, Any]:
        entry = await self._latest_stream_entry(stream, now_ms)
        if entry.get("status") != "ok" and entry.get("payload_status") != "ok":
            return entry
        return {
            "stream": entry.get("stream"),
            "message_id": entry.get("message_id"),
            "timestamp": entry.get("timestamp"),
            "lag_ms": entry.get("lag_ms"),
            "status": "ok",
            "order_id": entry.get("order_id"),
            "side": entry.get("side"),
            "requested_size": entry.get("requested_size"),
            "filled_size": entry.get("filled_size"),
            "requested_price": entry.get("requested_price"),
            "average_fill_price": entry.get("average_fill_price"),
            "fill_status": entry.get("payload_status") or entry.get("fill_status"),
            "slippage_bps": entry.get("slippage_bps"),
            "stop_loss_price": entry.get("stop_loss_price"),
            "take_profit_price": entry.get("take_profit_price"),
            "idempotency_key": entry.get("idempotency_key"),
            "error_message": entry.get("error_message"),
        }

    async def _latest_failure_entry(self, stream: str, now_ms: int) -> dict[str, Any]:
        entry = await self._latest_stream_entry(stream, now_ms)
        if entry.get("status") != "ok":
            return entry
        return {
            "stream": entry.get("stream"),
            "message_id": entry.get("message_id"),
            "timestamp": entry.get("timestamp"),
            "lag_ms": entry.get("lag_ms"),
            "status": "ok",
            "asset": entry.get("asset"),
            "consumer_group": entry.get("consumer_group"),
            "consumer_name": entry.get("consumer_name"),
            "idempotency_key": entry.get("idempotency_key"),
            "error_type": entry.get("error_type"),
            "error_message": entry.get("error_message"),
            "order_side": entry.get("order_side"),
            "order_size": entry.get("order_size"),
            "requested_price": entry.get("requested_price"),
            "order_type": entry.get("order_type"),
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


def _infer_state(fill_entry: dict[str, Any], failure_entry: dict[str, Any]) -> ExecutionAssetState:
    if failure_entry.get("status") == "ok":
        return ExecutionAssetState.FAILED
    if fill_entry.get("status") == "ok":
        return ExecutionAssetState.LIVE
    if fill_entry.get("status") == "error":
        return ExecutionAssetState.FAILED
    return ExecutionAssetState.WARMING
