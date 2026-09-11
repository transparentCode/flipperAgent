from __future__ import annotations

from collections.abc import Sequence
from typing import Any, get_type_hints

import pandas as pd

import libs.features.indicators  # noqa: F401
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

KEY_FEATURES = "features"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"
MICROSTRUCTURE_INDICATORS = {"KyleLambda", "TFI", "VPIN"}

BarTuple = tuple[float, ...]


class RawIndicatorPipeline:
    """Stateful raw indicator pipeline for one asset/timeframe pair."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.config_manager = config_manager or ConfigManager()
        self.config_manager.register_file(CONFIG_FILE_FEATURES)
        self._indicator_entries: list[tuple[str, Indicator]] = []
        self._initialize_indicators()

    @property
    def indicators(self) -> list[Indicator]:
        return [indicator for _, indicator in self._indicator_entries]

    def get_unprimed_indicator_keys(self) -> list[str]:
        return [
            output_key
            for output_key, indicator in self._indicator_entries
            if not indicator.is_primed
        ]

    def prime(self, historical_data: Sequence[BarTuple]) -> None:
        for output_key, indicator in self._indicator_entries:
            mapped_data: list[Any] = []
            try:
                mapped_data = self._get_mapped_historical_inputs(
                    indicator, historical_data
                )
                indicator.prime(mapped_data)
                logger.info("Primed indicator '%s'", output_key)
            except Exception as exc:
                if _is_expected_priming_shortfall(indicator, mapped_data, exc):
                    logger.warning(
                        "Indicator '%s' awaiting more history to prime: have %s bars, need %s.",
                        output_key,
                        len(mapped_data),
                        int(indicator.lookback_required),
                    )
                else:
                    logger.exception("Error priming '%s'", output_key)
                indicator._is_primed = False

    def process_tick(self, data: BarTuple) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for output_key, indicator in self._indicator_entries:
            if not indicator.is_primed:
                logger.warning(
                    "Indicator '%s' is not primed. Skipping update.", output_key
                )
                continue

            try:
                mapped_input = self._get_mapped_input(indicator, data)
                output = indicator.update(mapped_input)
                results[output_key] = output
                _flatten_microstructure_outputs(results, indicator, output)
            except Exception:
                logger.exception(
                    "Indicator '%s' failed during update. Un-priming.",
                    output_key,
                )
                indicator._is_primed = False
        return results

    def snapshot_features(self, historical_data: Sequence[BarTuple]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for output_key, indicator in self._indicator_entries:
            if not indicator.is_primed:
                continue

            try:
                mapped_data = self._get_mapped_historical_inputs(
                    indicator, historical_data
                )
                if not mapped_data:
                    continue
                batch_input = (
                    pd.DataFrame(mapped_data)
                    if isinstance(mapped_data[0], dict)
                    else mapped_data
                )
                batch_results = indicator.batch(batch_input)
                if not batch_results:
                    continue
                output = self._extract_latest_batch_output(batch_results)
                results[output_key] = output
                _flatten_microstructure_outputs(results, indicator, output)
            except Exception:
                logger.exception(
                    "Indicator '%s' failed during snapshot.",
                    output_key,
                )
        return results

    def _initialize_indicators(self) -> None:
        try:
            features_config = self.config_manager.get(KEY_FEATURES, {})
            assets_config = features_config.get(KEY_ASSETS, {})
            asset_node = assets_config.get(
                self.asset, assets_config.get(KEY_DEFAULT, {})
            )
            timeframes_config = asset_node.get(KEY_TIMEFRAMES, {})
            timeframe_node = timeframes_config.get(
                self.timeframe,
                timeframes_config.get(KEY_DEFAULT, {}),
            )
        except Exception:
            logger.exception("Error reading indicator config")
            return

        for config_key, params in timeframe_node.items():
            try:
                indicator_type, output_key, constructor_params = (
                    _resolve_indicator_config(config_key, params)
                )
                indicator_class = IndicatorRegistry.get(indicator_type)
                indicator = indicator_class(**constructor_params)
                self._indicator_entries.append((output_key, indicator))
                logger.info(
                    "Initialized indicator %s as '%s' for %s %s",
                    indicator_type,
                    output_key,
                    self.asset,
                    self.timeframe,
                )
            except KeyError:
                logger.warning(
                    "Indicator type for '%s' not found in registry. Skipping.",
                    config_key,
                )
            except Exception:
                logger.exception("Error instantiating '%s'", config_key)

    def _get_mapped_input(self, indicator: Indicator, data: BarTuple) -> Any:
        hints = get_type_hints(indicator.update)
        new_value_type = hints.get("new_value")
        type_str = str(new_value_type)

        if "dict" in type_str:
            return {
                "open": data[0],
                "high": data[1],
                "low": data[2],
                "close": data[3],
                "volume": data[4],
                "taker_buy_base": data[6] if len(data) > 6 else 0.0,
            }

        if new_value_type is float:
            return data[3]

        comma_count = type_str.count(",")
        if comma_count >= 4:
            return data[1:6]
        if comma_count >= 3:
            return (data[1], data[2], data[3], data[4])
        if comma_count >= 2:
            return (data[1], data[2], data[3])
        return data[3]

    def _get_mapped_historical_inputs(
        self,
        indicator: Indicator,
        historical_data: Sequence[BarTuple],
    ) -> list[Any]:
        return [self._get_mapped_input(indicator, data) for data in historical_data]

    def _extract_latest_batch_output(self, batch_output: Any) -> Any:
        if isinstance(batch_output, dict):
            return {
                key: self._extract_latest_batch_output(value)
                for key, value in batch_output.items()
            }
        if isinstance(batch_output, (str, bytes)):
            return batch_output
        try:
            return batch_output[-1]
        except (TypeError, KeyError, IndexError):
            return batch_output


def _resolve_indicator_config(
    config_key: str, params: Any
) -> tuple[str, str, dict[str, Any]]:
    if isinstance(params, dict) and "type" in params:
        indicator_type = str(params["type"])
        output_key = config_key
        constructor_params = {
            key: value for key, value in params.items() if key != "type"
        }
        return indicator_type, output_key, constructor_params

    indicator_type = config_key
    output_key = config_key
    constructor_params = params if isinstance(params, dict) else {}
    return indicator_type, output_key, constructor_params


def _flatten_microstructure_outputs(
    results: dict[str, Any],
    indicator: Indicator,
    output: Any,
) -> None:
    if (
        isinstance(output, dict)
        and indicator.__class__.__name__ in MICROSTRUCTURE_INDICATORS
    ):
        for nested_key, nested_value in output.items():
            results.setdefault(nested_key, nested_value)


def _is_expected_priming_shortfall(
    indicator: Indicator,
    mapped_data: Sequence[Any],
    exc: Exception,
) -> bool:
    if len(mapped_data) < int(indicator.lookback_required):
        return True
    return "requires at least" in str(exc).lower()
