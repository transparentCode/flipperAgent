import logging
from typing import Dict, Any, List, Sequence, Tuple, get_type_hints

from src.libs.common.config import ConfigManager
from src.libs.common.logging.logger_utils import bind_logger
import src.libs.features.indicators
from src.libs.features.indicators.registry import IndicatorRegistry
from src.libs.features.indicators.base import Indicator
from src.libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)

CONFIG_FILE_FEATURES = "configs/features.yaml"
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
        self.indicators: List[Indicator] = []
        self._initialize_indicators()
        
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

        for ind_name, params in timeframe_node.items():
            try:
                indicator_class = IndicatorRegistry.get(ind_name)
                indicator = indicator_class(**params)
                self.indicators.append(indicator)
                logger.info(f"Initialized indicator {ind_name} for {self.asset} {self.timeframe}")
            except KeyError:
                logger.warning(f"Indicator {ind_name} not found in registry. Skipping.")
            except Exception as e:
                logger.error(f"Error instantiating {ind_name}: {e}", exc_info=True)

    def _get_mapped_input(self, ind: Indicator, data: Tuple[float, float, float, float, float]) -> Any:
        hints = get_type_hints(ind.update)
        new_value_type = hints.get("new_value")
        # Heuristics based on type
        if new_value_type is float:
            return data[2]  # close
        
        # We can also check by string rep of type, or hardcode based on tuple size
        type_str = str(new_value_type)
        if TYPE_HINT_FULL_CANDLE in type_str:
            return data
        elif TYPE_HINT_HLC_CANDLE in type_str:
            return (data[0], data[1], data[2])
            
        # fallback to close if undetermined, or just pass full data
        return data[2]

    def _get_mapped_historical_inputs(self, ind: Indicator, historical_data: Sequence[Tuple[float, float, float, float, float]]) -> List[Any]:
        # Maps the entire sequence
        return [self._get_mapped_input(ind, d) for d in historical_data]

    def prime(self, historical_data: Sequence[Tuple[float, float, float, float, float]]) -> None:
        """
        Pre-warms the live internal state.
        historical_data: list of (high, low, close, volume, timestamp)
        """
        for ind in self.indicators:
            try:
                mapped_data = self._get_mapped_historical_inputs(ind, historical_data)
                ind.prime(mapped_data)
                logger.info(f"Primed indicator {ind.__class__.__name__}")
            except Exception as e:
                logger.error(f"Error priming {ind.__class__.__name__}: {e}")
                ind._is_primed = False

    def process_tick(self, data: Tuple[float, float, float, float, float]) -> Dict[str, Any]:
        """
        Accepts incoming (high, low, close, volume, timestamp) tuple.
        """
        results = {}
        for ind in self.indicators:
            if not ind.is_primed:
                logger.warning(f"Indicator {ind.__class__.__name__} is not primed. Skipping update.")
                continue
            
            try:
                mapped_input = self._get_mapped_input(ind, data)
                res = ind.update(mapped_input)
                results[ind.__class__.__name__] = res
            except Exception as e:
                logger.error(f"Indicator {ind.__class__.__name__} failed during update: {e}. Un-priming.", exc_info=True)
                ind._is_primed = False
        return results
