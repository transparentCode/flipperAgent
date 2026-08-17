"""Offline certification harness for Momentum RSI/MACD semantics (M3).

The harness deliberately keeps configuration resolution and legacy-runtime
inspection at the evidence boundary.  The calculators under test are pure and
do not read YAML, instantiate indicator state, or publish Decision artifacts.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import json
import math
import struct
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apps.decision_app.domain.market_state import BarStore, MarketSeriesKey
from apps.decision_app.features.momentum import (
    MACDValue,
    calculate_macd,
    calculate_rsi,
)
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES
from libs.contracts.decision import CausalBarView
from libs.features.indicators.momentum.macd import MACD
from libs.features.indicators.momentum.rsi import RSI
from libs.models.momentum import MomentumConfig
from libs.models.momentum.core import (
    MomentumObservation,
    evaluate_momentum,
)

SCHEMA_VERSION = 1
CORPUS_LENGTH = 768
ROUTES = (
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "4h"),
)
HORIZON_MULTIPLIERS = (1, 2, 4, 8, 16)
RESTART_STEPS = (1, 5, 20)
RESTART_LENGTH_MULTIPLIERS = (1, 2, 4)
TIMEFRAME_DURATIONS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}


@dataclass(frozen=True, slots=True)
class RepositoryMarketMember:
    """One immutable repository-owned market series used as M3 evidence."""

    member_id: str
    evidence_class: str
    asset: str
    timeframe: str
    relative_path: str
    file_sha256: str
    row_count: int
    start_at: datetime
    end_at: datetime
    provenance_class: str
    normalization: str
    closes: tuple[float, ...]
    timestamps: tuple[datetime, ...]
    source_metadata: dict[str, Any]


REPOSITORY_MARKET_MEMBER_SPECS = (
    {
        "member_id": "btc_1h_temporal_normalized",
        "asset": "BTCUSDT",
        "timeframe": "1h",
        "relative_path": (
            "artifacts/trendlines_research_robustness/"
            "20260727_l2d5a_source_matrix_v1/members/"
            "temporal-btcusdt-1h-20250401-v1/normalized_ohlcv_v2.json"
        ),
        "provenance_class": "canonical_normalized_artifact",
        "evidence_class": "repository_market_history",
        "normalization": "trendlines.research-frame-artifact.v1",
    },
    {
        "member_id": "btc_4h_saturating_normalized",
        "asset": "BTCUSDT",
        "timeframe": "4h",
        "relative_path": (
            "artifacts/trendline_family_saturating_quality_trials/"
            "btcusdt_4h_20251201_20260401_saturating_quality_v1/input/"
            "normalized_ohlcv.csv"
        ),
        "provenance_class": "canonical_normalized_artifact",
        "evidence_class": "repository_market_history",
        "normalization": "normalized_ohlcv_csv_complete_rows",
    },
    {
        "member_id": "btc_4h_candidate_normalized",
        "asset": "BTCUSDT",
        "timeframe": "4h",
        "relative_path": (
            "artifacts/trendline_family_candidate_trials/"
            "btcusdt_4h_20250801_20251201_candidate_geometry_v2/input/"
            "normalized_ohlcv.csv"
        ),
        "provenance_class": "canonical_normalized_artifact",
        "evidence_class": "repository_market_history",
        "normalization": "normalized_ohlcv_csv_complete_rows",
    },
    {
        "member_id": "eth_4h_tv_research_input",
        "asset": "ETHUSDT",
        "timeframe": "4h",
        "relative_path": "research/model_inputs/ethusdt_4h_tv_derivatives_2025.csv",
        "provenance_class": "research_input",
        "evidence_class": "repository_market_history",
        "normalization": "research_csv_datetime_close_column",
    },
)


@dataclass(frozen=True, slots=True)
class Route:
    asset: str
    timeframe: str
    rsi_params: dict[str, int]
    macd_params: dict[str, int]
    momentum_params: dict[str, int | bool | float]
    legacy_runtime: dict[str, Any]

    @property
    def rsi_period(self) -> int:
        return self.rsi_params["period"]

    @property
    def macd_min_history(self) -> int:
        return self.macd_params["slow_period"] + self.macd_params["signal_period"] - 1

    @property
    def rsi_min_history(self) -> int:
        return self.rsi_period + 1


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _source_sha(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _parse_timestamp(value: str) -> datetime:
    """Parse only explicit millisecond or ISO-8601 UTC timestamps."""

    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
    except ValueError:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("repository market timestamps must be UTC")
        return parsed


def _decode_float64_column(column: dict[str, Any]) -> tuple[float, ...]:
    if column.get("numpy_dtype") != "float64":
        raise ValueError(
            f"unsupported normalized column dtype: {column.get('numpy_dtype')}"
        )
    raw = base64.b64decode(column["bytes_base64"])
    if len(raw) % 8:
        raise ValueError("normalized float64 column has invalid byte length")
    values = struct.unpack(f"<{len(raw) // 8}d", raw)
    shape = column.get("shape")
    if not isinstance(shape, list) or len(shape) != 1 or shape[0] != len(values):
        raise ValueError("normalized column shape does not match decoded values")
    return tuple(float(value) for value in values)


def _load_normalized_json(
    path: Path,
) -> tuple[tuple[datetime, ...], tuple[float, ...], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    columns = {
        column["name"]: _decode_float64_column(column) for column in document["columns"]
    }
    timestamps = tuple(
        datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        for value in document["index"]["values"]
    )
    if "close" not in columns or len(columns["close"]) != len(timestamps):
        raise ValueError(
            "normalized JSON must contain close values aligned to its index"
        )
    return (
        timestamps,
        columns["close"],
        {
            "asset": document.get("asset"),
            "timeframe": document.get("timeframe"),
            "artifact_id": document.get("artifact_id"),
            "dataset_id": document.get("dataset_id"),
            "schema_version": document.get("schema_version"),
            "semantics_version": document.get("semantics_version"),
            "source_id": document.get("source_id"),
            "attributes": document.get("attributes", {}),
            "data_spec": document.get("data_spec", {}),
        },
    )


def _load_market_csv(
    path: Path,
) -> tuple[tuple[datetime, ...], tuple[float, ...], dict[str, Any]]:
    timestamps: list[datetime] = []
    closes: list[float] = []
    complete_rows = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "close" not in reader.fieldnames:
            raise ValueError("market CSV must contain a close column")
        timestamp_field = "datetime" if "datetime" in reader.fieldnames else "timestamp"
        if timestamp_field not in reader.fieldnames:
            raise ValueError("market CSV must contain datetime or timestamp")
        for row in reader:
            if "complete" in row and row["complete"].strip().lower() != "true":
                continue
            complete_rows += 1
            timestamps.append(_parse_timestamp(row[timestamp_field]))
            closes.append(float(row["close"]))
    return (
        tuple(timestamps),
        tuple(closes),
        {
            "complete_filter": "complete == true"
            if "complete" in reader.fieldnames
            else None,
            "timestamp_column": timestamp_field,
            "close_column": "close",
            "complete_rows": complete_rows,
        },
    )


def _validate_repository_series(
    *,
    asset: str,
    timeframe: str,
    timestamps: Sequence[datetime],
    closes: Sequence[float],
) -> None:
    if not timestamps or len(timestamps) != len(closes):
        raise ValueError("repository market series must have aligned non-empty columns")
    duration = TIMEFRAME_DURATIONS[timeframe]
    for timestamp in timestamps:
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise ValueError(f"{asset}/{timeframe} timestamps must be UTC")
        if timestamp.minute or timestamp.second or timestamp.microsecond:
            raise ValueError(f"{asset}/{timeframe} timestamps are not bucket aligned")
        if timeframe == "4h" and timestamp.hour % 4:
            raise ValueError(f"{asset}/{timeframe} timestamps are not 4h aligned")
    if any(not math.isfinite(float(close)) for close in closes):
        raise ValueError(f"{asset}/{timeframe} contains a non-finite close")
    for previous, current in pairwise(timestamps):
        if current <= previous:
            raise ValueError(f"{asset}/{timeframe} timestamps are not ordered")
        if current - previous != duration:
            raise ValueError(f"{asset}/{timeframe} contains a timeframe gap")


def load_repository_market_members(
    root: Path = ROOT,
) -> tuple[RepositoryMarketMember, ...]:
    """Load the explicit, immutable M3 repository evidence manifest."""

    members: list[RepositoryMarketMember] = []
    for spec in REPOSITORY_MARKET_MEMBER_SPECS:
        path = root / spec["relative_path"]
        if not path.is_file():
            raise FileNotFoundError(f"required M3 market evidence is missing: {path}")
        if path.suffix == ".json":
            timestamps, closes, metadata = _load_normalized_json(path)
            if (
                metadata.get("schema_version")
                != "trendlines.research-frame-artifact.v1"
            ):
                raise ValueError(f"unexpected normalized artifact schema: {path}")
            if metadata.get("asset") != spec["asset"]:
                raise ValueError(
                    f"normalized artifact asset does not match manifest: {path}"
                )
            if metadata.get("timeframe") != spec["timeframe"]:
                raise ValueError(
                    f"normalized artifact timeframe does not match manifest: {path}"
                )
        else:
            timestamps, closes, metadata = _load_market_csv(path)
        _validate_repository_series(
            asset=spec["asset"],
            timeframe=spec["timeframe"],
            timestamps=timestamps,
            closes=closes,
        )
        members.append(
            RepositoryMarketMember(
                member_id=spec["member_id"],
                evidence_class=spec["evidence_class"],
                asset=spec["asset"],
                timeframe=spec["timeframe"],
                relative_path=spec["relative_path"],
                file_sha256=sha256(path.read_bytes()).hexdigest(),
                row_count=len(closes),
                start_at=timestamps[0],
                end_at=timestamps[-1],
                provenance_class=spec["provenance_class"],
                normalization=spec["normalization"],
                closes=tuple(closes),
                timestamps=tuple(timestamps),
                source_metadata=metadata,
            )
        )
    return tuple(members)


def _normalize_indicator_params(indicator: object) -> dict[str, int] | None:
    if isinstance(indicator, RSI):
        return {"period": int(indicator.period)}
    if isinstance(indicator, MACD):
        return {
            "fast_period": int(indicator.fast_period),
            "slow_period": int(indicator.slow_period),
            "signal_period": int(indicator.signal_period),
        }
    return None


def _raw_runtime_resolution(
    *,
    asset: str,
    timeframe: str,
    config_manager: ConfigManager,
) -> dict[str, Any]:
    # Import at the evidence boundary: this intentionally measures the legacy
    # pipeline and is not imported by the pure Decision calculator.
    from apps.signal_app.pipeline.raw_indicators import RawIndicatorPipeline

    pipeline = RawIndicatorPipeline(
        asset,
        timeframe,
        config_manager=config_manager,
    )
    actual: dict[str, Any] = {"RSI": None, "MACD": None}
    indicator_evidence: list[dict[str, Any]] = []
    for output_key, indicator in pipeline._indicator_entries:
        lookback_required = int(indicator.lookback_required)
        indicator_evidence.append(
            {
                "output_key": output_key,
                "indicator": indicator.__class__.__name__,
                "lookback_required": lookback_required,
            }
        )
        params = _normalize_indicator_params(indicator)
        if isinstance(indicator, RSI):
            actual["RSI"] = params
        elif isinstance(indicator, MACD):
            actual["MACD"] = params
    return {
        "instantiated": actual,
        "indicators": indicator_evidence,
        "observed_startup_max_lookback": max(
            (item["lookback_required"] for item in indicator_evidence),
            default=0,
        ),
        "rsi_minimum_lookback": (
            None if actual["RSI"] is None else int(actual["RSI"]["period"]) + 1
        ),
        "macd_minimum_lookback": (
            None
            if actual["MACD"] is None
            else int(actual["MACD"]["slow_period"])
            + int(actual["MACD"]["signal_period"])
            - 1
        ),
        "pipeline_class": "RawIndicatorPipeline",
    }


def _load_momentum_params(root: Path, asset: str, timeframe: str) -> dict[str, Any]:
    document = yaml.safe_load(
        (root / "configs" / "models.yaml").read_text(encoding="utf-8")
    )
    node = document["strategy_models"]["assets"][asset]["timeframes"][timeframe]
    momentum = node["MomentumV2"]
    if not momentum.get("enabled", True):
        raise ValueError(f"MomentumV2 is not enabled for {asset}/{timeframe}")
    return MomentumConfig.from_mapping(momentum.get("params", {})).to_mapping()


def resolve_routes(root: Path = ROOT) -> tuple[Route, ...]:
    """Resolve both intended config semantics and observed legacy instantiation."""

    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(root / "configs"))
    manager.register_file(root / CONFIG_FILE_FEATURES)
    try:
        routes: list[Route] = []
        for asset, timeframe in ROUTES:
            raw_rsi = manager.get_feature_params(asset, timeframe, "RSI")
            raw_macd = manager.get_feature_params(asset, timeframe, "MACD")
            rsi_params = {"period": int(raw_rsi["period"])}
            macd_params = {
                "fast_period": int(raw_macd["fast_period"]),
                "slow_period": int(raw_macd["slow_period"]),
                "signal_period": int(raw_macd["signal_period"]),
            }
            intended = {"RSI": rsi_params, "MACD": macd_params}
            legacy_runtime = _raw_runtime_resolution(
                asset=asset,
                timeframe=timeframe,
                config_manager=manager,
            )
            actual = legacy_runtime["instantiated"]
            legacy_runtime["intended_config_manager"] = intended
            legacy_runtime["discrepancy"] = {
                name: {
                    "intended": intended[name],
                    "observed": actual[name],
                    "matches": intended[name] == actual[name],
                }
                for name in ("RSI", "MACD")
            }
            routes.append(
                Route(
                    asset=asset,
                    timeframe=timeframe,
                    rsi_params=rsi_params,
                    macd_params=macd_params,
                    momentum_params=_load_momentum_params(root, asset, timeframe),
                    legacy_runtime=legacy_runtime,
                )
            )
        return tuple(routes)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _corpus_series() -> dict[str, tuple[float, ...]]:
    up = tuple(100.0 + 0.15 * index for index in range(CORPUS_LENGTH))
    down = tuple(300.0 - 0.15 * index for index in range(CORPUS_LENGTH))
    flat = tuple(100.0 for _ in range(CORPUS_LENGTH))

    alternating_values: list[float] = [100.0]
    for index in range(1, CORPUS_LENGTH):
        alternating_values.append(alternating_values[-1] + (1.0 if index % 2 else -0.8))

    reversal_values: list[float] = []
    for index in range(CORPUS_LENGTH):
        if index < CORPUS_LENGTH // 2:
            reversal_values.append(100.0 + 0.2 * index)
        else:
            reversal_values.append(
                100.0 + 0.2 * (CORPUS_LENGTH // 2) - 0.23 * (index - CORPUS_LENGTH // 2)
            )

    expansion_values: list[float] = [100.0]
    for index in range(1, CORPUS_LENGTH):
        magnitude = 0.03 + 0.0015 * (index % 80)
        expansion_values.append(
            expansion_values[-1] + (magnitude if index % 2 else -magnitude * 0.8)
        )

    oscillation = tuple(
        100.0 + 0.8 * math.sin(index * 0.19) for index in range(CORPUS_LENGTH)
    )

    shock_values: list[float] = []
    for index in range(CORPUS_LENGTH):
        base = 100.0 + 0.04 * index
        shock = 18.0 if index == CORPUS_LENGTH // 2 else 0.0
        if index > CORPUS_LENGTH // 2:
            shock = 18.0 * math.exp(-(index - CORPUS_LENGTH // 2) / 18.0)
        shock_values.append(base + shock)

    near_threshold_values: list[float] = [100.0]
    near_threshold_pattern = (10.0,) * 6 + (-7.0,) * 4
    for index in range(1, CORPUS_LENGTH):
        near_threshold_values.append(
            near_threshold_values[-1]
            + near_threshold_pattern[(index - 1) % len(near_threshold_pattern)]
        )

    return {
        "monotonic_uptrend": up,
        "monotonic_downtrend": down,
        "flat_prices": flat,
        "alternating_gains_losses": tuple(alternating_values),
        "trend_reversal": tuple(reversal_values),
        "volatility_expansion": tuple(expansion_values),
        "low_amplitude_oscillation": oscillation,
        "large_gap_shock": tuple(shock_values),
        "near_threshold": tuple(near_threshold_values),
    }


def corpus_identity(corpus: dict[str, Sequence[float]]) -> str:
    return _json_hash({name: list(values) for name, values in sorted(corpus.items())})


def _route_corpus(
    route: Route,
    synthetic: dict[str, Sequence[float]],
    repository_members: Sequence[RepositoryMarketMember],
) -> dict[str, Sequence[float]]:
    corpus: dict[str, Sequence[float]] = dict(synthetic)
    for member in repository_members:
        if (member.asset, member.timeframe) == (route.asset, route.timeframe):
            corpus[member.member_id] = member.closes
    return corpus


def _repository_member_identity(
    member: RepositoryMarketMember,
    routes: Sequence[Route],
) -> dict[str, Any]:
    route_eligibility: dict[str, dict[str, Any]] = {}
    for route in routes:
        route_id = f"{route.asset}/{route.timeframe}"
        required_bars = max(
            route.rsi_min_history * max(HORIZON_MULTIPLIERS),
            route.macd_min_history * max(HORIZON_MULTIPLIERS),
        )
        route_eligibility[route_id] = {
            "applicable": (member.asset, member.timeframe)
            == (route.asset, route.timeframe),
            "row_count": member.row_count,
            "candidate_horizons": {
                str(multiplier): {
                    "required_bars": max(
                        route.rsi_min_history * multiplier,
                        route.macd_min_history * multiplier,
                    ),
                    "eligible": member.row_count
                    >= max(
                        route.rsi_min_history * multiplier,
                        route.macd_min_history * multiplier,
                    ),
                }
                for multiplier in HORIZON_MULTIPLIERS
            }
            if (member.asset, member.timeframe) == (route.asset, route.timeframe)
            else {},
            "maximum_ladder_bars": required_bars,
        }
    return {
        "member_id": member.member_id,
        "evidence_class": member.evidence_class,
        "asset": member.asset,
        "timeframe": member.timeframe,
        "repository_relative_path": member.relative_path,
        "file_sha256": member.file_sha256,
        "row_count": member.row_count,
        "start_at": member.start_at.isoformat(),
        "end_at": member.end_at.isoformat(),
        "provenance_class": member.provenance_class,
        "normalization": member.normalization,
        "source_metadata": member.source_metadata,
        "candidate_eligibility": route_eligibility,
    }


def _barstore_practicality(
    routes: Sequence[Route],
    route_artifacts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Prove selected route capacities fit the current bounded D3 structures."""

    capacities: dict[MarketSeriesKey, int] = {}
    route_evidence: list[dict[str, Any]] = []
    grid_start = datetime(2025, 1, 1, tzinfo=UTC)
    for route, artifact in zip(routes, route_artifacts):
        selected = artifact["recommended_candidate"]
        if selected is None:
            return {
                "status": "BLOCKED_NO_SELECTED_HORIZON",
                "route_evidence": route_evidence,
            }
        horizon = selected["horizon"]
        capacity = max(horizon["rsi_bars"], horizon["macd_bars"])
        key = MarketSeriesKey(
            asset=route.asset,
            venue="m3-offline",
            instrument_id=f"{route.asset}-m3",
            timeframe=route.timeframe,
        )
        capacities[key] = capacity

    store = BarStore(capacities)
    repository = InMemoryCanonicalMarketHistoryRepository(
        {
            key: (
                CausalBarView(
                    timeframe=key.timeframe,
                    bar_open_at=grid_start,
                    bar_close_at=grid_start + TIMEFRAME_DURATIONS[key.timeframe],
                    market_as_of=grid_start + TIMEFRAME_DURATIONS[key.timeframe],
                    open=Decimal(100),
                    high=Decimal(101),
                    low=Decimal(99),
                    close=Decimal("100.5"),
                    volume=Decimal(1),
                    taker_buy_base=Decimal("0.5"),
                    closed=True,
                ),
            )
            for key in capacities
        }
    )
    positive_limit_accepted = True
    for key, capacity in capacities.items():
        duration = TIMEFRAME_DURATIONS[key.timeframe]
        for index in range(capacity):
            opened_at = grid_start + index * duration
            closed_at = opened_at + duration
            close = Decimal(100) + Decimal(index) / Decimal(10)
            store.append(
                key,
                CausalBarView(
                    timeframe=key.timeframe,
                    bar_open_at=opened_at,
                    bar_close_at=closed_at,
                    market_as_of=closed_at,
                    open=close,
                    high=close + Decimal(1),
                    low=close - Decimal(1),
                    close=close,
                    volume=Decimal(1),
                    taker_buy_base=Decimal("0.5"),
                    closed=True,
                ),
            )
        try:
            asyncio.run(repository.fetch_bars(key, limit=capacity))
        except (TypeError, ValueError):
            positive_limit_accepted = False
        route_evidence.append(
            {
                "series_key": {
                    "asset": key.asset,
                    "venue": key.venue,
                    "instrument_id": key.instrument_id,
                    "timeframe": key.timeframe,
                },
                "effective_capacity": capacity,
                "capacity_for": store.capacity_for(key),
                "retained_count": store.retained_count(key),
            }
        )
    total_retained = sum(item["retained_count"] for item in route_evidence)
    return {
        "status": "PASS",
        "route_evidence": route_evidence,
        "total_retained_bars": total_retained,
        "expected_total_retained_bars": sum(capacities.values()),
        "capacity_is_max_of_rsi_macd": True,
        "series_are_not_summed_across_routes": len(capacities) == len(routes),
        "positive_history_limit_accepted": positive_limit_accepted,
        "tracemalloc": {
            "recorded": False,
            "reason": "platform-dependent diagnostic remains outside deterministic identity",
        },
        "final_model_mix_resource_recertification": (
            "FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED"
        ),
    }


def _error_summary(errors: Iterable[float]) -> dict[str, float | int]:
    values = sorted(float(error) for error in errors)
    if not values:
        return {
            "count": 0,
            "max_absolute_error": 0.0,
            "mean_absolute_error": 0.0,
            "median_absolute_error": 0.0,
            "p95_absolute_error": 0.0,
        }
    p95_index = min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)
    return {
        "count": len(values),
        "max_absolute_error": values[-1],
        "mean_absolute_error": sum(values) / len(values),
        "median_absolute_error": values[(len(values) - 1) // 2],
        "p95_absolute_error": values[p95_index],
    }


def _momentum_result(route: Route, rsi: float, macd: MACDValue) -> Any:
    observation = MomentumObservation(
        rsi=rsi,
        macd_histogram=macd.histogram,
        macd_line=macd.line,
    )
    return evaluate_momentum(
        observation,
        MomentumConfig.from_mapping(route.momentum_params),
    )


def _candidate_horizon(route: Route, multiplier: int) -> dict[str, int]:
    return {
        "rsi_bars": route.rsi_min_history * multiplier,
        "macd_bars": route.macd_min_history * multiplier,
        "multiplier": multiplier,
    }


def _empty_family_metrics() -> dict[str, Any]:
    return {
        "count": 0,
        "rsi_max_absolute_error": 0.0,
        "macd_histogram_max_absolute_error": 0.0,
        "direction_disagreements": 0,
        "tradable_neutral_disagreements": 0,
        "max_absolute_score_delta": 0.0,
        "mean_absolute_score_delta": 0.0,
        "max_absolute_conviction_delta": 0.0,
        "mean_absolute_conviction_delta": 0.0,
        "_score_delta_sum": 0.0,
        "_conviction_delta_sum": 0.0,
    }


def evaluate_candidate(
    route: Route,
    corpus: dict[str, Sequence[float]],
    *,
    candidate_name: str,
    horizon: dict[str, int],
    required_repository_members: Sequence[str] = (),
    evidence_classes: dict[str, str] | None = None,
) -> dict[str, Any]:
    rsi_errors: list[float] = []
    macd_errors = {"line": [], "signal": [], "histogram": []}
    direction_disagreements = 0
    tradable_disagreements = 0
    long_short_disagreements = 0
    score_deltas: list[float] = []
    conviction_deltas: list[float] = []
    first_disagreements: list[dict[str, Any]] = []
    family_metrics = {name: _empty_family_metrics() for name in sorted(corpus)}

    for family, closes in sorted(corpus.items()):
        minimum_cutoff = max(horizon["rsi_bars"], horizon["macd_bars"]) - 1
        for cutoff in range(minimum_cutoff, len(closes)):
            prefix = closes[: cutoff + 1]
            reference_rsi = calculate_rsi(prefix, period=route.rsi_period)
            reference_macd = calculate_macd(
                prefix,
                **route.macd_params,
            )
            candidate_rsi = calculate_rsi(
                closes[cutoff + 1 - horizon["rsi_bars"] : cutoff + 1],
                period=route.rsi_period,
            )
            candidate_macd = calculate_macd(
                closes[cutoff + 1 - horizon["macd_bars"] : cutoff + 1],
                **route.macd_params,
            )
            rsi_error = abs(candidate_rsi - reference_rsi)
            rsi_errors.append(rsi_error)
            macd_errors["line"].append(abs(candidate_macd.line - reference_macd.line))
            macd_errors["signal"].append(
                abs(candidate_macd.signal - reference_macd.signal)
            )
            macd_errors["histogram"].append(
                abs(candidate_macd.histogram - reference_macd.histogram)
            )

            reference_result = _momentum_result(route, reference_rsi, reference_macd)
            candidate_result = _momentum_result(route, candidate_rsi, candidate_macd)
            direction_differs = candidate_result.direction != reference_result.direction
            tradable_differs = (candidate_result.direction != 0) != (
                reference_result.direction != 0
            )
            long_short_differs = (
                candidate_result.direction != 0
                and reference_result.direction != 0
                and candidate_result.direction != reference_result.direction
            )
            direction_disagreements += int(direction_differs)
            tradable_disagreements += int(tradable_differs)
            long_short_disagreements += int(long_short_differs)
            score_deltas.append(abs(candidate_result.score - reference_result.score))
            conviction_deltas.append(
                abs(candidate_result.conviction - reference_result.conviction)
            )
            family_entry = family_metrics[family]
            family_entry["count"] += 1
            family_entry["rsi_max_absolute_error"] = max(
                family_entry["rsi_max_absolute_error"], rsi_error
            )
            family_entry["macd_histogram_max_absolute_error"] = max(
                family_entry["macd_histogram_max_absolute_error"],
                abs(candidate_macd.histogram - reference_macd.histogram),
            )
            family_entry["direction_disagreements"] += int(direction_differs)
            family_entry["tradable_neutral_disagreements"] += int(tradable_differs)
            score_delta = abs(candidate_result.score - reference_result.score)
            conviction_delta = abs(
                candidate_result.conviction - reference_result.conviction
            )
            family_entry["max_absolute_score_delta"] = max(
                family_entry["max_absolute_score_delta"], score_delta
            )
            family_entry["_score_delta_sum"] += score_delta
            family_entry["max_absolute_conviction_delta"] = max(
                family_entry["max_absolute_conviction_delta"], conviction_delta
            )
            family_entry["_conviction_delta_sum"] += conviction_delta
            if direction_differs and len(first_disagreements) < 10:
                first_disagreements.append(
                    {
                        "family": family,
                        "cutoff_index": cutoff,
                        "reference_direction": reference_result.direction,
                        "candidate_direction": candidate_result.direction,
                    }
                )

    for family_entry in family_metrics.values():
        count = family_entry["count"]
        family_entry["mean_absolute_score_delta"] = (
            family_entry["_score_delta_sum"] / count if count else 0.0
        )
        family_entry["mean_absolute_conviction_delta"] = (
            family_entry["_conviction_delta_sum"] / count if count else 0.0
        )
        family_entry.pop("_score_delta_sum")
        family_entry.pop("_conviction_delta_sum")
    repository_eligibility = {
        member_id: {
            "row_count": len(corpus.get(member_id, ())),
            "required_bars": max(horizon["rsi_bars"], horizon["macd_bars"]),
            "eligible": len(corpus.get(member_id, ()))
            >= max(horizon["rsi_bars"], horizon["macd_bars"]),
        }
        for member_id in sorted(required_repository_members)
    }
    class_metrics: dict[str, dict[str, Any]] = {}
    for family, family_entry in family_metrics.items():
        evidence_class = (
            "synthetic_mathematical_edge_family"
            if evidence_classes is None
            else evidence_classes.get(family, "synthetic_mathematical_edge_family")
        )
        family_entry["evidence_class"] = evidence_class
        aggregate = class_metrics.setdefault(
            evidence_class,
            {
                "count": 0,
                "direction_disagreements": 0,
                "tradable_neutral_disagreements": 0,
                "max_absolute_score_delta": 0.0,
                "mean_absolute_score_delta": 0.0,
                "max_absolute_conviction_delta": 0.0,
                "mean_absolute_conviction_delta": 0.0,
                "_score_delta_sum": 0.0,
                "_conviction_delta_sum": 0.0,
            },
        )
        aggregate["count"] += family_entry["count"]
        aggregate["direction_disagreements"] += family_entry["direction_disagreements"]
        aggregate["tradable_neutral_disagreements"] += family_entry[
            "tradable_neutral_disagreements"
        ]
        aggregate["max_absolute_score_delta"] = max(
            aggregate["max_absolute_score_delta"],
            family_entry["max_absolute_score_delta"],
        )
        aggregate["max_absolute_conviction_delta"] = max(
            aggregate["max_absolute_conviction_delta"],
            family_entry["max_absolute_conviction_delta"],
        )
        aggregate["_score_delta_sum"] += (
            family_entry["mean_absolute_score_delta"] * family_entry["count"]
        )
        aggregate["_conviction_delta_sum"] += (
            family_entry["mean_absolute_conviction_delta"] * family_entry["count"]
        )
    for aggregate in class_metrics.values():
        count = aggregate["count"]
        aggregate["mean_absolute_score_delta"] = (
            aggregate["_score_delta_sum"] / count if count else 0.0
        )
        aggregate["mean_absolute_conviction_delta"] = (
            aggregate["_conviction_delta_sum"] / count if count else 0.0
        )
        aggregate.pop("_score_delta_sum")
        aggregate.pop("_conviction_delta_sum")

    return {
        "candidate": candidate_name,
        "horizon": horizon,
        "eligible_cutoffs": len(rsi_errors),
        "rsi": _error_summary(rsi_errors),
        "macd": {name: _error_summary(values) for name, values in macd_errors.items()},
        "momentum": {
            "direction_disagreements": direction_disagreements,
            "tradable_neutral_disagreements": tradable_disagreements,
            "long_short_disagreements": long_short_disagreements,
            "direction_agreement_rate": (
                1.0 - direction_disagreements / len(rsi_errors) if rsi_errors else 0.0
            ),
            "max_absolute_score_delta": max(score_deltas, default=0.0),
            "mean_absolute_score_delta": (
                sum(score_deltas) / len(score_deltas) if score_deltas else 0.0
            ),
            "max_absolute_conviction_delta": max(conviction_deltas, default=0.0),
            "mean_absolute_conviction_delta": (
                sum(conviction_deltas) / len(conviction_deltas)
                if conviction_deltas
                else 0.0
            ),
            "first_disagreements": first_disagreements,
        },
        "by_family": family_metrics,
        "by_evidence_class": class_metrics,
        "repository_member_eligibility": repository_eligibility,
    }


def _legacy_restart_value(
    closes: Sequence[float],
    *,
    cutoff: int,
    restart_steps: int,
    seed_length: int,
    indicator_name: str,
    route: Route,
) -> float | MACDValue:
    prime_end = cutoff - restart_steps
    start = prime_end - seed_length + 1
    if start < 0:
        raise ValueError("restart history is not available")
    history = closes[start : prime_end + 1]
    if indicator_name == "RSI":
        indicator = RSI(route.rsi_period)
    else:
        indicator = MACD(**route.macd_params)
    indicator.prime(history)
    output: Any = None
    for value in closes[prime_end + 1 : cutoff + 1]:
        output = indicator.update(value)
    if output is None:
        if indicator_name == "RSI":
            return calculate_rsi(history, period=route.rsi_period)
        return calculate_macd(history, **route.macd_params)
    if indicator_name == "RSI":
        return float(output)
    return MACDValue(
        line=float(output[0]),
        signal=float(output[1]),
        histogram=float(output[2]),
    )


def evaluate_restart_sensitivity(
    route: Route,
    corpus: dict[str, Sequence[float]],
) -> dict[str, Any]:
    cases = 0
    rsi_differences = 0
    macd_differences = {"line": 0, "signal": 0, "histogram": 0}
    direction_differences = 0
    score_differences = 0
    examples: list[dict[str, Any]] = []
    base_length = max(route.rsi_min_history, route.macd_min_history)
    cutoffs = (base_length * 8, base_length * 12, CORPUS_LENGTH - 1)

    for family, closes in sorted(corpus.items()):
        for cutoff in cutoffs:
            if cutoff >= len(closes):
                continue
            reference_rsi = calculate_rsi(closes[: cutoff + 1], period=route.rsi_period)
            reference_macd = calculate_macd(closes[: cutoff + 1], **route.macd_params)
            reference_result = _momentum_result(route, reference_rsi, reference_macd)
            for length_multiplier in RESTART_LENGTH_MULTIPLIERS:
                seed_length = base_length * length_multiplier
                for restart_step in RESTART_STEPS:
                    if cutoff - restart_step < seed_length - 1:
                        continue
                    restart_rsi = _legacy_restart_value(
                        closes,
                        cutoff=cutoff,
                        restart_steps=restart_step,
                        seed_length=seed_length,
                        indicator_name="RSI",
                        route=route,
                    )
                    restart_macd = _legacy_restart_value(
                        closes,
                        cutoff=cutoff,
                        restart_steps=restart_step,
                        seed_length=seed_length,
                        indicator_name="MACD",
                        route=route,
                    )
                    if not isinstance(restart_macd, MACDValue):
                        raise TypeError("MACD restart did not return MACDValue")
                    cases += 1
                    rsi_differs = abs(float(restart_rsi) - reference_rsi) > 0.0
                    rsi_differences += int(rsi_differs)
                    component_differences = {
                        "line": abs(restart_macd.line - reference_macd.line) > 0.0,
                        "signal": abs(restart_macd.signal - reference_macd.signal)
                        > 0.0,
                        "histogram": abs(
                            restart_macd.histogram - reference_macd.histogram
                        )
                        > 0.0,
                    }
                    for component, differs in component_differences.items():
                        macd_differences[component] += int(differs)
                    restart_result = _momentum_result(
                        route,
                        float(restart_rsi),
                        restart_macd,
                    )
                    direction_differs = (
                        restart_result.direction != reference_result.direction
                    )
                    score_differs = restart_result.score != reference_result.score
                    direction_differences += int(direction_differs)
                    score_differences += int(score_differs)
                    if (rsi_differs or any(component_differences.values())) and len(
                        examples
                    ) < 10:
                        examples.append(
                            {
                                "family": family,
                                "cutoff_index": cutoff,
                                "seed_length": seed_length,
                                "restart_steps": restart_step,
                                "rsi_absolute_error": abs(
                                    float(restart_rsi) - reference_rsi
                                ),
                                "macd_histogram_absolute_error": abs(
                                    restart_macd.histogram - reference_macd.histogram
                                ),
                                "direction_disagrees": direction_differs,
                            }
                        )

    return {
        "cases": cases,
        "rsi_value_differences": rsi_differences,
        "macd_value_differences": macd_differences,
        "momentum_direction_differences": direction_differences,
        "momentum_score_differences": score_differences,
        "examples": examples,
    }


def evaluate_observed_startup_restart(
    route: Route,
    corpus: dict[str, Sequence[float]],
) -> dict[str, Any]:
    """Measure prime/update restart using the legacy route's actual lookback."""

    seed_length = int(route.legacy_runtime["observed_startup_max_lookback"])
    if seed_length <= 0:
        return {
            "applicable": False,
            "reason": "legacy pipeline exposed no instantiated indicators",
            "seed_length": seed_length,
        }

    instantiated = route.legacy_runtime["instantiated"]
    evidence: dict[str, Any] = {
        "applicable": True,
        "seed_length": seed_length,
        "restart_steps": list(RESTART_STEPS),
        "indicators": {},
    }
    for indicator_name in ("RSI", "MACD"):
        if instantiated[indicator_name] is None:
            evidence["indicators"][indicator_name] = {
                "applicable": False,
                "reason": "not instantiated by legacy RawIndicatorPipeline",
            }
            continue
        cases = 0
        value_differences = 0
        examples: list[dict[str, Any]] = []
        for family, closes in sorted(corpus.items()):
            cutoffs = tuple(
                dict.fromkeys(
                    cutoff
                    for cutoff in (
                        seed_length,
                        seed_length * 2,
                        len(closes) - 1,
                    )
                    if cutoff < len(closes)
                )
            )
            for cutoff in cutoffs:
                reference = (
                    calculate_rsi(closes[: cutoff + 1], period=route.rsi_period)
                    if indicator_name == "RSI"
                    else calculate_macd(closes[: cutoff + 1], **route.macd_params)
                )
                for restart_step in RESTART_STEPS:
                    if cutoff - restart_step < seed_length - 1:
                        continue
                    restarted = _legacy_restart_value(
                        closes,
                        cutoff=cutoff,
                        restart_steps=restart_step,
                        seed_length=seed_length,
                        indicator_name=indicator_name,
                        route=route,
                    )
                    if indicator_name == "RSI":
                        differs = abs(float(restarted) - float(reference)) > 0.0
                        error = abs(float(restarted) - float(reference))
                    else:
                        if not isinstance(restarted, MACDValue) or not isinstance(
                            reference, MACDValue
                        ):
                            raise TypeError("MACD startup restart type mismatch")
                        differs = any(
                            left != right
                            for left, right in zip(
                                (restarted.line, restarted.signal, restarted.histogram),
                                (reference.line, reference.signal, reference.histogram),
                            )
                        )
                        error = abs(restarted.histogram - reference.histogram)
                    cases += 1
                    value_differences += int(differs)
                    if differs and len(examples) < 10:
                        examples.append(
                            {
                                "family": family,
                                "cutoff_index": cutoff,
                                "restart_steps": restart_step,
                                "absolute_error": error,
                            }
                        )
        evidence["indicators"][indicator_name] = {
            "applicable": True,
            "cases": cases,
            "value_differences": value_differences,
            "examples": examples,
        }
    return evidence


def _select_candidate(
    results: Sequence[dict[str, Any]],
    *,
    required_repository_members: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Select the first bounded candidate with stable trade semantics.

    No numerical tolerance is invented here.  The numerical convergence table
    remains evidence for review; the hard semantic gates are exact zero
    direction and tradable/neutral disagreements against the full prefix.
    """

    convergence = {
        "rsi_p95_non_increasing": _non_increasing(
            [result["rsi"]["p95_absolute_error"] for result in results]
        ),
        "macd_line_p95_non_increasing": _non_increasing(
            [result["macd"]["line"]["p95_absolute_error"] for result in results]
        ),
        "macd_signal_p95_non_increasing": _non_increasing(
            [result["macd"]["signal"]["p95_absolute_error"] for result in results]
        ),
        "macd_histogram_p95_non_increasing": _non_increasing(
            [result["macd"]["histogram"]["p95_absolute_error"] for result in results]
        ),
    }
    if not all(convergence.values()):
        return None

    for result in results:
        momentum = result["momentum"]
        eligibility = result.get("repository_member_eligibility", {})
        all_repository_members_eligible = all(
            eligibility.get(member_id, {}).get("eligible", False)
            for member_id in required_repository_members
        )
        if (
            all_repository_members_eligible
            and momentum["direction_disagreements"] == 0
            and momentum["tradable_neutral_disagreements"] == 0
        ):
            return {
                "candidate": result["candidate"],
                "horizon": result["horizon"],
                "reason": (
                    "zero direction and tradable/neutral disagreements on the "
                    "certification corpus, with non-increasing p95 feature errors "
                    "across the evaluated horizon ladder"
                ),
                "convergence": convergence,
            }
    return None


def _non_increasing(values: Sequence[float]) -> bool:
    return all(current <= previous for previous, current in pairwise(values))


def _route_artifact(
    route: Route,
    corpus: dict[str, Sequence[float]],
    repository_members: Sequence[RepositoryMarketMember],
) -> dict[str, Any]:
    required_repository_members = tuple(
        member.member_id
        for member in repository_members
        if (member.asset, member.timeframe) == (route.asset, route.timeframe)
    )
    evidence_classes = {
        name: (
            "repository_market_history"
            if name in required_repository_members
            else "synthetic_mathematical_edge_family"
        )
        for name in corpus
    }
    candidate_results = []
    for multiplier in HORIZON_MULTIPLIERS:
        horizon = _candidate_horizon(route, multiplier)
        candidate_results.append(
            evaluate_candidate(
                route,
                corpus,
                candidate_name=(
                    "minimum_lookback" if multiplier == 1 else f"bounded_x{multiplier}"
                ),
                horizon=horizon,
                required_repository_members=required_repository_members,
                evidence_classes=evidence_classes,
            )
        )
    selected = _select_candidate(
        candidate_results,
        required_repository_members=required_repository_members,
    )
    return {
        "asset": route.asset,
        "timeframe": route.timeframe,
        "resolved_rsi": route.rsi_params,
        "resolved_macd": route.macd_params,
        "momentum_parameters": route.momentum_params,
        "legacy_runtime_resolution": route.legacy_runtime,
        "candidate_results": candidate_results,
        "recommended_candidate": selected,
        "repository_members": list(required_repository_members),
        "restart_sensitivity": evaluate_restart_sensitivity(route, corpus),
        "observed_startup_restart": evaluate_observed_startup_restart(
            route,
            corpus,
        ),
    }


def deterministic_identity_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return identity inputs that intentionally exclude measured errors."""

    return {
        "schema_version": artifact["schema_version"],
        "certification": artifact["certification"],
        "source_sha": artifact["source_sha"],
        "candidate_horizon_multipliers": artifact["candidate_horizon_multipliers"],
        "corpus": artifact["corpus"],
        "route_identities": [
            {
                "asset": route["asset"],
                "timeframe": route["timeframe"],
                "resolved_rsi": route["resolved_rsi"],
                "resolved_macd": route["resolved_macd"],
                "momentum_parameters": route["momentum_parameters"],
            }
            for route in artifact["routes"]
        ],
        "recommendation": artifact["recommendation"],
    }


def measurement_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return all measured evidence covered by the measurement digest."""

    return {
        "routes": artifact["routes"],
        "legacy_config_resolution_discrepancies": artifact[
            "legacy_config_resolution_discrepancies"
        ],
        "resource_and_corpus": artifact["corpus"],
        "barstore_practicality": artifact["barstore_practicality"],
        "recommendation": artifact["recommendation"],
    }


def deterministic_identity_sha256(artifact: dict[str, Any]) -> str:
    return _json_hash(deterministic_identity_payload(artifact))


def measurement_payload_sha256(artifact: dict[str, Any]) -> str:
    return _json_hash(measurement_payload(artifact))


def build_certification(root: Path = ROOT) -> dict[str, Any]:
    routes = resolve_routes(root)
    synthetic_corpus = _corpus_series()
    repository_members = load_repository_market_members(root)
    route_corpora = {
        f"{route.asset}/{route.timeframe}": _route_corpus(
            route,
            synthetic_corpus,
            repository_members,
        )
        for route in routes
    }
    route_artifacts = [
        _route_artifact(
            route,
            route_corpora[f"{route.asset}/{route.timeframe}"],
            repository_members,
        )
        for route in routes
    ]
    member_identities = [
        _repository_member_identity(member, routes) for member in repository_members
    ]
    corpus_identity_payload = {
        "synthetic": {
            "length": CORPUS_LENGTH,
            "families": sorted(synthetic_corpus),
            "identity_sha256": corpus_identity(synthetic_corpus),
        },
        "repository_members": member_identities,
        "route_members": {
            route_id: [
                member["member_id"]
                for member in member_identities
                if member["candidate_eligibility"][route_id]["applicable"]
            ]
            for route_id in route_corpora
        },
    }
    selected = {
        f"{item['asset']}/{item['timeframe']}": item["recommended_candidate"]
        for item in route_artifacts
    }
    barstore_practicality = _barstore_practicality(routes, route_artifacts)
    all_selected = all(value is not None for value in selected.values()) and (
        barstore_practicality["status"] == "PASS"
    )
    discrepancies = {
        f"{item['asset']}/{item['timeframe']}": item["legacy_runtime_resolution"]
        for item in route_artifacts
        if any(
            not entry["matches"]
            for entry in item["legacy_runtime_resolution"]["discrepancy"].values()
        )
    }
    core = {
        "schema_version": SCHEMA_VERSION,
        "certification": "momentum_rsi_macd_canonical_semantics_m3",
        "source_sha": _source_sha(root),
        "routes": route_artifacts,
        "candidate_horizon_multipliers": list(HORIZON_MULTIPLIERS),
        "corpus": {
            "synthetic": corpus_identity_payload["synthetic"],
            "repository_members": member_identities,
            "route_members": corpus_identity_payload["route_members"],
            "identity_sha256": _json_hash(corpus_identity_payload),
            "repository_fixture_used": True,
        },
        "legacy_config_resolution_discrepancies": discrepancies,
        "barstore_practicality": barstore_practicality,
        "recommendation": {
            "outcome": (
                "MOMENTUM_M3_CANONICAL_FEATURE_SEMANTICS_READY_FOR_REVIEW"
                if all_selected
                else "MOMENTUM_M3_STATEFUL_FEATURE_SEMANTICS_REVIEW_REQUIRED"
            ),
            "bounded_stateless_candidate_available_for_every_route": all_selected,
            "selected_candidates": selected,
            "selection_rule": (
                "first bounded candidate with exact zero direction and "
                "tradable/neutral disagreements against full causal-prefix reference; "
                "numeric convergence remains explicitly reported for review"
            ),
        },
        "deferred_gates": [
            "M4 must independently approve and freeze the route-specific resolved parameters and selected histories.",
            "M3 does not register RSI/MACD or Momentum in Decision composition.",
            "signal_app RawIndicatorPipeline sparse-node fallback discrepancy remains unmodified and requires separate downstream treatment.",
        ],
    }
    artifact = {**core, "routes": route_artifacts}
    artifact["deterministic_identity_sha256"] = deterministic_identity_sha256(artifact)
    artifact["measurement_payload_sha256"] = measurement_payload_sha256(artifact)
    return artifact


def write_artifact(
    artifact: dict[str, Any],
    *,
    root: Path = ROOT,
) -> Path:
    path = (
        root
        / "artifacts"
        / "decision_m3"
        / "m3_momentum_feature_semantics_certification.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    artifact = build_certification()
    path = write_artifact(artifact)
    print(
        json.dumps(
            {"artifact": str(path), "status": artifact["recommendation"]["outcome"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
