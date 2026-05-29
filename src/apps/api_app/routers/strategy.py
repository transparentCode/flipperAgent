"""Strategy observability router."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/strategy", tags=["strategy"])

config_manager = ConfigManager()


@router.get("/latest", summary="Latest trade signal per asset/timeframe")
async def strategy_latest() -> dict[str, Any]:
    """Return the most recently published TradeSignal for every configured
    asset/timeframe pair, plus a staleness indicator.

    Reads the tail of ``signals:{asset}:{tf}`` streams via XREVRANGE LIMIT 1.
    Creates a short-lived Valkey connection per request — suitable for low-frequency
    operational polling (not a hot path).

    Response shape per pair::

        {
          "BTCUSDT:1h": {
            "stream": "signals:BTCUSDT:1h",
            "message_id": "1234567890123-0",
            "timestamp": 1717000000.0,
            "lag_ms": 3200,
            "status": "ok",
            "direction": 1,
            "conviction": 0.82,
            "price": 67450.5,
            "model_name": "SqueezeBreakout",
            "idempotency_key": "a3f1b2c4d5e6f789",
            "metadata": {
              "selection_rank": 1,
              "selection_score": 0.72,
              "selection_penalties": {},
              ...
            }
          }
        }

    ``status`` values:

    - ``ok`` — signal found, data valid
    - ``no_data`` — stream exists but no signal published yet (e.g. all flat bars)
    - ``error`` — unexpected Valkey error
    """
    pairs = discover_pairs(config_manager)
    now_ms = int(time.time() * 1000)

    valkey_client = await create_valkey_client(config_manager)
    try:
        result: dict[str, Any] = {}
        for asset, tf in pairs:
            key = f"{asset}:{tf}"
            stream = f"signals:{asset}:{tf}"
            entry: dict[str, Any] = {"stream": stream, "status": "no_data"}

            try:
                messages = await valkey_client.xrevrange(stream, count=1)
                if messages:
                    message_id, data = messages[0]
                    decoded: dict[str, Any] = {}
                    for k, v in data.items():
                        k = k.decode() if isinstance(k, bytes) else k
                        v = v.decode() if isinstance(v, bytes) else v
                        # metadata is JSON-encoded by valkey_encode
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
                        "direction": decoded.get("direction"),
                        "conviction": decoded.get("conviction"),
                        "price": decoded.get("price"),
                        "model_name": decoded.get("model_name", ""),
                        "idempotency_key": decoded.get("idempotency_key", ""),
                        "metadata": decoded.get("metadata", {}),
                    }
                else:
                    entry["status"] = "no_data"
            except Exception as e:
                entry = {"stream": stream, "status": "error", "error": str(e)}

            result[key] = entry
    finally:
        await valkey_client.aclose()

    return result
