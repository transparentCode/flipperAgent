"""Frozen semantic, legacy, and batch regressions for Momentum."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from libs.contracts.signal import FeatureVector
from libs.contracts.strategy_model import ModelExecutionContext
from libs.models.momentum import (
    MomentumConfig,
    MomentumModel,
    MomentumObservation,
    MomentumResult,
    evaluate_momentum,
)
from libs.models.momentum.strategy_v2 import MomentumV2


def _active_momentum_params() -> list[tuple[str, str, dict[str, object]]]:
    repository_root = Path(__file__).resolve().parents[3]
    result: list[tuple[str, str, dict[str, object]]] = []
    assets_root = repository_root / "configs" / "decision" / "assets"
    for asset_file in sorted(assets_root.glob("*.yaml")):
        document = yaml.safe_load(asset_file.read_text(encoding="utf-8")) or {}
        decision_asset = document.get("decision_asset")
        lanes = document.get("lanes", {})
        for lane in lanes.values():
            timeframe = lane.get("decision_timeframe")
            primary = (lane.get("bindings") or {}).get("primary") or {}
            if primary.get("plugin") != "momentum":
                continue
            parameters = primary.get("parameters") or {}
            result.append((decision_asset, timeframe, parameters.get("model", {})))
    return result


def _feature_vector(
    *, rsi: object, histogram: object, line: object = 0.3
) -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        features={
            "RSI": {"value": rsi},
            "MACD": {"histogram": histogram, "line": line},
        },
        bar_data={"close": 100.0},
    )


def _scalar_direction(
    config: MomentumConfig,
    *,
    rsi: object,
    histogram: object,
    line: object = None,
) -> int:
    try:
        observation = MomentumObservation(
            rsi=rsi,
            macd_histogram=histogram,
            macd_line=line,
        )
        return evaluate_momentum(observation, config).direction
    except (TypeError, ValueError):
        return 0


def test_defaults_and_active_legacy_configuration_maps_are_frozen() -> None:
    assert MomentumConfig().to_mapping() == {
        "rsi_long_threshold": 55,
        "rsi_short_threshold": 45,
        "require_macd_positive": False,
        "histogram_min_abs": 0.0,
    }
    observed = [
        (asset, timeframe, MomentumConfig.from_mapping(params).to_mapping())
        for asset, timeframe, params in _active_momentum_params()
    ]
    assert observed == [
        (
            "BTCUSDT",
            "1h",
            {
                "rsi_long_threshold": 70,
                "rsi_short_threshold": 34,
                "require_macd_positive": True,
                "histogram_min_abs": 0.7,
            },
        ),
        (
            "BTCUSDT",
            "4h",
            {
                "rsi_long_threshold": 61,
                "rsi_short_threshold": 37,
                "require_macd_positive": True,
                "histogram_min_abs": 0.35,
            },
        ),
        (
            "ETHUSDT",
            "4h",
            {
                "rsi_long_threshold": 55,
                "rsi_short_threshold": 45,
                "require_macd_positive": False,
                "histogram_min_abs": 0.0,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rsi_long_threshold", True),
        ("rsi_short_threshold", 45.0),
        ("require_macd_positive", 1),
        ("histogram_min_abs", float("nan")),
        ("histogram_min_abs", float("inf")),
        ("histogram_min_abs", -0.1),
    ],
)
def test_config_rejects_strict_type_and_domain_errors(
    field: str, value: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        MomentumConfig.from_mapping({field: value})


def test_config_rejects_unknown_keys_and_invalid_threshold_order() -> None:
    with pytest.raises(ValueError, match="unknown"):
        MomentumConfig.from_mapping({"unexpected": 1})
    with pytest.raises(ValueError, match="unknown"):
        MomentumModel({"unexpected": 1})
    with pytest.raises(ValueError, match="between 0 and 100"):
        MomentumConfig(rsi_long_threshold=101)
    with pytest.raises(ValueError, match="must be less"):
        MomentumConfig(rsi_long_threshold=45, rsi_short_threshold=45)


def test_config_and_core_types_are_immutable() -> None:
    config = MomentumConfig()
    observation = MomentumObservation(rsi=60.0, macd_histogram=0.5)
    with pytest.raises(FrozenInstanceError):
        config.rsi_long_threshold = 60  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        observation.rsi = 61.0  # type: ignore[misc]


def test_result_enforces_direction_conviction_score_invariant() -> None:
    with pytest.raises(ValueError, match="score"):
        MomentumResult(direction=1, conviction=0.2, score=-0.2)
    with pytest.raises(ValueError, match="neutral"):
        MomentumResult(direction=0, conviction=0.2, score=0.0)


@pytest.mark.parametrize(
    "observation",
    [
        {"rsi": float("nan"), "macd_histogram": 0.5},
        {"rsi": float("inf"), "macd_histogram": 0.5},
        {"rsi": -0.1, "macd_histogram": 0.5},
        {"rsi": 100.1, "macd_histogram": 0.5},
        {"rsi": True, "macd_histogram": 0.5},
        {"rsi": 60.0, "macd_histogram": float("nan")},
        {"rsi": 60.0, "macd_histogram": 0.5, "macd_line": float("inf")},
    ],
)
def test_observation_rejects_malformed_values(observation: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        MomentumObservation(**observation)


GOLDEN_CASES = (
    (
        "default-long",
        MomentumConfig(),
        MomentumObservation(rsi=60.0, macd_histogram=0.5, macd_line=0.3),
        MomentumResult(direction=1, conviction=0.2, score=0.2),
    ),
    (
        "default-short",
        MomentumConfig(),
        MomentumObservation(rsi=40.0, macd_histogram=-0.5, macd_line=-0.3),
        MomentumResult(direction=-1, conviction=0.2, score=-0.2),
    ),
    (
        "btc-1h-long",
        MomentumConfig(
            rsi_long_threshold=70,
            rsi_short_threshold=34,
            require_macd_positive=True,
            histogram_min_abs=0.7,
        ),
        MomentumObservation(rsi=71.0, macd_histogram=0.7, macd_line=0.1),
        MomentumResult(direction=1, conviction=0.42, score=0.42),
    ),
    (
        "btc-4h-short",
        MomentumConfig(
            rsi_long_threshold=61,
            rsi_short_threshold=37,
            require_macd_positive=True,
            histogram_min_abs=0.35,
        ),
        MomentumObservation(rsi=36.0, macd_histogram=-0.35, macd_line=-0.1),
        MomentumResult(direction=-1, conviction=0.28, score=-0.28),
    ),
    (
        "threshold-equality-neutral",
        MomentumConfig(),
        MomentumObservation(rsi=55.0, macd_histogram=0.5, macd_line=0.3),
        MomentumResult.neutral(),
    ),
)


@pytest.mark.parametrize("name, config, observation, expected", GOLDEN_CASES)
def test_frozen_valid_finite_golden_outputs(
    name: str,
    config: MomentumConfig,
    observation: MomentumObservation,
    expected: MomentumResult,
) -> None:
    del name
    assert evaluate_momentum(observation, config) == expected


@pytest.mark.parametrize(
    ("rsi", "histogram", "line"),
    [
        (55.0, 0.5, 0.3),
        (45.0, -0.5, -0.3),
        (60.0, 0.0, 0.3),
        (60.0, 0.5, 0.0),
        (40.0, -0.5, 0.0),
        (60.0, 0.5, None),
    ],
)
def test_boundary_matrix_matches_frozen_rule(
    rsi: float, histogram: float, line: float | None
) -> None:
    config = MomentumConfig(require_macd_positive=True, histogram_min_abs=0.5)
    result = evaluate_momentum(
        MomentumObservation(rsi=rsi, macd_histogram=histogram, macd_line=line),
        config,
    )
    assert result.direction == 0


def test_legacy_model_matches_golden_valid_outputs() -> None:
    config = MomentumConfig(
        rsi_long_threshold=70,
        rsi_short_threshold=34,
        require_macd_positive=True,
        histogram_min_abs=0.7,
    )
    output = MomentumModel(config.to_mapping()).evaluate(
        _feature_vector(rsi=71.0, histogram=0.7, line=0.1)
    )
    assert (output.direction, output.conviction) == (1, 0.42)
    assert output.metadata == {"rsi": 71.0, "macd_histogram": 0.7}


def test_legacy_invalid_evidence_fails_closed() -> None:
    model = MomentumModel({"require_macd_positive": True})
    for values in (
        {"rsi": float("nan"), "histogram": 0.5, "line": 0.5},
        {"rsi": 101.0, "histogram": 0.5, "line": 0.5},
        {"rsi": 60.0, "histogram": float("inf"), "line": 0.5},
        {"rsi": 60.0, "histogram": 0.5, "line": None},
    ):
        assert model.evaluate(_feature_vector(**values)).direction == 0


def test_momentum_v2_preserves_core_score_and_metadata() -> None:
    model = MomentumV2(
        {
            "rsi_long_threshold": 55,
            "rsi_short_threshold": 45,
            "require_macd_positive": False,
            "histogram_min_abs": 0.0,
        }
    )
    decision = model.evaluate(
        ModelExecutionContext(
            feature_vector=_feature_vector(rsi=60.0, histogram=0.5, line=0.3)
        )
    )
    assert decision.model_name == "MomentumV2"
    assert decision.direction_hint == 1
    assert decision.conviction == 0.2
    assert decision.score == 0.2
    assert decision.metadata == {"rsi": 60.0, "macd_histogram": 0.5}


def test_scalar_and_batch_directions_are_identical() -> None:
    config = MomentumConfig(
        rsi_long_threshold=55,
        rsi_short_threshold=45,
        require_macd_positive=True,
        histogram_min_abs=0.5,
    )
    rows = [
        (60.0, 0.5, 0.3),
        (Decimal(60), Decimal("0.5"), Decimal("0.3")),
        (60, Decimal("0.5"), 0.3),
        (55.0, 0.5, 0.3),
        (40.0, -0.5, -0.3),
        (45.0, -0.5, -0.3),
        (60.0, 0.0, 0.3),
        (60.0, 0.5, 0.0),
        (True, 0.5, 0.3),
        (float("nan"), 0.5, 0.3),
        (60.0, Decimal("NaN"), 0.3),
        (101.0, 0.5, 0.3),
        (Decimal(-1), 0.5, 0.3),
        (60.0, float("inf"), 0.3),
        (60.0, 0.5, -0.3),
    ]
    frame = pd.DataFrame(rows, columns=["RSI", "MACD_histogram", "MACD_line"])
    model = MomentumModel(config.to_mapping())
    actual = list(model.batch_evaluate(frame))
    expected = [
        model.evaluate(
            _feature_vector(rsi=rsi, histogram=histogram, line=line)
        ).direction
        for rsi, histogram, line in rows
    ]
    assert actual == expected


def test_required_macd_line_missing_in_batch_fails_closed() -> None:
    model = MomentumModel(
        {
            "rsi_long_threshold": 55,
            "rsi_short_threshold": 45,
            "require_macd_positive": True,
        }
    )
    frame = pd.DataFrame(
        {"RSI": [60.0, 40.0], "MACD_histogram": [0.5, -0.5]},
        index=pd.date_range("2024-01-01", periods=2, tz=UTC),
    )
    assert list(model.batch_evaluate(frame)) == [0, 0]


def test_batch_contract_still_rejects_non_monotonic_index() -> None:
    model = MomentumModel({})
    frame = pd.DataFrame(
        {
            "RSI": [60.0, 40.0],
            "MACD_histogram": [0.5, -0.5],
            "MACD_line": [0.3, -0.3],
        },
        index=[2, 1],
    )
    with pytest.raises(ValueError, match="temporal ordering"):
        model.batch_evaluate(frame)
