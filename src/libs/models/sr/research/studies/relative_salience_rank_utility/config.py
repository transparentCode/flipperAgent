"""Strict immutable protocol for SR-V2.4 relative-salience ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.config import require_exact_keys, require_mapping
from libs.models.sr.research.config.strict_yaml import load_strict_research_yaml


ASSETS = ("TAOUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("1d", "12h")
COHORTS = tuple((asset, timeframe) for timeframe in TIMEFRAMES for asset in ASSETS)
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)
_EXPECTED = {
    "version": "1",
    "trial": {"trial_name": "sr-v2.4-relative-salience-rank-utility", "venue": "binance_usdm", "assets": list(ASSETS), "timeframes": list(TIMEFRAMES)},
    "history": {"v2_3_source_bundle_path": "research/tmp_sr_v2_3/source/041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e", "v2_3_source_bundle_id": "041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e"},
    "provider": {"adapter": "libs.market_data.binance_native.BinanceNativeAdapter", "start": "2026-01-01T00:00:00Z", "end": "2026-07-01T00:00:00Z", "limit": 1000, "max_calls": 6, "expected_rows": {"1d": 181, "12h": 362}},
    "atr": {"method": "wilder_rma", "period": 14, "seed": "sma", "common_start_index": 28},
    "normalization": {"history_days": 365, "rank": "deterministic_midrank"},
    "outcome": {"first_touch_offset_bars": 1, "touch_search_bars": 50, "horizon_bars": 10, "control_side_order": ["SUPPORT", "RESISTANCE"]},
    "bootstrap": {"draws": 10000, "generator": "numpy.random.Generator", "bit_generator": "PCG64", "seed": 2404, "interval": "central_90_percent", "resampling": "asset_timeframe_month_cells_then_cases"},
    "readiness": {"minimum_scored_completed_cases": 350, "minimum_completed_q4_cases": 60, "minimum_completed_cases_per_cohort": 20},
    "dispositions": ["RELATIVE_SALIENCE_SUPPORTED_FOR_SHADOW", "RELATIVE_SALIENCE_NOT_SUPPORTED", "INSUFFICIENT_SOURCE_DENSITY", "INSUFFICIENT_RANK_EVIDENCE"],
    "artifact": {"output_root": "research/tmp_sr_v2_4", "source_members": ["manifest.json", "TAOUSDT_1d.json", "ETHUSDT_1d.json", "SOLUSDT_1d.json", "TAOUSDT_12h.json", "ETHUSDT_12h.json", "SOLUSDT_12h.json"], "evaluation_members": ["manifest.json", "study.json", "cases.json"]},
}


@dataclass(frozen=True)
class RelativeSalienceRankConfig:
    """Exact V2.4 protocol payload, intentionally parameter-free."""

    payload: dict[str, Any]
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.payload) is not dict or self.payload != _EXPECTED:
            raise ContractValidationError("V2.4 configuration is outside approved protocol")
        object.__setattr__(self, "config_hash", deterministic_hash(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return dict(self.payload)


def load_relative_salience_rank_config(path: str) -> RelativeSalienceRankConfig:
    raw = load_strict_research_yaml(path, description="V2.4 relative salience rank configuration")
    mapping = require_mapping(raw, path="config")
    require_exact_keys(mapping, set(_EXPECTED), path="config")
    return RelativeSalienceRankConfig(dict(mapping))


__all__ = ["ASSETS", "COHORTS", "END", "RelativeSalienceRankConfig", "START", "TIMEFRAMES", "load_relative_salience_rank_config"]
