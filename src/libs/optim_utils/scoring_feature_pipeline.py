"""Batch feature pipeline for scoring model optimization.

OHLCV DataFrame → indicators (FeatureManager) → engineered features
(EngineeredFeatureManager) → flat feature DataFrame suitable for
ScoringModel.batch_evaluate().
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from apps.signal_app.feature_manager import FeatureManager
from libs.features.engineered.manager import EngineeredFeatureManager

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# Number of initial bars used solely for indicator warm-up.
_WARMUP_BARS = 100


def _flatten_indicators(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten composite indicator outputs into scalar columns.

    MACD dict → MACD_macd, MACD_signal, MACD_histogram
    BollingerBands tuple → BollingerBands_middle, BollingerBands_upper, BollingerBands_lower
    KeltnerChannel tuple → KeltnerChannel_middle, KeltnerChannel_upper, KeltnerChannel_lower
    """
    flat: dict[str, Any] = {}
    for key, val in raw.items():
        if key == "MACD" and isinstance(val, dict):
            flat["MACD_macd"] = val.get("macd")
            flat["MACD_signal"] = val.get("signal")
            flat["MACD_histogram"] = val.get("histogram")
        elif key == "MACD" and isinstance(val, (tuple, list)) and len(val) >= 3:
            flat["MACD_macd"] = val[0]
            flat["MACD_signal"] = val[1]
            flat["MACD_histogram"] = val[2]
        elif key == "ADX" and isinstance(val, dict):
            flat["ADX"] = val.get("adx")
            flat["plus_DI"] = val.get("plus_di")
            flat["minus_DI"] = val.get("minus_di")
        elif key in ("BollingerBands", "KeltnerChannel") and isinstance(val, (tuple, list)):
            if len(val) >= 3:
                flat[f"{key}_middle"] = val[0]
                flat[f"{key}_upper"] = val[1]
                flat[f"{key}_lower"] = val[2]
            else:
                flat[key] = val
        else:
            flat[key] = val
    return flat


def build_scoring_feature_df(
    ohlcv_df: pd.DataFrame,
    asset: str,
    timeframe: str,
) -> pd.DataFrame:
    """Build a feature DataFrame suitable for ScoringModel.batch_evaluate().

    Pipeline:
    1. Prime FeatureManager with the first ``_WARMUP_BARS`` bars
    2. Process remaining bars via ``process_tick()`` to get raw indicators
    3. Feed raw indicators + bar data into EngineeredFeatureManager
    4. Flatten composite outputs, merge with OHLCV, return DataFrame

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        Must have columns: timestamp, open, high, low, close, volume.
        Sorted by timestamp ascending.
    asset : str
        Trading pair (e.g. "BTCUSDT").
    timeframe : str
        Kline interval (e.g. "1h").

    Returns
    -------
    pd.DataFrame
        Columns include raw indicators (RSI, ATR, …), engineered features
        (eng_regime_score, eng_mean_reversion_z, …), and OHLCV columns.
        Rows before indicator warm-up contain NaN for indicator columns.
    """
    fm = FeatureManager(asset, timeframe)
    efm = EngineeredFeatureManager(asset, timeframe)

    bar_tuples = [
        (r.open, r.high, r.low, r.close, r.volume, r.timestamp)
        for r in ohlcv_df.itertuples(index=False)
    ]

    warmup = min(_WARMUP_BARS, len(bar_tuples))
    fm.prime(bar_tuples[:warmup])

    rows: list[dict[str, Any]] = []

    # Warm-up bars: no per-bar outputs available
    for i in range(warmup):
        rows.append({})

    # Remaining bars: process one by one
    for i in range(warmup, len(bar_tuples)):
        tick = bar_tuples[i]
        raw = fm.process_tick(tick)

        bar_dict = {
            "open": tick[0],
            "high": tick[1],
            "low": tick[2],
            "close": tick[3],
            "volume": tick[4],
        }

        # EngineeredFeatureManager needs un-flattened raw indicators
        eng = efm.compute(raw, bar_dict, index_data=None)
        flat = _flatten_indicators(raw)
        flat.update(eng)
        rows.append(flat)

    df = pd.DataFrame(rows, index=ohlcv_df.index)

    # Merge OHLCV columns (always available for all rows)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = ohlcv_df[col].values

    logger.info(
        f"Built scoring feature DataFrame: {len(df)} rows, "
        f"{len(df.columns)} columns for {asset}/{timeframe}"
    )
    return df
