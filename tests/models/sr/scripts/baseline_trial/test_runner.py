from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import shutil

import pytest

from libs.models.sr import ContractValidationError
from libs.models.sr.scripts.baseline_trial.config import load_trial_config
from libs.models.sr.scripts.baseline_trial.dataset import _timestamp_to_ms
from libs.models.sr.scripts.baseline_trial.runner import run_trial

from .test_dataset import _frame


_ROOT = Path(__file__).parents[5]


class _FakeAdapter:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    async def get_historical_ohlcv(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.frame


def _trial(output_root: str):
    return replace(
        load_trial_config(_ROOT / "configs/sr_trials/taousdt_1d_baseline.yaml"),
        output_root=output_root,
    )


def test_runner_fetches_once_replays_once_and_binds_all_identities(monkeypatch) -> None:
    import libs.models.sr.scripts.baseline_trial.runner as runner_module

    adapter = _FakeAdapter(_frame())
    trial = _trial("research/tmp_sr_v1_5_runner_test")
    calls = {"replay": 0}
    replay = runner_module.replay_bars

    def counted_replay(*args, **kwargs):
        calls["replay"] += 1
        return replay(*args, **kwargs)

    monkeypatch.setattr(runner_module, "replay_bars", counted_replay)
    try:
        result, publication = asyncio.run(
            run_trial(
                trial,
                repo_root=_ROOT,
                adapter=adapter,
                implementation_commit="a" * 40,
            )
        )
    finally:
        shutil.rmtree(_ROOT / trial.output_root, ignore_errors=True)

    assert len(adapter.calls) == 1
    assert calls["replay"] == 1
    assert result.trace.config_hash == result.resolved_sr_config.resolved_config_hash
    assert result.diagnostics.trace_id == result.trace.trace_id
    assert publication.manifest.resolved_input.resolved_input_hash == (
        result.resolved_input.resolved_input_hash
    )


def test_runner_passes_frozen_epoch_milliseconds_to_provider() -> None:
    trial = _trial("research/tmp_sr_v1_5_runner_args_test")
    adapter = _FakeAdapter(_frame())
    try:
        asyncio.run(
            run_trial(
                trial,
                repo_root=_ROOT,
                adapter=adapter,
                implementation_commit="b" * 40,
            )
        )
    finally:
        shutil.rmtree(_ROOT / trial.output_root, ignore_errors=True)

    args, kwargs = adapter.calls[0]
    assert args == ("TAOUSDT", "1d")
    assert kwargs["since"] == _timestamp_to_ms(trial.requested_since)
    assert kwargs["until"] == _timestamp_to_ms(trial.requested_until) - 1
    assert kwargs["limit"] == 1500


def test_trial_result_rejects_atr_timestamp_before_model_bar_close() -> None:
    trial = _trial("research/tmp_sr_v1_5_atr_timestamp_test")
    adapter = _FakeAdapter(_frame())
    try:
        result, _ = asyncio.run(
            run_trial(
                trial,
                repo_root=_ROOT,
                adapter=adapter,
                implementation_commit="e" * 40,
            )
        )
        invalid_atr = replace(
            result.atr,
            first_valid_at=result.model_bars[0].closed_at - timedelta(days=1),
        )
        with pytest.raises(ContractValidationError, match="first_valid_at"):
            replace(result, atr=invalid_atr)
    finally:
        shutil.rmtree(_ROOT / trial.output_root, ignore_errors=True)
