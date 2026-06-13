from __future__ import annotations

from dataclasses import dataclass

from libs.common.config import ConfigManager


@dataclass(frozen=True)
class SignalWorkerSettings:
    consumer_group: str = "signal_app_group"
    consumer_name_prefix: str = "signal_worker"
    batch_size: int = 10
    block_ms: int = 1000
    priming_retry_delay_sec: float = 1.0
    warming_retry_delay_sec: float = 5.0

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | None = None,
    ) -> "SignalWorkerSettings":
        config_manager = config_manager or ConfigManager()
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
            batch_size=int(config_manager.get("signal.runtime.batch_size", cls.batch_size)),
            block_ms=int(config_manager.get("signal.runtime.block_ms", cls.block_ms)),
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
        )
