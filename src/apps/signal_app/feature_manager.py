from typing import Dict, Any, List, Sequence, Tuple, get_type_hints

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES
from libs.common.logging.logger_utils import bind_logger
import libs.features.indicators
from libs.features.indicators.registry import IndicatorRegistry
from libs.features.indicators.base import Indicator
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)

KEY_FEATURES = "features"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"

TYPE_HINT_FULL_CANDLE = "float, float, float, float, float"
TYPE_HINT_HLC_CANDLE = "float, float, float"

class FeatureManager:
    def __init__(self, asset: str, timeframe: str, db_fetcher=None):
        self.asset = asset
        self.timeframe = timeframe
        self.db_fetcher = db_fetcher
        self.config_mgr = ConfigManager()
        self.config_mgr.register_file(CONFIG_FILE_FEATURES)
        self._indicator_entries: list[tuple[str, Indicator]] = []
        self._initialize_indicators()

    @property
    def indicators(self) -> list[Indicator]:
        return [ind for _, ind in self._indicator_entries]
        
    async def fetch_historical_db_records(self, max_lookback: int) -> Sequence[Tuple[float, float, float, float, float]]:
        """
        Mock DB historical fetch injected dependency or default stub.
        In reality, this queries TimescaleDB to get the last `max_lookback` bars before accepting live updates.
        """
        if self.db_fetcher:
            return await self.db_fetcher(self.asset, self.timeframe, max_lookback)
        logger.info(f"Fetching {max_lookback} historical records for prime from stubbed DB...")
        return []

    def _initialize_indicators(self):
        try:
            features_config = self.config_mgr.get(KEY_FEATURES, {})
            assets_config = features_config.get(KEY_ASSETS, {})
            
            asset_node = assets_config.get(self.asset, assets_config.get(KEY_DEFAULT, {}))
            timeframes_config = asset_node.get(KEY_TIMEFRAMES, {})
            
            timeframe_node = timeframes_config.get(self.timeframe, timeframes_config.get(KEY_DEFAULT, {}))
        except Exception as e:
            logger.error(f"Error reading indicator config: {e}", exc_info=True)
            return

        for config_key, params in timeframe_node.items():
            try:
                if isinstance(params, dict) and "type" in params:
                    indicator_type = params["type"]
                    output_key = config_key
                    constructor_params = {k: v for k, v in params.items() if k != "type"}
                else:
                    indicator_type = config_key
                    output_key = config_key
                    constructor_params = params if isinstance(params, dict) else {}

                indicator_class = IndicatorRegistry.get(indicator_type)
                indicator = indicator_class(**constructor_params)
                self._indicator_entries.append((output_key, indicator))
                logger.info(f"Initialized indicator {indicator_type} as '{output_key}' for {self.asset} {self.timeframe}")
            except KeyError:
                logger.warning(f"Indicator type for '{config_key}' not found in registry. Skipping.")
            except Exception as e:
                logger.error(f"Error instantiating '{config_key}': {e}", exc_info=True)

    def _get_mapped_input(self, ind: Indicator, data: Tuple[float, float, float, float, float, float]) -> Any:
        hints = get_type_hints(ind.update)
        new_value_type = hints.get("new_value")
        # Heuristics based on type
        if new_value_type is float:
            return data[3]  # close
        
        # Disambiguate by counting commas in the type string
        type_str = str(new_value_type)
        comma_count = type_str.count(",")
        if comma_count >= 4:  # 5+ floats = full candle (open, high, low, close, volume)
            return data[:5]
        elif comma_count >= 2:  # 3 floats = HLC candle
            return (data[1], data[2], data[3])
            
        # fallback to close if undetermined, or just pass full data
        return data[3]

    def _get_mapped_historical_inputs(self, ind: Indicator, historical_data: Sequence[Tuple[float, float, float, float, float, float]]) -> List[Any]:
        # Maps the entire sequence
        return [self._get_mapped_input(ind, d) for d in historical_data]

    def prime(self, historical_data: Sequence[Tuple[float, float, float, float, float, float]]) -> None:
        """
        Pre-warms the live internal state.
        historical_data: list of (open, high, low, close, volume, timestamp)
        """
        for output_key, ind in self._indicator_entries:
            try:
                mapped_data = self._get_mapped_historical_inputs(ind, historical_data)
                ind.prime(mapped_data)
                logger.info(f"Primed indicator '{output_key}'")
            except Exception as e:
                logger.error(f"Error priming '{output_key}': {e}")
                ind._is_primed = False

    def process_tick(self, data: Tuple[float, float, float, float, float, float]) -> Dict[str, Any]:
        """
        Accepts incoming (open, high, low, close, volume, timestamp) tuple.
        """
        results = {}
        for output_key, ind in self._indicator_entries:
            if not ind.is_primed:
                logger.warning(f"Indicator '{output_key}' is not primed. Skipping update.")
                continue

            try:
                mapped_input = self._get_mapped_input(ind, data)
                res = ind.update(mapped_input)
                results[output_key] = res
            except Exception as e:
                logger.error(f"Indicator '{output_key}' failed during update: {e}. Un-priming.", exc_info=True)
                ind._is_primed = False
        return results
