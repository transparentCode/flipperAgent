from __future__ import annotations

from pathlib import Path

from libs.features.indicators.volatility.atr import ATR
from libs.models.sr.scripts.baseline_trial.config import load_and_resolve_input_config, load_trial_config
from libs.models.sr.scripts.baseline_trial.dataset import build_model_bars, validate_raw_dataset

from .test_dataset import _frame


_ROOT = Path(__file__).parents[5]
_TRIAL = load_trial_config(_ROOT / "configs/sr_trials/taousdt_1d_baseline.yaml")
_INPUT = load_and_resolve_input_config(
    _ROOT / "configs/sr_inputs.yaml", asset=_TRIAL.symbol, timeframe=_TRIAL.timeframe
)


def test_existing_atr_has_sma_seed_and_fourteen_value_warmup() -> None:
    frame = _frame(20)
    values = ATR(period=14).batch(
        tuple(zip(frame.high, frame.low, frame.close))
    )

    assert len(values) == 20
    assert all(value is None for value in values[:14])
    assert values[14] is not None and values[14] > 0


def test_atr_prefixes_match_full_run_exactly() -> None:
    full = validate_raw_dataset(_frame(30), _TRIAL)
    full_bars, _ = build_model_bars(full, _INPUT, _TRIAL)

    for count in range(15, 31):
        prefix = validate_raw_dataset(_frame(count), _TRIAL)
        prefix_bars, _ = build_model_bars(prefix, _INPUT, _TRIAL)
        assert prefix_bars == full_bars[: len(prefix_bars)]


def test_later_source_changes_cannot_rewrite_earlier_atr_or_closed_bars() -> None:
    baseline = _frame(25)
    changed = baseline.copy()
    changed.loc[24, "high"] += 1000.0
    changed.loc[24, "close"] += 500.0

    baseline_bars, _ = build_model_bars(
        validate_raw_dataset(baseline, _TRIAL), _INPUT, _TRIAL
    )
    changed_bars, _ = build_model_bars(
        validate_raw_dataset(changed, _TRIAL), _INPUT, _TRIAL
    )

    assert changed_bars[:-1] == baseline_bars[:-1]
