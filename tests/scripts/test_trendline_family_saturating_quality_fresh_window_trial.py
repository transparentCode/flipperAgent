from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
import inspect
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from libs.models.trendline_family.contracts import (
    AnchorRef,
    FamilyRole,
    LineCandidate,
    LineDiagnostics,
    LineGeometry,
)
from libs.models.trendline_family.optimization.candidate_optimizer import CandidateGeometryEvaluator
from libs.models.trendline_family.optimization.contracts import TrialStatus
from libs.models.trendline_family.provider import (
    CandidateGenerationResult,
    CandidateGenerationStatus,
)
from scripts import run_trendline_family_saturating_quality_fresh_window_trial as trial


def _raw_frame(*, rows: int = trial.EXPECTED_ROW_COUNT) -> pd.DataFrame:
    index = pd.date_range(trial.START_UTC, periods=rows, freq="4h", tz="UTC")
    close = [100_000.0 + float(position) + float(position % 7) * 0.1 for position in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": index.map(lambda value: int(value.timestamp() * 1_000)),
            "open": [value - 0.5 for value in close],
            "high": [value + 4.0 for value in close],
            "low": [value - 4.0 for value in close],
            "close": close,
            "volume": [10.0 + float(position) for position in range(rows)],
        }
    )


def _dataset():
    return trial.normalize_and_preflight(_raw_frame())


def _candidate(*, config, ohlcv: pd.DataFrame, observed_at, role: FamilyRole = FamilyRole.SUPPORT) -> LineCandidate:
    first = ohlcv.index[-25].to_pydatetime()
    second = ohlcv.index[-13].to_pydatetime()
    first_price = float(ohlcv.iloc[-25].close)
    second_price = float(ohlcv.iloc[-13].close)
    geometry = LineGeometry(
        reference_time=first,
        reference_price=first_price,
        slope_per_second=(second_price - first_price) / (second - first).total_seconds(),
    )
    pivot_kind = "low" if role is FamilyRole.SUPPORT else "high"
    return LineCandidate(
        candidate_id=f"fixture-{role.value.lower()}-{observed_at.isoformat()}",
        asset=config.asset,
        timeframe=config.timeframe,
        observed_at=observed_at,
        geometry=geometry,
        anchors=(
            AnchorRef("anchor-first", first, first_price, pivot_kind, first),
            AnchorRef("anchor-second", second, second_price, pivot_kind, second),
        ),
        role=role,
        method="pathfinding",
        provider="native_deterministic",
        diagnostics=LineDiagnostics(0.8, 0.8, 2, 2, 12.0 / 179.0),
        source_line_index=0,
        metadata={"path_length": 2, "quality_method": "anchor_span_coverage_v1"},
    )


class _Adapter:
    def __init__(self, frame: pd.DataFrame, *, required_input_directory: Path | None = None) -> None:
        self.frame = frame
        self.required_input_directory = required_input_directory
        self.calls: list[tuple[object, ...]] = []

    async def get_historical_ohlcv(self, symbol, timeframe, since=None, until=None, limit=None):
        if self.required_input_directory is not None:
            assert self.required_input_directory.is_dir()
        self.calls.append((symbol, timeframe, since, until, limit))
        return self.frame.copy(deep=True)


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def generate(self, ohlcv, *, asset, timeframe, observed_at, config, context=None):
        del context
        assert asset == trial.ASSET
        assert timeframe == trial.TIMEFRAME
        assert ohlcv.index[-1].to_pydatetime() == observed_at
        self.calls.append((len(ohlcv), observed_at))
        candidate = _candidate(config=config, ohlcv=ohlcv, observed_at=observed_at)
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.VALID,
            candidates=(candidate,),
            reason_codes=(),
            metadata={"fixture": "recording-provider"},
        )


class _FailIfCalledProvider:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("holdout provider must not run without a finalist freeze")


def _resolved_configs():
    baseline = trial.resolve_baseline_config()
    return baseline, trial.research_generation_config(baseline)


def test_fixed_request_and_normalized_window_are_exact() -> None:
    adapter = _Adapter(_raw_frame())
    returned = asyncio.run(trial.fetch_bounded_ohlcv(adapter))
    assert adapter.calls == [("BTCUSDT", "4h", 1_764_547_200_000, 1_775_001_600_000, 1000)]
    assert len(returned) == trial.EXPECTED_ROW_COUNT

    dataset = trial.normalize_and_preflight(returned)
    assert dataset.row_count == 726
    assert dataset.timestamps[0] == trial.START_UTC
    assert dataset.timestamps[-1].isoformat() == "2026-03-31T20:00:00+00:00"

    with pytest.raises(trial.FreshWindowTrialError, match="row count mismatch"):
        trial.normalize_and_preflight(_raw_frame(rows=725))


def test_config_identity_and_research_override_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline, research = _resolved_configs()
    assert baseline.resolved_config_hash == trial.EXPECTED_RESOLVED_CONFIG_HASH
    assert research.candidate.lookback_bars == 180
    assert research.candidate.min_candidate_quality == 0.0
    changed = {
        key: value
        for key, value in asdict(research.candidate).items()
        if asdict(baseline.candidate)[key] != value
    }
    assert changed == {"min_candidate_quality": 0.0}

    drifted = replace(baseline, candidate=replace(baseline.candidate, lookback_bars=181))

    class _Resolver:
        def resolve(self, *, asset: str, timeframe: str):
            assert (asset, timeframe) == (trial.ASSET, trial.TIMEFRAME)
            return drifted

    monkeypatch.setattr(
        trial.TrendlineFamilyConfigResolver,
        "from_path",
        classmethod(lambda _cls, _path: _Resolver()),
    )
    with pytest.raises(trial.FreshWindowTrialError, match="resolved canonical"):
        trial.resolve_baseline_config()


def test_fixed_fold_formula_policy_and_objective_contracts() -> None:
    dataset = _dataset()
    _, research = _resolved_configs()
    plan = trial.build_fixed_fold_plan(dataset)
    trial.validate_fixed_fold_plan(dataset, plan)
    assert tuple(
        (fold.fold_index, fold.validation.start_position, fold.validation.end_position)
        for fold in plan.folds
    ) == trial.VALIDATION_BOUNDS
    assert (plan.holdout.window.start_position, plan.holdout.window.end_position) == trial.HOLDOUT_BOUNDS
    assert plan.holdout.warmup.end_position == 629
    assert trial.objective_spec().to_dict() == {
        "objective_version": "candidate_saturating_quality_reaction_btcusdt_4h_v1",
        "primary_metric": "reaction_quality",
        "maximize": True,
        "minimum_sample_count": 100,
        "minimum_fold_coverage": 1.0,
        "maximum_failure_rate": 0.0,
        "allowed_degradation": 0.0,
        "require_comparable_population": True,
        "worst_window_floor": None,
        "worst_window_ceiling": None,
        "maximum_latency_ms": None,
        "maximum_churn_rate": None,
    }
    assert trial.outcome_policy().to_dict()["policy_version"] == trial.OUTCOME_POLICY_VERSION

    spec = trial.evaluation_spec(research_config=research, provider_identity="fixture.provider")
    baseline, primary = trial.build_trial_configs(
        dataset=dataset,
        fold_plan=plan,
        research_config=research,
        spec=spec,
    )
    assert baseline.evaluation_context == {"quality_policy_id": "threshold_zero_candidate_control_v1"}
    assert [item.evaluation_context["horizon_bars"] for item in primary] == [12, 24, 48, 96]
    assert all(item.evaluation_context["score_threshold"] == "0.50" for item in primary)

    for horizon in trial.HORIZONS:
        for span in (1, horizon - 1, horizon, horizon + 1, 511):
            score = trial._saturating_score(anchor_span_bars=span, horizon_bars=horizon)
            assert (score >= trial.SCORE_THRESHOLD) is (span >= horizon)


def test_validation_stream_uses_only_causal_prefixes_and_holdout_requires_freeze() -> None:
    dataset = _dataset()
    _, research = _resolved_configs()
    plan = trial.build_fixed_fold_plan(dataset)
    provider = _RecordingProvider()
    stream = trial.build_candidate_stream(
        dataset=dataset,
        config=research,
        fold_plan=plan,
        provider=provider,
        window_kind="validation",
    )
    positions = [record["position"] for record in stream["records"]]
    expected = [position for _, start, end in trial.VALIDATION_BOUNDS for position in range(start, end + 1)]
    assert positions == expected
    assert len(provider.calls) == 288
    assert [length for length, _ in provider.calls] == [position + 1 for position in expected]
    assert stream["finalist_freeze_id"] is None

    with pytest.raises(trial.FreshWindowTrialError, match="requires a frozen"):
        trial.build_candidate_stream(
            dataset=dataset,
            config=research,
            fold_plan=plan,
            provider=_FailIfCalledProvider(),
            window_kind="holdout",
        )


def test_validation_outcomes_are_sealed_to_each_fold_end() -> None:
    dataset = _dataset()
    _, research = _resolved_configs()
    plan = trial.build_fixed_fold_plan(dataset)
    provider = _RecordingProvider()
    record = trial._stream_record(
        dataset=dataset,
        config=research,
        provider=provider,
        fold_index=0,
        fold_id=plan.folds[0].fold_id,
        position=plan.folds[0].validation.end_position,
    )
    stream = {
        "candidate_stream_id": "fixture-stream",
        "records": [record],
    }
    evidence = trial.build_outcome_evidence(dataset=dataset, stream=stream, window_kind="validation")
    assert evidence["outcomes"][0]["outcome"] == {
        "available": False,
        "reason": "outcome_horizon_unavailable",
    }


def test_local_outcome_calculation_matches_canonical_evaluator_on_available_fixture() -> None:
    dataset = _dataset()
    baseline, _ = _resolved_configs()
    position = 300
    frame = dataset.to_frame()
    candidate = _candidate(
        config=baseline,
        ohlcv=dataset.prefix(position),
        observed_at=dataset.timestamps[position],
    )
    policy = trial.outcome_policy()
    local = trial._candidate_outcome(
        candidate=candidate,
        position=position,
        frame=frame,
        policy=policy,
        end_position=347,
    )
    canonical = CandidateGeometryEvaluator(dataset=dataset, outcome_policy=policy)._candidate_outcome(
        candidate=candidate,
        position=position,
        frame=frame,
        policy=policy,
    )
    assert local["available"] is True
    assert canonical is not None
    assert {key: local[key] for key in canonical} == canonical


def test_persisted_normalized_input_is_reloaded_without_raw_re_normalization(tmp_path: Path) -> None:
    root = tmp_path / "trial"
    trial.prepare_trial_root(trial_root=root, scope={"fixture": "scope"})
    baseline, research = _resolved_configs()
    raw = _raw_frame()
    trial.persist_raw_fetch_evidence(trial_root=root, raw=raw)
    dataset = trial.normalize_and_preflight(raw)
    manifest = trial.persist_normalized_input(
        trial_root=root,
        dataset=dataset,
        config=baseline,
        research_config=research,
    )
    loaded = trial.load_normalized_input(trial_root=root, input_manifest=manifest)
    normalized_path = root / "input" / manifest["normalized_input_file"]
    assert loaded.dataset_hash == dataset.dataset_hash
    assert sha256(normalized_path.read_bytes()).hexdigest() == manifest["normalized_input_sha256"]


def test_atomic_input_persistence_binds_exact_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "trial"
    trial.prepare_trial_root(trial_root=root, scope={"fixture": "scope"})
    baseline, research = _resolved_configs()
    dataset = _dataset()
    replacements: list[tuple[Path, Path]] = []
    original_replace = trial.os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(trial.os, "replace", recording_replace)
    raw_manifest = trial.persist_raw_fetch_evidence(trial_root=root, raw=_raw_frame())
    input_manifest = trial.persist_normalized_input(
        trial_root=root,
        dataset=dataset,
        config=baseline,
        research_config=research,
    )
    raw_path = root / "input" / raw_manifest["raw_response_file"]
    normalized_path = root / "input" / input_manifest["normalized_input_file"]
    assert sha256(raw_path.read_bytes()).hexdigest() == raw_manifest["raw_response_sha256"]
    assert sha256(normalized_path.read_bytes()).hexdigest() == input_manifest["normalized_input_sha256"]
    assert raw_path in {destination for _, destination in replacements}
    assert normalized_path in {destination for _, destination in replacements}
    assert all(source.parent == destination.parent for source, destination in replacements)


def test_existing_root_rejects_before_adapter_use(tmp_path: Path) -> None:
    root = tmp_path / trial.TRIAL_NAME
    root.mkdir()
    adapter = _Adapter(_raw_frame())
    with pytest.raises(trial.FreshWindowTrialError, match="refusing rerun"):
        trial.prepare_trial_root(trial_root=root, scope={})
    assert adapter.calls == []


def test_quality_identity_drift_rejects_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = {
        "quality_normalization_study": {"study_identity": {"study_id": "drift"}},
        "source_binding": {"quality_source_binding_id": trial.QUALITY_SOURCE_BINDING_ID},
    }
    monkeypatch.setattr(trial.quality_study, "validate_quality_study_bundle", lambda **_kwargs: bundle)
    with pytest.raises(trial.FreshWindowTrialError, match="quality-study ID drift"):
        trial.validate_approved_quality_sources()


def test_external_selector_uses_declared_tie_break_only() -> None:
    def result(trial_id: str, horizon: int, reaction: float) -> SimpleNamespace:
        return SimpleNamespace(
            status=TrialStatus.COMPLETED,
            objective_gate=SimpleNamespace(passed=True),
            result_id=f"result-{trial_id}",
            trial=SimpleNamespace(
                trial_id=trial_id,
                evaluation_context={
                    "quality_policy_id": "fixed_horizon_saturating_v1",
                    "horizon_bars": horizon,
                    "score_threshold": "0.50",
                    "equivalent_min_anchor_span_bars": horizon,
                },
            ),
            metric=lambda name: SimpleNamespace(value=reaction if name == "reaction_quality" else 0.6),
        )

    baseline = SimpleNamespace(
        result_id="baseline-result",
        metric=lambda _name: SimpleNamespace(value=0.5),
    )
    left = result("trial-b", 12, 0.7)
    right = result("trial-a", 24, 0.7)
    audits = {
        "audits": [
            {"trial_result_id": left.result_id, "effect_detected": True, "leakage_detected": False},
            {"trial_result_id": right.result_id, "effect_detected": True, "leakage_detected": False},
        ]
    }
    selection = trial.select_external_research_finalist(
        baseline=baseline,
        primary=(left, right),
        effect_audits=audits,
    )
    assert selection["decision"] == "VALIDATION_FINALIST_FROZEN"
    assert selection["finalist_trial_id"] == "trial-a"
    assert selection["finalist_horizon_bars"] == 24


def test_external_evaluator_has_no_native_provider_path_or_yaml_write() -> None:
    evaluator_source = inspect.getsource(trial.PersistedStreamEvaluator)
    module_source = Path(trial.__file__).read_text(encoding="utf-8")
    assert "NativeDeterministicLineProvider" not in evaluator_source
    assert ".generate(" not in evaluator_source
    assert "CandidateGeometryEvaluator" not in module_source
    assert "select_validation_finalist(" not in module_source
    assert "CONFIG_PATH.write" not in module_source
    assert "runtime" not in inspect.getsource(trial.research_generation_config).lower()


def test_mocked_top_to_bottom_runner_makes_one_request_after_input_root_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / trial.TRIAL_NAME
    adapter = _Adapter(_raw_frame(), required_input_directory=root / "input")
    quality_bundle = {
        "quality_normalization_study": {"study_identity": {"study_id": trial.QUALITY_STUDY_ID}},
        "source_binding": {"quality_source_binding_id": trial.QUALITY_SOURCE_BINDING_ID},
    }
    protected = {"approved_quality": {"fixture": "inventory"}}
    decision = {
        "decision": "REJECT_NO_VALIDATION_FINALIST",
        "research_decision_id": "fixture-decision",
    }
    monkeypatch.setattr(trial, "validate_approved_quality_sources", lambda: quality_bundle)
    monkeypatch.setattr(trial, "protected_source_inventories", lambda: protected)
    monkeypatch.setattr(
        trial,
        "execute_research_evaluation",
        lambda **_kwargs: {
            "baseline": None,
            "primary": (),
            "audits": {},
            "decision": decision,
            "freeze": None,
            "holdout_baseline": None,
            "holdout_finalist": None,
        },
    )
    monkeypatch.setattr(trial, "_build_report", lambda **_kwargs: {})
    monkeypatch.setattr(trial, "_write_report_and_manifest", lambda **_kwargs: None)
    monkeypatch.setattr(trial, "validate_trial_bundle", lambda **_kwargs: {})

    paths = asyncio.run(trial.run_trial(adapter_factory=lambda: adapter, trial_root=root))
    assert len(adapter.calls) == 1
    assert (root / "input" / "raw_binance_response.csv").is_file()
    assert (root / "input" / "normalized_ohlcv.csv").is_file()
    assert paths["decision"].is_file()


def test_full_mocked_no_finalist_bundle_round_trips_without_holdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / trial.TRIAL_NAME
    adapter = _Adapter(_raw_frame())
    provider = _RecordingProvider()
    quality_bundle = {
        "quality_normalization_study": {"study_identity": {"study_id": trial.QUALITY_STUDY_ID}},
        "source_binding": {"quality_source_binding_id": trial.QUALITY_SOURCE_BINDING_ID},
    }
    protected = {"approved_quality": {"fixture": "inventory"}}
    monkeypatch.setattr(trial, "validate_approved_quality_sources", lambda: quality_bundle)
    monkeypatch.setattr(trial, "protected_source_inventories", lambda: protected)
    monkeypatch.setattr(trial, "NativeDeterministicLineProvider", lambda: provider)

    paths = asyncio.run(trial.run_trial(adapter_factory=lambda: adapter, trial_root=root))
    verified = trial.validate_trial_bundle(trial_root=root)

    assert len(adapter.calls) == 1
    assert len(provider.calls) == 288
    assert verified["decision"]["decision"] == "REJECT_NO_VALIDATION_FINALIST"
    assert not (root / "validation" / "finalist_freeze.json").exists()
    assert not (root / "holdout").exists()
    assert paths["bundle_manifest"].is_file()
