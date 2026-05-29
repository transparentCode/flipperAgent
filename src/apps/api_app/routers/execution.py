"""Execution observability router."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/execution", tags=["execution"])

config_manager = ConfigManager()


@router.get("/fills", summary="Latest fill report per asset")
async def execution_fills() -> dict[str, Any]:
    """Return the most recently published ``ExecutionReport`` for every
    configured asset, plus a staleness indicator.

    Reads the tail of ``fills:{asset}`` streams via XREVRANGE LIMIT 1.
    Creates a short-lived Valkey connection per request — suitable for
    low-frequency operational polling (not a hot path).

    Response shape per asset::

        {
          "BTCUSDT": {
            "stream": "fills:BTCUSDT",
            "message_id": "1234567890123-0",
            "timestamp": 1717000000.0,
            "lag_ms": 800,
            "status": "ok",
            "order_id": "a1b2c3d4e5f6",
            "side": "buy",
            "requested_size": 0.012345,
            "filled_size": 0.012345,
            "requested_price": 67450.5,
            "average_fill_price": 67453.9,
            "fill_status": "filled",
            "slippage_bps": 0.50,
            "stop_loss_price": 65800.0,
            "take_profit_price": 69200.0,
            "idempotency_key": "abc123...",
            "error_message": null
          }
        }

    ``status`` values:

    - ``ok`` — fill found, data valid
    - ``no_data`` — stream exists but no fill has been published yet
    - ``error`` — unexpected Valkey error
    """
    pairs = discover_pairs(config_manager)
    # Execution operates per-asset — deduplicate while preserving order
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
            stream = f"fills:{asset}"
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
                        "order_id": decoded.get("order_id"),
                        "side": decoded.get("side"),
                        "requested_size": decoded.get("requested_size"),
                        "filled_size": decoded.get("filled_size"),
                        "requested_price": decoded.get("requested_price"),
                        "average_fill_price": decoded.get("average_fill_price"),
                        "fill_status": decoded.get("status"),
                        "slippage_bps": decoded.get("slippage_bps"),
                        "stop_loss_price": decoded.get("stop_loss_price"),
                        "take_profit_price": decoded.get("take_profit_price"),
                        "idempotency_key": decoded.get("idempotency_key"),
                        "error_message": decoded.get("error_message"),
                    }
                else:
                    entry["status"] = "no_data"
            except Exception as e:
                entry = {"stream": stream, "status": "error", "error": str(e)}

            result[asset] = entry
    finally:
        await valkey_client.aclose()

    return result
