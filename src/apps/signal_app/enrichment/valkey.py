from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__)

_DEFAULT_TV_INDICES = ["CRYPTOCAP:BTC.D", "CRYPTOCAP:TOTAL2", "CRYPTOCAP:TOTAL3"]


def resolve_tv_index_keys(config_manager: ConfigManager) -> list[str]:
    config_manager.register_file(CONFIG_FILE_TRADINGVIEW)
    configured = config_manager.get("tradingview.indices", _DEFAULT_TV_INDICES)
    if not isinstance(configured, list) or not configured:
        configured = _DEFAULT_TV_INDICES
    return [str(symbol).split(":")[-1] for symbol in configured]


class ValkeySignalEnrichmentReader:
    def __init__(
        self,
        redis_client: Any,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.config_manager = config_manager or ConfigManager()
        self.config_manager.register_file(CONFIG_FILE_TRADINGVIEW)
        self.index_keys = resolve_tv_index_keys(self.config_manager)

    async def load_index_data(self) -> dict[str, dict[str, Any]]:
        index_data: dict[str, dict[str, Any]] = {}
        if self.redis_client is None:
            return index_data

        for symbol in self.index_keys:
            try:
                raw = await self.redis_client.hgetall(f"index:latest:{symbol}")
                if raw:
                    parsed = _decode_hash(raw)
                    index_data[symbol] = _parse_numeric_snapshot(parsed)
            except Exception:
                logger.warning("Failed to fetch TV index data for %s", symbol, exc_info=True)
        return index_data

    async def load_derivatives_data(self) -> dict[str, float]:
        derivatives: dict[str, float] = {}
        if self.redis_client is None:
            return derivatives

        derivatives_config = self.config_manager.get("tradingview.derivatives", [])
        if not isinstance(derivatives_config, list):
            return derivatives

        assets = sorted(
            {
                str(entry.get("asset", "")).upper()
                for entry in derivatives_config
                if isinstance(entry, dict) and entry.get("asset")
            }
        )
        for asset in assets:
            for suffix, output_key in (("oi", "open_interest"), ("funding", "funding_rate")):
                try:
                    raw = await self.redis_client.hgetall(f"derivatives:latest:{asset}:{suffix}")
                    decoded = _decode_hash(raw)
                    value = decoded.get("value")
                    if value is not None:
                        derivatives[f"{asset}_{output_key}"] = float(value)
                except (TypeError, ValueError):
                    continue
                except Exception:
                    logger.warning("Failed to fetch derivatives data for %s/%s", asset, suffix, exc_info=True)
        return derivatives


def _decode_hash(raw: dict[Any, Any]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        decoded_key = key.decode() if isinstance(key, bytes) else str(key)
        decoded_value = value.decode() if isinstance(value, bytes) else str(value)
        decoded[decoded_key] = decoded_value
    return decoded


def _parse_numeric_snapshot(decoded: dict[str, str]) -> dict[str, Any]:
    numeric_fields = ("timestamp", "open", "high", "low", "close", "volume", "fetched_at")
    parsed: dict[str, Any] = {}
    for field in numeric_fields:
        if field in decoded:
            parsed[field] = float(decoded[field])
    for field in ("symbol", "timeframe"):
        if field in decoded:
            parsed[field] = decoded[field]
    return parsed

