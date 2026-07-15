from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from libs.models.sr import ContractValidationError, SRStateKey
from libs.models.sr.scripts.baseline_trial.config import load_trial_config, load_and_resolve_input_config
from libs.models.sr.scripts.baseline_trial.dataset import (
    DAY_MS,
    build_model_bars,
    fetch_validated_dataset,
    validate_raw_dataset,
)


_ROOT = Path(__file__).parents[5]
_TRIAL = load_trial_config(_ROOT / "configs/sr_trials/taousdt_1d_baseline.yaml")
_INPUT = load_and_resolve_input_config(
    _ROOT / "configs/sr_inputs.yaml", asset=_TRIAL.symbol, timeframe=_TRIAL.timeframe
)


def _frame(count: int = 20, *, start_ms: int = 1704067200000) -> pd.DataFrame:
    rows = []
    for index in range(count):
        timestamp = start_ms + index * DAY_MS
        price = 100.0 + index * 0.1
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price + 0.5,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_valid_dataset_preserves_source_order_and_identity() -> None:
    dataset = validate_raw_dataset(_frame(), _TRIAL)

    assert dataset.raw_row_count == 20
    assert dataset.actual_since == _TRIAL.requested_since
    assert dataset.bars[0].bar_id == "binance_usdm:TAOUSDT:1d:1704067200000"
    assert dataset.bars[-1].closed_at == dataset.bars[-1].open_time + timedelta(days=1)
    assert dataset.bars[0].volume == 10.0


@pytest.mark.parametrize(
    ("mutator", "message"),
    (
        (lambda frame: frame.drop(columns=["volume"]), "missing"),
        (lambda frame: frame.assign(timestamp=frame.timestamp.astype(float)), "integer"),
        (lambda frame: frame.assign(open=0.0), "positive"),
        (lambda frame: frame.assign(low=frame.high + 1.0), "OHLC"),
        (lambda frame: frame.assign(volume=float("inf")), "finite"),
    ),
)
def test_invalid_source_values_fail_closed(mutator, message: str) -> None:
    frame = _frame()
    changed = mutator(frame)
    with pytest.raises(ContractValidationError, match=message):
        validate_raw_dataset(changed, _TRIAL)


def test_duplicate_out_of_order_and_gapped_rows_are_not_repaired() -> None:
    duplicate = _frame()
    duplicate.loc[1, "timestamp"] = duplicate.loc[0, "timestamp"]
    with pytest.raises(ContractValidationError, match="increasing"):
        validate_raw_dataset(duplicate, _TRIAL)

    out_of_order = _frame()
    out_of_order.loc[2, "timestamp"] = out_of_order.loc[1, "timestamp"] - 1
    with pytest.raises(ContractValidationError, match="increasing"):
        validate_raw_dataset(out_of_order, _TRIAL)

    gapped = _frame()
    gapped.loc[1, "timestamp"] += DAY_MS
    with pytest.raises(ContractValidationError, match="gap"):
        validate_raw_dataset(gapped, _TRIAL)


def test_later_listing_start_is_recorded_without_backfilling() -> None:
    frame = _frame(start_ms=1704067200000 + 3 * DAY_MS)
    dataset = validate_raw_dataset(frame, _TRIAL)
    assert dataset.actual_since == _TRIAL.requested_since + timedelta(days=3)
    assert dataset.raw_row_count == 20


def test_cutoff_and_adapter_limit_reject_open_or_truncated_data() -> None:
    june_30 = _frame(
        1,
        start_ms=int(_TRIAL.requested_until.timestamp() * 1000) - DAY_MS,
    )
    dataset = validate_raw_dataset(june_30, _TRIAL)
    assert dataset.bars[0].closed_at == _TRIAL.requested_until

    july_1 = _frame(
        1,
        start_ms=int(_TRIAL.requested_until.timestamp() * 1000),
    )
    with pytest.raises(ContractValidationError, match="open_time"):
        validate_raw_dataset(july_1, _TRIAL)

    truncated = _frame(1500)
    with pytest.raises(ContractValidationError, match="adapter_limit"):
        validate_raw_dataset(truncated, _TRIAL)


def test_adapter_is_called_once_with_frozen_request() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.calls = []

        async def get_historical_ohlcv(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return _frame()

    adapter = FakeAdapter()
    dataset = asyncio.run(fetch_validated_dataset(adapter, _TRIAL))

    assert dataset.raw_row_count == 20
    assert len(adapter.calls) == 1
    args, kwargs = adapter.calls[0]
    assert args == ("TAOUSDT", "1d")
    assert kwargs == {
        "since": int(_TRIAL.requested_since.timestamp() * 1000),
        "until": int(_TRIAL.requested_until.timestamp() * 1000) - 1,
        "limit": 1500,
    }


def test_closed_bar_mapping_uses_exact_state_key_and_atr_warmup() -> None:
    dataset = validate_raw_dataset(_frame(), _TRIAL)
    model_bars, provenance = build_model_bars(dataset, _INPUT, _TRIAL)

    assert model_bars
    assert all(bar.state_key == SRStateKey("binance_usdm", "TAOUSDT", "1d") for bar in model_bars)
    assert model_bars[0].bar_id == dataset.bars[14].bar_id
    assert provenance.warmup_count == 14
    assert provenance.model_bar_count == 6
    assert provenance.first_valid_at == model_bars[0].closed_at
    assert provenance.first_valid_at == dataset.bars[14].closed_at
