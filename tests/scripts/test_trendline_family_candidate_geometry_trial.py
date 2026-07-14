from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendline_family.optimization.contracts import OptimizationStage

from scripts import run_trendline_family_candidate_geometry_trial as trial


def _raw_frame(*, rows: int = trial.EXPECTED_ROW_COUNT) -> pd.DataFrame:
    index = pd.date_range(trial.START_UTC, periods=rows, freq="4h", tz="UTC")
    price = pd.Series(range(rows), dtype=float) + 100_000.0
    return pd.DataFrame(
        {
            "timestamp": index.map(lambda value: int(value.timestamp() * 1_000)),
            "open": price,
            "high": price + 10.0,
            "low": price - 10.0,
            "close": price + 1.0,
            "volume": 10.0,
        }
    )


class _Adapter:
    def __init__(self, frame: pd.DataFrame, *, input_directory: Path | None = None) -> None:
        self.frame = frame
        self.input_directory = input_directory
        self.calls: list[tuple[object, ...]] = []

    async def get_historical_ohlcv(self, symbol, timeframe, since=None, until=None, limit=None):
        if self.input_directory is not None:
            assert self.input_directory.is_dir()
        self.calls.append((symbol, timeframe, since, until, limit))
        return self.frame.copy(deep=True)


def test_fixed_request_is_one_binance_call() -> None:
    adapter = _Adapter(_raw_frame())
    returned = asyncio.run(trial.fetch_bounded_ohlcv(adapter))
    assert len(adapter.calls) == 1
    assert adapter.calls[0] == (
        "BTCUSDT",
        "4h",
        1_754_006_400_000,
        1_764_547_200_000,
        1000,
    )
    assert len(returned) == trial.EXPECTED_ROW_COUNT


def test_normalize_and_preflight_requires_exact_confirmed_window() -> None:
    dataset = trial.normalize_and_preflight(_raw_frame())
    assert dataset.row_count == 732
    assert dataset.timestamps[0] == trial.START_UTC
    assert dataset.timestamps[-1].isoformat() == "2025-11-30T20:00:00+00:00"

    gapped = _raw_frame().drop(index=80).reset_index(drop=True)
    with pytest.raises(trial.TrialPreflightError, match="row count mismatch"):
        trial.normalize_and_preflight(gapped)

    invalid = _raw_frame()
    invalid.loc[2, "high"] = invalid.loc[2, "open"] - 1.0
    with pytest.raises(trial.TrialPreflightError, match="high below"):
        trial.normalize_and_preflight(invalid)


def test_resolved_config_and_fixed_fold_grid_have_approved_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = trial.CONFIG_PATH.read_bytes()
    config = trial.resolve_baseline_config()
    assert trial.CONFIG_PATH.read_bytes() == before
    assert config.asset == "BTCUSDT"
    assert config.timeframe == "4h"
    assert config.candidate.lookback_bars == 180
    dataset = trial.normalize_and_preflight(_raw_frame())
    plan = trial.build_fixed_fold_plan(dataset)
    trial.validate_fixed_trial_spec(dataset, plan)
    assert len(plan.folds) == 3
    assert plan.holdout.window.bar_count == 96
    assert plan.label_horizon_bars == 12
    assert trial.objective_spec().primary_metric == "reaction_quality"
    assert trial.outcome_policy().policy_version == "candidate_structural_outcome_btcusdt_4h_v1"
    assert trial.objective_spec().objective_version == "candidate_geometry_reaction_btcusdt_4h_v1"
    assert trial.SEARCH_SPACE == {
        "candidate.lookback_bars": (120, 180, 240),
        "candidate.min_candidate_quality": (0.30, 0.40),
    }

    drifted = replace(config, candidate=replace(config.candidate, lookback_bars=181))
    class _Resolver:
        def resolve(self, *, asset: str, timeframe: str):
            return drifted

    monkeypatch.setattr(
        trial.TrendlineFamilyConfigResolver,
        "from_path",
        classmethod(lambda cls, path: _Resolver()),
    )
    with pytest.raises(trial.TrialPreflightError, match="config drift"):
        trial.resolve_baseline_config()


def test_phase_i_call_is_fixed_to_candidate_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset = trial.normalize_and_preflight(_raw_frame())
    config = trial.resolve_baseline_config()
    plan = trial.build_fixed_fold_plan(dataset)
    evaluator = object()
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(trial, "run_phase_i_evaluation", fake_runner)
    trial._run_phase_i(
        trial_root=tmp_path,
        dataset=dataset,
        config=config,
        fold_plan=plan,
        evaluator=evaluator,
    )
    assert captured["stage"] is OptimizationStage.CANDIDATE_GEOMETRY
    assert captured["search_space"] == trial.SEARCH_SPACE
    assert captured["maximum_trial_count"] == 6
    assert captured["seed"] == 0
    assert captured["open_holdout"] is True
    assert captured["codebase_project"] == "Users-aloobhujia-flipperAgent"
    assert captured["objective"].primary_metric == "reaction_quality"


def test_trial_root_reuse_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "fixed"
    trial.prepare_trial_root(root)
    scope = json.loads((root / "execution_scope.json").read_text())
    assert (root / "input").is_dir()
    assert scope == {
        "asset": "BTCUSDT",
        "authorization_id": "trendline_family_candidate_geometry_retry_v2",
        "end": "2025-12-01T00:00:00Z",
        "execution_attempt": 2,
        "market": "Binance USD-M Futures",
        "phase_i_semantics_unchanged": True,
        "previous_attempt_status": "local_persistence_failure_before_normalization",
        "single_execution": True,
        "start": "2025-08-01T00:00:00Z",
        "supersedes_trial_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v1",
        "timeframe": "4h",
        "trial_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v2",
    }
    with pytest.raises(trial.TrialPreflightError, match="refusing rerun"):
        trial.prepare_trial_root(root)


def test_v2_identity_does_not_select_or_modify_exhausted_v1_root(tmp_path: Path) -> None:
    before = (trial.V1_TRIAL_ROOT / "execution_scope.json").read_bytes()
    assert trial.TRIAL_NAME == "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
    assert trial.TRIAL_ROOT.name == trial.TRIAL_NAME
    assert trial.TRIAL_ROOT != trial.V1_TRIAL_ROOT
    trial.prepare_trial_root(tmp_path / trial.TRIAL_NAME)
    assert (trial.V1_TRIAL_ROOT / "execution_scope.json").read_bytes() == before


def test_raw_and_normalized_persistence_are_atomic_and_hash_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "v2"
    trial.prepare_trial_root(root)
    dataset = trial.normalize_and_preflight(_raw_frame())
    config = trial.resolve_baseline_config()
    replacements: list[tuple[Path, Path]] = []
    original_replace = trial.os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(trial.os, "replace", recording_replace)
    raw = _raw_frame()
    raw_manifest = trial.persist_raw_fetch_evidence(trial_root=root, raw=raw)
    input_manifest = trial.persist_input(trial_root=root, dataset=dataset, config=config)

    raw_path = root / "input" / raw_manifest["raw_response_file"]
    normalized_path = root / "input" / input_manifest["normalized_input_file"]
    assert sha256(raw_path.read_bytes()).hexdigest() == raw_manifest["raw_response_sha256"]
    assert sha256(normalized_path.read_bytes()).hexdigest() == input_manifest["normalized_input_sha256"]
    assert raw_manifest["trial_name"] == trial.TRIAL_NAME
    assert raw_manifest["execution_attempt"] == 2
    assert raw_manifest["authorization_id"] == trial.AUTHORIZATION_ID
    assert input_manifest["trial_name"] == trial.TRIAL_NAME
    assert input_manifest["execution_attempt"] == 2
    assert input_manifest["authorization_id"] == trial.AUTHORIZATION_ID
    destinations = {destination for _, destination in replacements}
    assert raw_path in destinations
    assert normalized_path in destinations
    for source, destination in replacements:
        assert source.parent == destination.parent
        assert source.name.startswith(f".{destination.name}.")

    with pytest.raises(trial.TrialPreflightError, match="refusing to overwrite"):
        trial.persist_raw_fetch_evidence(trial_root=root, raw=raw)
    with pytest.raises(trial.TrialPreflightError, match="refusing to overwrite"):
        trial.persist_input(trial_root=root, dataset=dataset, config=config)


def test_mocked_runner_prepares_input_before_exactly_one_adapter_call_and_persists_both_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / trial.TRIAL_NAME
    adapter = _Adapter(_raw_frame(), input_directory=root / "input")
    factory_calls = 0

    def adapter_factory() -> _Adapter:
        nonlocal factory_calls
        factory_calls += 1
        assert (root / "input").is_dir()
        return adapter

    def fake_phase_i(**kwargs) -> object:
        assert (root / "input" / "raw_binance_response.csv").is_file()
        assert (root / "input" / "normalized_ohlcv.csv").is_file()
        assert kwargs["fold_plan"].holdout.window.bar_count == 96
        assert kwargs["evaluator"].outcome_policy.policy_version == (
            "candidate_structural_outcome_btcusdt_4h_v1"
        )
        return object()

    def fake_report(*, trial_root: Path, input_manifest, browser) -> Path:
        assert (trial_root / "input" / "raw_fetch_manifest.json").is_file()
        assert (trial_root / "input" / "input_manifest.json").is_file()
        return trial_root / "trial_report.md"

    monkeypatch.setattr(trial, "_run_phase_i", fake_phase_i)
    monkeypatch.setattr(trial, "load_verified_phase_i_artifacts", lambda path: object())
    monkeypatch.setattr(trial, "write_trial_report", fake_report)

    paths = asyncio.run(trial.run_trial(adapter_factory=adapter_factory, trial_root=root))

    assert factory_calls == 1
    assert len(adapter.calls) == 1
    assert paths["input_manifest"].is_file()
    assert (root / "input" / "raw_binance_response.csv").is_file()
    assert (root / "input" / "normalized_ohlcv.csv").is_file()
