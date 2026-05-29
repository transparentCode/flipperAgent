"""Risk observability router."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/risk", tags=["risk"])

config_manager = ConfigManager()


@router.get("/latest", summary="Latest order request per asset")
async def risk_latest() -> dict[str, Any]:
    """Return the most recently published ``OrderExecutionRequest`` for every
    configured asset, plus a staleness indicator.

    Reads the tail of ``orders:{asset}`` streams via XREVRANGE LIMIT 1.
    Creates a short-lived Valkey connection per request — suitable for low-frequency
    operational polling (not a hot path).

    Response shape per asset::

        {
          "BTCUSDT": {
            "stream": "orders:BTCUSDT",
            "message_id": "1234567890123-0",
            "timestamp": 1717000000.0,
            "lag_ms": 1200,
            "status": "ok",
            "side": "buy",
            "size": 0.012345,
            "order_type": "market",
            "requested_price": 67450.5,
            "stop_loss_price": 65800.0,
            "take_profit_price": 69200.0,
            "model_name": "SqueezeBreakout",
            "source_timeframe": "1h",
            "idempotency_key": "abc123..."
          }
        }

    ``status`` values:

    - ``ok`` — order found, data valid
    - ``no_data`` — stream exists but no order has been published yet
    - ``error`` — unexpected Valkey error
    """
    pairs = discover_pairs(config_manager)
    # Risk operates per-asset — deduplicate while preserving order
    seen: set[str] = set()
    assets: list[str] = []
    for asset, _ in pairs:
        if asset not in seen:
            seen.add(asset)
            assets.append(asset)

    now_ms = int(time.time() * 1000)

    valkey_client = await create_valkey_client(config_manager)
    try:
        result: dict[str, Any] = {}
        for asset in assets:
            stream = f"orders:{asset}"
            entry: dict[str, Any] = {"stream": stream, "status": "no_data"}

            try:
                messages = await valkey_client.xrevrange(stream, count=1)
                if messages:
                    message_id, data = messages[0]
                    decoded: dict[str, Any] = {}
                    for k, v in data.items():
                        k = k.decode() if isinstance(k, bytes) else k
                        v = v.decode() if isinstance(v, bytes) else v
                        try:
                            decoded[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            decoded[k] = v

                    ts = decoded.get("timestamp")
                    try:
                        ts_float = float(ts)
                        ts_ms = ts_float * 1000 if ts_float < 1e12 else ts_float
                        lag_ms = now_ms - int(ts_ms)
                    except (TypeError, ValueError):
                        lag_ms = None

                    entry = {
                        "stream": stream,
                        "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
                        "timestamp": ts,
                        "lag_ms": lag_ms,
                        "status": "ok",
                        "side": decoded.get("side"),
                        "size": decoded.get("size"),
                        "order_type": decoded.get("order_type"),
                        "requested_price": decoded.get("requested_price"),
                        "stop_loss_price": decoded.get("stop_loss_price"),
                        "take_profit_price": decoded.get("take_profit_price"),
                        "model_name": decoded.get("model_name", ""),
                        "source_timeframe": decoded.get("source_timeframe", ""),
                        "idempotency_key": decoded.get("idempotency_key", ""),
                    }
                else:
                    entry["status"] = "no_data"
            except Exception as e:
                entry = {"stream": stream, "status": "error", "error": str(e)}

            result[asset] = entry
    finally:
        await valkey_client.aclose()

    return result
