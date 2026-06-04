"""Default configuration for the regime classification feature producer."""

from __future__ import annotations

from libs.contracts.schemas import ParamDef


REGIME_CLASSIFICATION_PARAMS = {
    "short_vol_window": ParamDef(type="int", default=24, low=8, high=72, step=4),
    "long_vol_window": ParamDef(type="int", default=168, low=72, high=720, step=24),
    "trend_window": ParamDef(type="int", default=48, low=12, high=240, step=12),
    "vol_rank_window": ParamDef(type="int", default=1000, low=240, high=3000, step=120),
    "ewma_lambda": ParamDef(type="float", default=0.94, low=0.85, high=0.99, step=0.01),
}


DEFAULT_L2_COLUMNS = (
    "l2_bid_ask_imbalance",
    "l2_spread_bps",
    "l2_depth_ratio_5",
    "l2_depth_decay_bid",
    "l2_depth_decay_ask",
    "l2_wall_bid",
    "l2_wall_ask",
    "l2_microprice_deviation_bps",
)
