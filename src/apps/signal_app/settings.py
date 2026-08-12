from __future__ import annotations

from dataclasses import dataclass

from apps.signal_app.ohlcv_source import (
    OhlcvSourceBinding,
    parse_ohlcv_source_bindings,
)
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW

DEFAULT_SIGNAL_TV_INDICES = (
    "CRYPTOCAP:BTC.D",
    "CRYPTOCAP:TOTAL2",
    "CRYPTOCAP:TOTAL3",
)


def _normalize_index_keys(symbols: object) -> tuple[str, ...]:
    if not isinstance(symbols, list) or not symbols:
        symbols = list(DEFAULT_SIGNAL_TV_INDICES)
    return tuple(str(symbol).split(":")[-1] for symbol in symbols)


@dataclass(frozen=True)
class SignalWorkerSettings:
    consumer_group: str = "signal_app_group"
    consumer_name_prefix: str = "signal_worker"
    batch_size: int = 10
    block_ms: int = 1000
    feature_stream_maxlen: int = 1000
    feature_stream_approximate: bool = True
    price_update_stream_maxlen: int = 200
    price_update_stream_approximate: bool = True
    ltf_context_ttl_seconds: int = 21_600
    priming_retry_delay_sec: float = 1.0
    warming_retry_delay_sec: float = 5.0
    enrichment_index_keys: tuple[str, ...] = ("BTC.D", "TOTAL2", "TOTAL3")
    regime_min_bars: int = 200
    regime_max_history: int = 2000
    regime_reeval_interval: int = 10
    ohlcv_sources: tuple[OhlcvSourceBinding, ...] = ()

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | None = None,
    ) -> SignalWorkerSettings:
        config_manager = config_manager or ConfigManager()
        config_manager.register_file(CONFIG_FILE_TRADINGVIEW)
        return cls(
            consumer_group=str(
                config_manager.get(
                    "signal.runtime.consumer_group",
                    cls.consumer_group,
                )
            ),
            consumer_name_prefix=str(
                config_manager.get(
                    "signal.runtime.consumer_name_prefix",
                    cls.consumer_name_prefix,
                )
            ),
            batch_size=int(
                config_manager.get("signal.runtime.batch_size", cls.batch_size)
            ),
            block_ms=int(config_manager.get("signal.runtime.block_ms", cls.block_ms)),
            feature_stream_maxlen=int(
                config_manager.get(
                    "signal.runtime.feature_stream_maxlen",
                    cls.feature_stream_maxlen,
                )
            ),
            feature_stream_approximate=bool(
                config_manager.get(
                    "signal.runtime.feature_stream_approximate",
                    cls.feature_stream_approximate,
                )
            ),
            price_update_stream_maxlen=int(
                config_manager.get(
                    "signal.runtime.price_update_stream_maxlen",
                    cls.price_update_stream_maxlen,
                )
            ),
            price_update_stream_approximate=bool(
                config_manager.get(
                    "signal.runtime.price_update_stream_approximate",
                    cls.price_update_stream_approximate,
                )
            ),
            ltf_context_ttl_seconds=int(
                config_manager.get(
                    "signal.runtime.ltf_context_ttl_seconds",
                    cls.ltf_context_ttl_seconds,
                )
            ),
            priming_retry_delay_sec=float(
                config_manager.get(
                    "signal.runtime.priming_retry_delay_sec",
                    cls.priming_retry_delay_sec,
                )
            ),
            warming_retry_delay_sec=float(
                config_manager.get(
                    "signal.runtime.warming_retry_delay_sec",
                    cls.warming_retry_delay_sec,
                )
            ),
            enrichment_index_keys=_normalize_index_keys(
                config_manager.get(
                    "tradingview.indices", list(DEFAULT_SIGNAL_TV_INDICES)
                )
            ),
            regime_min_bars=int(
                config_manager.get("signal.regime.min_bars", cls.regime_min_bars)
            ),
            regime_max_history=int(
                config_manager.get("signal.regime.max_history", cls.regime_max_history)
            ),
            regime_reeval_interval=int(
                config_manager.get(
                    "signal.regime.reeval_interval",
                    cls.regime_reeval_interval,
                )
            ),
            ohlcv_sources=parse_ohlcv_source_bindings(
                config_manager.get("signal.runtime.ohlcv_sources", {})
            ),
        )

    def source_binding(self, asset: str) -> OhlcvSourceBinding:
        """Return the explicit ingestion binding for an asset or fail closed."""
        normalized_asset = str(asset).strip().upper()
        for binding in self.ohlcv_sources:
            if binding.asset == normalized_asset:
                return binding
        raise ValueError(
            f"no explicit ingestion OHLCV source binding configured for {normalized_asset}"
        )
