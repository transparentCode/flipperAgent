"""Candidate export helpers for RegimeV2 downstream evaluation.

The first implementation targets built-in downstream candidate families that
can be batch-evaluated from OHLCV plus standard indicators:

- Momentum
- TrendFollowing
- PriceAction
- SqueezeBreakout
- RegimePullbackScorer
- dataframe-exported Trendline candidates

The output dataframe is compatible with ``run_trend_family_ablation`` and can
also be written as a CSV for ``ablate_trend_family.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.momentum.model import MomentumModel
from libs.models.price_action.model import PriceActionModel
from libs.models.regime_pullback.model import RegimePullbackScorer
from libs.models.squeeze_breakout.model import SqueezeBreakoutModel
from libs.models.trend_following.model import TrendFollowingModel


@dataclass(frozen=True)
class TrendCandidateExportConfig:
    """Config for built-in downstream candidate export.

    Defaults stay conservative and backwards-compatible with the original
    trend-family proof set.  Additional Phase 4B families can be requested via
    ``models`` without changing live selection behavior.
    """

    models: tuple[str, ...] = ("Momentum", "TrendFollowing", "PriceAction")
    min_abs_edge: float = 0.0
    include_flat: bool = False


@dataclass(frozen=True)
class TrendlineCandidateExportConfig:
    """Config for dataframe-based trendline candidate export."""

    model_name: str = "Trendline"
    min_abs_edge: float = 0.0
    include_flat: bool = False
    direction_columns: tuple[str, ...] = ("trendline_direction", "signal_direction", "direction")
    slope_columns: tuple[str, ...] = ("trendline_slope", "line_slope", "slope")
    edge_columns: tuple[str, ...] = ("trendline_edge_score", "edge_score", "trendline_score", "score", "quality")
    conviction_columns: tuple[str, ...] = (
        "trendline_conviction",
        "conviction",
        "trendline_confidence",
        "confidence",
        "quality",
    )
    timestamp_columns: tuple[str, ...] = ("timestamp", "ts", "time")


def build_standard_feature_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Build standard offline indicators for Phase 4 candidate export.

    The frame intentionally uses lightweight deterministic approximations only.
    It is an evaluation harness, not the live indicator pipeline.
    """
    df = ohlcv.copy()
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing required columns: {missing}")
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def assign_if_missing(column: str, values: pd.Series) -> None:
        if column not in df.columns:
            df[column] = values
        else:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    assign_if_missing("EMA_fast", close.ewm(span=12, adjust=False, min_periods=12).mean())
    assign_if_missing("EMA_slow", close.ewm(span=26, adjust=False, min_periods=26).mean())

    macd_line = df["EMA_fast"] - df["EMA_slow"]
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    assign_if_missing("MACD_line", macd_line)
    assign_if_missing("MACD_signal", macd_signal)
    assign_if_missing("MACD_histogram", macd_line - macd_signal)

    assign_if_missing("RSI", _rsi(close, 14))
    assign_if_missing("ATR", _atr(df, 14))

    assign_if_missing("KAMA_fast", close.ewm(span=5, adjust=False, min_periods=5).mean())
    assign_if_missing("KAMA_slow", close.ewm(span=30, adjust=False, min_periods=30).mean())

    bb_mid = close.rolling(window=20, min_periods=20).mean()
    bb_std = close.rolling(window=20, min_periods=20).std(ddof=0)
    assign_if_missing("BollingerBands_upper", bb_mid + 2.0 * bb_std)
    assign_if_missing("BollingerBands_lower", bb_mid - 2.0 * bb_std)

    kc_mid = close.ewm(span=20, adjust=False, min_periods=20).mean()
    assign_if_missing("KeltnerChannel_upper", kc_mid + 1.5 * df["ATR"])
    assign_if_missing("KeltnerChannel_lower", kc_mid - 1.5 * df["ATR"])

    assign_if_missing("CCI", _cci(high, low, close, 20))
    adx, plus_di, minus_di = _adx(df, 14)
    assign_if_missing("ADX", adx)
    assign_if_missing("ADX_adx", df["ADX"] if "ADX" in df.columns else adx)
    assign_if_missing("ADX_plus_di", plus_di)
    assign_if_missing("ADX_minus_di", minus_di)
    assign_if_missing("ADLine", _ad_line(high, low, close, volume))
    assign_if_missing("MFI", _mfi(high, low, close, volume, 14))
    assign_if_missing("Momentum", close.diff(10).fillna(0.0))

    mean_20 = close.rolling(window=20, min_periods=20).mean()
    std_20 = close.rolling(window=20, min_periods=20).std(ddof=0).replace(0.0, np.nan)
    mr_z = ((close - mean_20) / std_20).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    assign_if_missing("eng_mean_reversion_z", mr_z)
    assign_if_missing("eng_squeeze_intensity", _squeeze_intensity(df))
    assign_if_missing(
        "eng_regime_score",
        _offline_regime_score(df["ADX"], df["eng_mean_reversion_z"]),
    )
    assign_if_missing("eng_btc_dominance_regime", pd.Series(0.0, index=df.index))
    assign_if_missing("eng_market_cap_breadth", pd.Series(0.0, index=df.index))
    assign_if_missing("eng_cross_asset_regime_state", pd.Series(0, index=df.index))
    assign_if_missing("eng_regime_alignment_score", pd.Series(0.0, index=df.index))
    return df


def export_builtin_trend_candidates(
    ohlcv_or_features: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: TrendCandidateExportConfig | None = None,
) -> pd.DataFrame:
    """Export candidate rows from built-in downstream model families."""
    cfg = config or TrendCandidateExportConfig()
    features = build_standard_feature_frame(ohlcv_or_features)
    rows: list[pd.DataFrame] = []

    for model_name in cfg.models:
        if _is_trendline_model_name(model_name):
            rows.append(
                export_trendline_candidates(
                    features,
                    asset=asset,
                    timeframe=timeframe,
                    config=TrendlineCandidateExportConfig(
                        model_name=model_name,
                        min_abs_edge=cfg.min_abs_edge,
                        include_flat=cfg.include_flat,
                    ),
                )
            )
            continue
        model = _make_phase4_candidate_model(model_name)
        output = model.batch_evaluate(features).reindex(features.index)
        if getattr(model.meta, "model_type", "direction") == "direction":
            rows.append(
                _directional_candidates(
                    output,
                    model_name=model.meta.name,
                    asset=asset,
                    timeframe=timeframe,
                    cfg=cfg,
                )
            )
        else:
            rows.append(
                _scoring_candidates(
                    output,
                    model_name=model.meta.name,
                    asset=asset,
                    timeframe=timeframe,
                    cfg=cfg,
                )
            )

    if not rows:
        return _empty_candidates()
    candidates = pd.concat(rows, ignore_index=True)
    return candidates.sort_values(["timestamp", "model_name"]).reset_index(drop=True)


def export_trendline_candidates(
    trendline_frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: TrendlineCandidateExportConfig | None = None,
) -> pd.DataFrame:
    """Export trendline rows into the common offline candidate schema."""
    cfg = config or TrendlineCandidateExportConfig()
    if trendline_frame.empty:
        return _empty_candidates()

    frame = trendline_frame.copy()
    direction = _direction_from_frame(frame, cfg)
    if direction is None:
        return _empty_candidates()

    direction = direction.fillna(0).astype(int).clip(-1, 1)
    edge = _numeric_alias(frame, cfg.edge_columns, default=1.0).abs().fillna(1.0)
    conviction = _numeric_alias(frame, cfg.conviction_columns, default=1.0).abs().clip(0.0, 1.0).fillna(1.0)
    mask = edge >= float(cfg.min_abs_edge)
    if not cfg.include_flat:
        mask = mask & (direction != 0)

    direction = direction[mask]
    edge = edge[mask]
    conviction = conviction[mask]
    if direction.empty:
        return _empty_candidates()

    return pd.DataFrame(
        {
            "timestamp": _timestamp_from_frame(frame.loc[direction.index], cfg),
            "model_name": cfg.model_name,
            "asset": asset,
            "timeframe": timeframe,
            "direction": direction.to_numpy(dtype=int),
            "edge_score": edge.to_numpy(dtype=float),
            "conviction": conviction.to_numpy(dtype=float),
            "source_type": "scoring",
        }
    ).reset_index(drop=True)


def _make_phase4_candidate_model(model_name: str):
    normalized = model_name.lower()
    if normalized in {"momentum", "momentumv2"}:
        return MomentumModel({})
    if normalized in {"trendfollowing", "trendfollowingmodel", "trend_following"}:
        return TrendFollowingModel({})
    if normalized in {"priceaction", "priceactionv2", "price_action"}:
        return PriceActionModel({})
    if normalized in {"squeezebreakout", "squeeze_breakout", "squeeze"}:
        return SqueezeBreakoutModel({})
    if normalized in {
        "regimepullbackscorer",
        "regime_pullback",
        "pullback",
        "regressionpullback",
        "regression_pullback",
    }:
        return RegimePullbackScorer({})
    raise ValueError(f"Unsupported Phase 4 candidate model: {model_name}")


def _is_trendline_model_name(model_name: str) -> bool:
    return model_name.lower() in {"trendline", "trendlines"}


def _directional_candidates(
    directions: pd.Series,
    *,
    model_name: str,
    asset: str,
    timeframe: str,
    cfg: TrendCandidateExportConfig,
) -> pd.DataFrame:
    direction = pd.to_numeric(directions, errors="coerce").fillna(0).astype(int)
    if not cfg.include_flat:
        direction = direction[direction != 0]
    frame = pd.DataFrame(
        {
            "timestamp": _timestamp_series(direction.index),
            "model_name": model_name,
            "asset": asset,
            "timeframe": timeframe,
            "direction": direction.to_numpy(dtype=int),
            "edge_score": 1.0,
            "conviction": 1.0,
            "source_type": "threshold",
        }
    )
    return frame


def _scoring_candidates(
    edge: pd.Series,
    *,
    model_name: str,
    asset: str,
    timeframe: str,
    cfg: TrendCandidateExportConfig,
) -> pd.DataFrame:
    score = pd.to_numeric(edge, errors="coerce").fillna(0.0)
    mask = score.abs() >= cfg.min_abs_edge
    if not cfg.include_flat:
        mask = mask & (score != 0.0)
    score = score[mask]
    direction = np.sign(score).astype(int)
    frame = pd.DataFrame(
        {
            "timestamp": _timestamp_series(score.index),
            "model_name": model_name,
            "asset": asset,
            "timeframe": timeframe,
            "direction": direction.to_numpy(dtype=int),
            "edge_score": score.abs().to_numpy(dtype=float),
            "conviction": score.abs().clip(0.0, 1.0).to_numpy(dtype=float),
            "source_type": "scoring",
        }
    )
    return frame


def _direction_from_frame(frame: pd.DataFrame, cfg: TrendlineCandidateExportConfig) -> pd.Series | None:
    direction = _first_present(frame, cfg.direction_columns)
    if direction is not None:
        return _normalize_direction(direction)
    slope = _first_present(frame, cfg.slope_columns)
    if slope is None:
        return None
    return np.sign(pd.to_numeric(slope, errors="coerce")).astype("float").rename("direction")


def _normalize_direction(raw: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(raw):
        return pd.to_numeric(raw, errors="coerce").clip(-1, 1)
    normalized = raw.astype(str).str.strip().str.lower()
    mapped = normalized.map(
        {
            "1": 1,
            "+1": 1,
            "long": 1,
            "bull": 1,
            "bullish": 1,
            "up": 1,
            "-1": -1,
            "short": -1,
            "bear": -1,
            "bearish": -1,
            "down": -1,
            "0": 0,
            "flat": 0,
            "neutral": 0,
            "none": 0,
            "nan": 0,
        }
    )
    return mapped.astype("float")


def _numeric_alias(frame: pd.DataFrame, columns: tuple[str, ...], *, default: float) -> pd.Series:
    raw = _first_present(frame, columns)
    if raw is None:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(raw, errors="coerce").fillna(default)


def _first_present(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series | None:
    for column in columns:
        if column in frame.columns:
            return frame[column]
    return None


def _timestamp_from_frame(frame: pd.DataFrame, cfg: TrendlineCandidateExportConfig) -> pd.Series:
    ts = _first_present(frame, cfg.timestamp_columns)
    if ts is not None:
        return pd.Series(ts.to_numpy(), index=None)
    return _timestamp_series(frame.index)


def _timestamp_series(index: pd.Index) -> pd.Series:
    if isinstance(index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(index, utc=True), index=None)
    return pd.Series(index, index=None)


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "model_name",
            "asset",
            "timeframe",
            "direction",
            "edge_score",
            "conviction",
            "source_type",
        ]
    )


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    typical = (high + low + close) / 3.0
    mean = typical.rolling(window=period, min_periods=period).mean()
    mad = typical.rolling(window=period, min_periods=period).apply(
        lambda values: float(np.mean(np.abs(values - np.mean(values)))),
        raw=True,
    )
    cci = (typical - mean) / (0.015 * mad.replace(0.0, np.nan))
    return cci.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _adx(df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0), index=df.index)

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return (
        adx.replace([np.inf, -np.inf], np.nan).fillna(0.0),
        plus_di.replace([np.inf, -np.inf], np.nan).fillna(0.0),
        minus_di.replace([np.inf, -np.inf], np.nan).fillna(0.0),
    )


def _ad_line(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    denom = (high - low).replace(0.0, np.nan)
    clv = (((close - low) - (high - close)) / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return (clv * volume.fillna(0.0)).cumsum()


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    typical = (high + low + close) / 3.0
    money_flow = typical * volume.fillna(0.0)
    delta = typical.diff()
    positive = money_flow.where(delta > 0.0, 0.0).rolling(window=period, min_periods=period).sum()
    negative = money_flow.where(delta < 0.0, 0.0).rolling(window=period, min_periods=period).sum().abs()
    ratio = positive / negative.replace(0.0, np.nan)
    mfi = 100.0 - (100.0 / (1.0 + ratio))
    return mfi.replace([np.inf, -np.inf], np.nan).fillna(50.0)


def _squeeze_intensity(df: pd.DataFrame) -> pd.Series:
    bb_width = df["BollingerBands_upper"] - df["BollingerBands_lower"]
    kc_width = (df["KeltnerChannel_upper"] - df["KeltnerChannel_lower"]).replace(0.0, np.nan)
    ratio = (bb_width / kc_width).replace([np.inf, -np.inf], np.nan)
    return (1.0 - ratio).clip(0.0, 1.0).fillna(0.0)


def _offline_regime_score(adx: pd.Series, mr_z: pd.Series) -> pd.Series:
    trend_component = ((adx.fillna(0.0) - 20.0) / 20.0).clip(-1.0, 1.0)
    exhaustion_discount = (mr_z.abs() / 6.0).clip(0.0, 0.3)
    return (trend_component - exhaustion_discount).clip(-1.0, 1.0).fillna(0.0)


__all__ = [
    "TrendCandidateExportConfig",
    "TrendlineCandidateExportConfig",
    "build_standard_feature_frame",
    "export_builtin_trend_candidates",
    "export_trendline_candidates",
]
