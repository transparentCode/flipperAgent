from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW
from libs.common.logging.logger_utils import bind_logger
from apps.signal_app.settings import SignalWorkerSettings

logger = bind_logger(__name__)

def resolve_tv_index_keys(config_manager: ConfigManager) -> list[str]:
    return list(SignalWorkerSettings.from_config(config_manager).enrichment_index_keys)


class ValkeySignalEnrichmentReader:
    def __init__(
        self,
        redis_client: Any,
        config_manager: ConfigManager | None = None,
        settings: SignalWorkerSettings | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.config_manager = config_manager or ConfigManager()
        self.config_manager.register_file(CONFIG_FILE_TRADINGVIEW)
        self.settings = settings or SignalWorkerSettings.from_config(self.config_manager)
        self.index_keys = list(self.settings.enrichment_index_keys)

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

    async def load_ltf_context_profiles(
        self,
        *,
        asset: str,
        base_timeframe: str = "1m",
        profiles: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        if self.redis_client is None or not profiles:
            return snapshots

        normalized_asset = str(asset).upper().strip()
        normalized_base = str(base_timeframe).strip() or "1m"
        for profile in profiles:
            normalized_profile = str(profile).strip()
            if not normalized_profile:
                continue
            try:
                raw = await self.redis_client.hgetall(
                    f"signal:ltf_context:{normalized_asset}:{normalized_base}:{normalized_profile}"
                )
                if raw:
                    snapshots[normalized_profile] = _parse_generic_snapshot(_decode_hash(raw))
            except Exception:
                logger.warning(
                    "Failed to fetch lower-timeframe context for %s/%s/%s",
                    normalized_asset,
                    normalized_base,
                    normalized_profile,
                    exc_info=True,
                )
        return snapshots


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


def _parse_generic_snapshot(decoded: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in decoded.items():
        try:
            parsed[key] = float(value)
        except (TypeError, ValueError):
            parsed[key] = value
    return parsed
