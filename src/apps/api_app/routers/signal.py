"""Signal observability router."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/signal", tags=["signal"])

config_manager = ConfigManager()


@router.get("/latest", summary="Latest feature vector per asset/timeframe")
async def signal_latest() -> dict[str, Any]:
    """Return the most recently published FeatureVector for every configured
    asset/timeframe pair, plus a staleness flag.

    Reads the tail of ``features:{asset}:{tf}`` streams via XREVRANGE LIMIT 1.
    Creates a short-lived Valkey connection per request — suitable for low-frequency
    operational polling (not a hot path).
    """
    pairs = discover_pairs(config_manager)
    now_ms = int(time.time() * 1000)

    valkey_client = await create_valkey_client(config_manager)
    try:
        result: dict[str, Any] = {}
        for asset, tf in pairs:
            key = f"{asset}:{tf}"
            stream = f"features:{asset}:{tf}"
            entry: dict[str, Any] = {"stream": stream, "status": "no_data"}

            try:
                messages = await valkey_client.xrevrange(stream, count=1)
                if messages:
                    message_id, data = messages[0]
                    # Decode bytes keys/values from Valkey
                    decoded: dict[str, Any] = {}
                    for k, v in data.items():
                        k = k.decode() if isinstance(k, bytes) else k
                        v = v.decode() if isinstance(v, bytes) else v
                        # Attempt JSON parse for nested fields (features, bar_data)
                        try:
                            decoded[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            decoded[k] = v

                    ts = decoded.get("timestamp")
                    try:
                        ts_ms = float(ts) * 1000 if ts and float(ts) < 1e12 else float(ts)
                        lag_ms = now_ms - int(ts_ms)
                    except (TypeError, ValueError):
                        lag_ms = None

                    entry = {
                        "stream": stream,
                        "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
                        "timestamp": ts,
                        "lag_ms": lag_ms,
                        "status": "ok",
                        "features": decoded.get("features", {}),
                        "bar_data": decoded.get("bar_data", {}),
                    }
                else:
                    entry["status"] = "no_data"
            except Exception as e:
                entry = {"stream": stream, "status": "error", "error": str(e)}

            result[key] = entry
    finally:
        await valkey_client.aclose()

    return result
