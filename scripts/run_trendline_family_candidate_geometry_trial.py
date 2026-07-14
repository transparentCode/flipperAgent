"""Run the one approved retry BTCUSDT 4h candidate/geometry research trial.

This script intentionally has no command-line switches. Its fixed scope prevents
accidental reruns with changed data, configuration, objective, or search space.
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping, Protocol

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.candidate_optimizer import (
    CandidateGeometryEvaluator,
    CandidateOutcomePolicy,
)
from libs.models.trendline_family.optimization.contracts import (
    ObjectiveSpec,
    OptimizationStage,
    TrialResult,
)
from libs.models.trendline_family.optimization.evaluator import enumerate_grid
from libs.models.trendline_family.optimization.folds import (
    FoldPlan,
    ImmutableHistoricalFrame,
    build_walk_forward_fold_plan,
)
from libs.models.trendline_family.optimization.runner import (
    PhaseIEvaluationResult,
    run_phase_i_evaluation,
)
from libs.models.trendline_family.research_lab.artifacts import (
    PhaseIArtifactBrowser,
    load_verified_phase_i_artifacts,
)
from libs.models.trendline_family.research_lab.replay import normalize_binance_ohlcv


ASSET = "BTCUSDT"
MARKET = "Binance USD-M Futures"
TIMEFRAME = "4h"
START_UTC = datetime(2025, 8, 1, tzinfo=timezone.utc)
END_UTC = datetime(2025, 12, 1, tzinfo=timezone.utc)
EXPECTED_ROW_COUNT = 732
EXPECTED_FIRST_TIMESTAMP = pd.Timestamp("2025-08-01T00:00:00Z")
EXPECTED_LAST_TIMESTAMP = pd.Timestamp("2025-11-30T20:00:00Z")
REQUEST_LIMIT = 1000
V1_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
EXECUTION_ATTEMPT = 2
AUTHORIZATION_ID = "trendline_family_candidate_geometry_retry_v2"
SUPERSEDES_TRIAL_NAME = V1_TRIAL_NAME
PREVIOUS_ATTEMPT_STATUS = "local_persistence_failure_before_normalization"
TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / TRIAL_NAME
V1_TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / V1_TRIAL_NAME
CONFIG_PATH = PROJECT_ROOT / "configs" / "trendline_family.yaml"
CODEBASE_PROJECT = "Users-aloobhujia-flipperAgent"

EXPECTED_CANDIDATE_CONFIG = {
    "lookback_bars": 180,
    "min_bars": 40,
    "fractal_left_bars": 3,
    "fractal_right_bars": 3,
    "min_pivots_per_side": 2,
    "min_candidate_quality": 0.35,
}
SEARCH_SPACE: Mapping[str, tuple[float | int, ...]] = {
    "candidate.lookback_bars": (120, 180, 240),
    "candidate.min_candidate_quality": (0.30, 0.40),
}


class TrialPreflightError(ContractValidationError):
    """Fixed-scope trial input, identity, or reuse failure."""


class HistoricalAdapter(Protocol):
    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame: ...


def request_parameters() -> dict[str, Any]:
    """Return exact single-request inputs as auditable primitive values."""

    return {
        "symbol": ASSET,
        "timeframe": TIMEFRAME,
        "since": int(START_UTC.timestamp() * 1_000),
        "until": int(END_UTC.timestamp() * 1_000),
        "limit": REQUEST_LIMIT,
    }


async def fetch_bounded_ohlcv(adapter: HistoricalAdapter) -> pd.DataFrame:
    """Make exactly one approved Binance historical-kline request."""

    if not hasattr(adapter, "get_historical_ohlcv"):
        raise TrialPreflightError("trial adapter lacks get_historical_ohlcv")
    request = request_parameters()
    raw = await adapter.get_historical_ohlcv(
        request["symbol"],
        request["timeframe"],
        since=request["since"],
        until=request["until"],
        limit=request["limit"],
    )
    if not isinstance(raw, pd.DataFrame):
        raise TrialPreflightError("Binance adapter must return a DataFrame")
    return raw


def resolve_baseline_config() -> ResolvedTrendlineFamilyConfig:
    """Resolve only the approved non-smoke YAML baseline without overrides."""

    config = TrendlineFamilyConfigResolver.from_path(CONFIG_PATH).resolve(
        asset=ASSET,
        timeframe=TIMEFRAME,
    )
    if config.asset != ASSET or config.timeframe != TIMEFRAME:
        raise TrialPreflightError("resolved config asset/timeframe drift")
    if config.config_version == "research_smoke_v1" or (
        config.field_provenance.get("research_lab") == "deterministic_smoke_fixture"
    ):
        raise TrialPreflightError("real-data trial cannot use research smoke config")
    if not config.model.enabled:
        raise TrialPreflightError("resolved trendline-family model is disabled")
    actual = {
        "lookback_bars": config.candidate.lookback_bars,
        "min_bars": config.candidate.min_bars,
        "fractal_left_bars": config.candidate.fractal_left_bars,
        "fractal_right_bars": config.candidate.fractal_right_bars,
        "min_pivots_per_side": config.candidate.min_pivots_per_side,
        "min_candidate_quality": config.candidate.min_candidate_quality,
    }
    if actual != EXPECTED_CANDIDATE_CONFIG:
        raise TrialPreflightError(
            "resolved candidate config drift: "
            + json.dumps({"expected": EXPECTED_CANDIDATE_CONFIG, "actual": actual}, sort_keys=True)
        )
    return config


def normalize_and_preflight(raw: pd.DataFrame) -> ImmutableHistoricalFrame:
    """Normalize Binance rows, then enforce every fixed trial data invariant."""

    try:
        normalized = normalize_binance_ohlcv(
            raw,
            timeframe=TIMEFRAME,
            closed_before=END_UTC,
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise TrialPreflightError(f"Binance normalization failed: {exc}") from exc

    if not isinstance(normalized.index, pd.DatetimeIndex) or normalized.index.tz is None:
        raise TrialPreflightError("normalized input requires timezone-aware UTC index")
    if str(normalized.index.tz) not in {"UTC", "UTC+00:00"}:
        raise TrialPreflightError("normalized input requires UTC timestamps")
    if len(normalized) != EXPECTED_ROW_COUNT:
        raise TrialPreflightError(
            f"confirmed row count mismatch: expected {EXPECTED_ROW_COUNT}, got {len(normalized)}"
        )
    if normalized.index[0] != EXPECTED_FIRST_TIMESTAMP or normalized.index[-1] != EXPECTED_LAST_TIMESTAMP:
        raise TrialPreflightError("normalized input boundary mismatch")
    if not normalized.index.is_monotonic_increasing or normalized.index.has_duplicates:
        raise TrialPreflightError("normalized input timestamps must be strictly increasing and unique")
    expected_gap = pd.Timedelta(hours=4)
    if not (normalized.index.to_series().diff().dropna() == expected_gap).all():
        raise TrialPreflightError("normalized input contains a non-4h timestamp gap")
    required = ("open", "high", "low", "close", "volume", "complete")
    if any(column not in normalized.columns for column in required):
        raise TrialPreflightError("normalized input is missing required OHLCV columns")
    numeric = normalized.loc[:, ("open", "high", "low", "close", "volume")].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if numeric.isna().any().any() or not math.isfinite(float(numeric.to_numpy().sum())):
        raise TrialPreflightError("normalized input contains non-finite OHLCV values")
    if (numeric.loc[:, ("open", "high", "low", "close")] <= 0.0).any().any():
        raise TrialPreflightError("normalized input requires positive OHLC prices")
    if (numeric["volume"] < 0.0).any():
        raise TrialPreflightError("normalized input requires non-negative volume")
    if (numeric["high"] < numeric.loc[:, ("open", "close")].max(axis=1)).any():
        raise TrialPreflightError("normalized input has high below open or close")
    if (numeric["low"] > numeric.loc[:, ("open", "close")].min(axis=1)).any():
        raise TrialPreflightError("normalized input has low above open or close")
    if not normalized["complete"].eq(True).all():
        raise TrialPreflightError("normalized input contains incomplete bars")
    if normalized.index[0] < pd.Timestamp(START_UTC) or (
        normalized.index[-1] + expected_gap > pd.Timestamp(END_UTC)
    ):
        raise TrialPreflightError("normalized input extends outside approved window")
    validated = normalized.copy(deep=True)
    validated.loc[:, numeric.columns] = numeric
    try:
        return ImmutableHistoricalFrame(asset=ASSET, timeframe=TIMEFRAME, _frame=validated)
    except ContractValidationError as exc:
        raise TrialPreflightError(f"immutable historical frame rejected input: {exc}") from exc


def outcome_policy() -> CandidateOutcomePolicy:
    return CandidateOutcomePolicy(
        horizon_bars=12,
        atr_window=14,
        touch_tolerance_atr=0.25,
        survival_penetration_atr=0.75,
        reaction_threshold_atr=0.50,
        policy_version="candidate_structural_outcome_btcusdt_4h_v1",
    )


def objective_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_version="candidate_geometry_reaction_btcusdt_4h_v1",
        primary_metric="reaction_quality",
        maximize=True,
        minimum_sample_count=100,
        minimum_fold_coverage=1.0,
        maximum_failure_rate=0.0,
        allowed_degradation=0.0,
        require_comparable_population=True,
    )


def build_fixed_fold_plan(dataset: ImmutableHistoricalFrame) -> FoldPlan:
    return build_walk_forward_fold_plan(
        dataset,
        initial_train_bars=240,
        validation_bars=96,
        fold_count=3,
        holdout_bars=96,
        warmup_bars=180,
        purge_bars=12,
        embargo_bars=0,
        label_horizon_bars=12,
        train_mode="expanding",
    )


def validate_fixed_trial_spec(dataset: ImmutableHistoricalFrame, fold_plan: FoldPlan) -> None:
    requested = enumerate_grid(SEARCH_SPACE, maximum_trial_count=6)
    if len(requested) != 6:
        raise TrialPreflightError("fixed candidate search must enumerate exactly six primary trials")
    if len(fold_plan.folds) != 3 or fold_plan.holdout.window.bar_count != 96:
        raise TrialPreflightError("fixed fold plan drift")
    if any(fold.purge_bars != 12 or fold.validation.bar_count != 96 for fold in fold_plan.folds):
        raise TrialPreflightError("fixed validation/purge plan drift")
    if fold_plan.label_horizon_bars != 12 or dataset.asset != ASSET or dataset.timeframe != TIMEFRAME:
        raise TrialPreflightError("fixed dataset/fold identity drift")


def _atomic_write(path: Path, payload: bytes) -> None:
    """Atomically create one immutable artifact without replacing prior evidence."""

    if path.exists():
        raise TrialPreflightError(f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
    )


def _execution_identity() -> dict[str, Any]:
    return {
        "trial_name": TRIAL_NAME,
        "execution_attempt": EXECUTION_ATTEMPT,
        "authorization_id": AUTHORIZATION_ID,
        "supersedes_trial_name": SUPERSEDES_TRIAL_NAME,
        "previous_attempt_status": PREVIOUS_ATTEMPT_STATUS,
        "phase_i_semantics_unchanged": True,
    }


def prepare_trial_root(trial_root: Path) -> None:
    """Reserve one immutable trial root before remote execution; root reuse is forbidden."""

    if trial_root.exists():
        raise TrialPreflightError(
            f"fixed trial root already exists; refusing rerun: {trial_root}"
        )
    trial_root.mkdir(parents=True)
    (trial_root / "input").mkdir()
    _write_json(
        trial_root / "execution_scope.json",
        {
            "asset": ASSET,
            "market": MARKET,
            "timeframe": TIMEFRAME,
            "start": _iso(START_UTC),
            "end": _iso(END_UTC),
            "single_execution": True,
            **_execution_identity(),
        },
    )


def persist_input(
    *,
    trial_root: Path,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
) -> Mapping[str, Any]:
    """Persist normalized immutable data and a content hash before evaluation."""

    input_path = trial_root / "input" / "normalized_ohlcv.csv"
    if input_path.exists():
        raise TrialPreflightError("refusing to overwrite existing normalized input")
    frame = dataset.to_frame().copy(deep=True)
    payload = frame.to_csv(
        index_label="timestamp",
        float_format="%.17g",
    ).encode("utf-8")
    _atomic_write(input_path, payload)
    file_hash = sha256(payload).hexdigest()
    manifest = {
        "asset": ASSET,
        "market": MARKET,
        "timeframe": TIMEFRAME,
        "start": _iso(START_UTC),
        "end": _iso(END_UTC),
        "adapter_class": f"{BinanceNativeAdapter.__module__}.{BinanceNativeAdapter.__qualname__}",
        "request": request_parameters(),
        "row_count": dataset.row_count,
        "first_timestamp": _iso(dataset.timestamps[0]),
        "last_timestamp": _iso(dataset.timestamps[-1]),
        "dataset_hash": dataset.dataset_hash,
        "resolved_config_version": config.config_version,
        "resolved_config_hash": config.resolved_config_hash,
        "normalized_input_file": input_path.name,
        "normalized_input_sha256": file_hash,
        **_execution_identity(),
    }
    _write_json(trial_root / "input" / "input_manifest.json", manifest)
    return manifest


def persist_raw_fetch_evidence(*, trial_root: Path, raw: pd.DataFrame) -> Mapping[str, Any]:
    """Preserve one-request evidence if normalization or preflight rejects it."""

    raw_path = trial_root / "input" / "raw_binance_response.csv"
    payload = raw.to_csv(index=False).encode("utf-8")
    _atomic_write(raw_path, payload)
    manifest = {
        "adapter_class": f"{BinanceNativeAdapter.__module__}.{BinanceNativeAdapter.__qualname__}",
        "request": request_parameters(),
        "raw_column_names": [str(column) for column in raw.columns],
        "raw_row_count": len(raw),
        "raw_response_file": raw_path.name,
        "raw_response_sha256": sha256(payload).hexdigest(),
        **_execution_identity(),
    }
    _write_json(
        trial_root / "input" / "raw_fetch_manifest.json",
        manifest,
    )
    return manifest


def _run_phase_i(
    *,
    trial_root: Path,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    evaluator: CandidateGeometryEvaluator,
) -> PhaseIEvaluationResult:
    return run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=dataset,
        fold_plan=fold_plan,
        baseline_config=config,
        objective=objective_spec(),
        search_space=SEARCH_SPACE,
        evaluator=evaluator,
        output_root=trial_root / "phase_i",
        maximum_trial_count=6,
        seed=0,
        open_holdout=True,
        codebase_project=CODEBASE_PROJECT,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _metric_payload(result: TrialResult | None) -> Mapping[str, Any] | None:
    if result is None:
        return None
    return result.to_dict()


def _provider_summary(results: tuple[TrialResult, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for window in result.window_results:
            statuses = window.diagnostics.get("provider_status_counts", {})
            if not isinstance(statuses, Mapping):
                continue
            for name, value in statuses.items():
                if isinstance(name, str) and isinstance(value, int) and not isinstance(value, bool):
                    counts[name] = counts.get(name, 0) + value
    return dict(sorted(counts.items()))


def _candidate_density_summary(results: tuple[TrialResult, ...]) -> list[Mapping[str, Any]]:
    names = (
        "candidate_coverage_ratio",
        "candidate_count",
        "candidates_per_bar",
        "support_balance",
        "resistance_balance",
        "provider_failure_rate",
    )
    return [
        {
            "trial_id": result.trial.trial_id,
            "trial_kind": result.trial.trial_kind,
            "metrics": {
                name: None if result.metric(name) is None else result.metric(name).to_dict()
                for name in names
            },
        }
        for result in results
    ]


def _fold_boundaries(fold_plan: FoldPlan) -> Mapping[str, Any]:
    return {
        "folds": [fold.to_dict() for fold in fold_plan.folds],
        "holdout": fold_plan.holdout.to_dict(),
    }


def write_trial_report(
    *,
    trial_root: Path,
    input_manifest: Mapping[str, Any],
    browser: PhaseIArtifactBrowser,
) -> Path:
    """Write reviewer report only from persisted input plus independently verified artifacts."""

    input_path = trial_root / "input" / str(input_manifest["normalized_input_file"])
    if sha256(input_path.read_bytes()).hexdigest() != input_manifest["normalized_input_sha256"]:
        raise TrialPreflightError("persisted normalized input hash no longer matches input manifest")
    bundle = browser.bundle
    verified_results = (browser.baseline_validation, *browser.trials)
    counterfactuals = tuple(
        counterfactual
        for trial in browser.trials
        for counterfactual in trial.counterfactual_results
    )
    report = {
        "dataset_identity_and_preflight": dict(input_manifest),
        "resolved_config_identity_and_baseline_candidate_values": {
            "config_version": browser.manifest.config_version,
            "resolved_config_hash": browser.manifest.baseline_config_hashes[f"{ASSET}:{TIMEFRAME}"],
            "baseline_candidate_values": browser.manifest.stage_baseline_parameter_values[
                OptimizationStage.CANDIDATE_GEOMETRY.value
            ],
        },
        "outcome_policy_identity": browser.manifest.stage_evaluation_specs[
            OptimizationStage.CANDIDATE_GEOMETRY.value
        ].semantic_inputs["outcome_policy"],
        "fold_and_holdout_boundaries": _fold_boundaries(bundle.fold_plan),
        "requested_primary_trial_ids_and_completion": {
            "expected_primary_trial_ids": browser.manifest.expected_primary_trial_ids,
            "completion_index": bundle.completion_index.to_dict(),
        },
        "baseline_validation": _metric_payload(browser.baseline_validation),
        "primary_trials": [_metric_payload(result) for result in browser.trials],
        "marginal_counterfactuals": [_metric_payload(result) for result in counterfactuals],
        "parameter_effect_and_leakage_audits": [
            audit.to_dict()
            for result in browser.trials
            for audit in result.parameter_effect_audits
        ],
        "frozen_finalist": None
        if bundle.finalist_freeze is None
        else bundle.finalist_freeze.to_dict(),
        "baseline_untouched_holdout": _metric_payload(bundle.baseline_holdout),
        "finalist_untouched_holdout": _metric_payload(bundle.finalist_holdout),
        "holdout_open_audits": [audit.to_dict() for audit in bundle.holdout_open_audits],
        "provider_status_counts": _provider_summary(verified_results),
        "candidate_density_and_balance": _candidate_density_summary(verified_results),
        "persisted_recommendation": bundle.recommendation.to_dict(),
        "reviewer_assessment": {
            "scope": "one BTCUSDT 4h candidate/geometry structural trial only",
            "residual_risks": [
                "One asset and one bounded window cannot establish model quality.",
                "Structural metrics are not PnL, trading, or runtime-readiness evidence.",
                "No runtime config or promotion action occurred.",
            ],
        },
        "runtime_and_config_promotion": "No config patch, runtime configuration write, or runtime promotion occurred.",
    }
    markdown = "# BTCUSDT 4h Candidate/Geometry Real-Data Trial v2\n\n"
    for heading, payload in report.items():
        markdown += "## " + heading.replace("_", " ").title() + "\n\n"
        markdown += "```json\n" + json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n```\n\n"
    path = trial_root / "trial_report.md"
    _atomic_write(path, markdown.encode("utf-8"))
    return path


async def run_trial(
    *,
    adapter_factory: Callable[[], HistoricalAdapter] = BinanceNativeAdapter,
    trial_root: Path = TRIAL_ROOT,
) -> Mapping[str, Path]:
    """Execute one immutable remote trial. Any failure preserves evidence and stops."""

    config = resolve_baseline_config()
    prepare_trial_root(trial_root)
    raw = await fetch_bounded_ohlcv(adapter_factory())
    persist_raw_fetch_evidence(trial_root=trial_root, raw=raw)
    dataset = normalize_and_preflight(raw)
    input_manifest = persist_input(trial_root=trial_root, dataset=dataset, config=config)
    fold_plan = build_fixed_fold_plan(dataset)
    validate_fixed_trial_spec(dataset, fold_plan)
    evaluator = CandidateGeometryEvaluator(dataset=dataset, outcome_policy=outcome_policy())
    _run_phase_i(
        trial_root=trial_root,
        dataset=dataset,
        config=config,
        fold_plan=fold_plan,
        evaluator=evaluator,
    )
    browser = load_verified_phase_i_artifacts(trial_root / "phase_i")
    report_path = write_trial_report(
        trial_root=trial_root,
        input_manifest=input_manifest,
        browser=browser,
    )
    return {
        "trial_root": trial_root,
        "input_manifest": trial_root / "input" / "input_manifest.json",
        "phase_i": trial_root / "phase_i",
        "trial_report": report_path,
    }


def main() -> None:
    paths = asyncio.run(run_trial())
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
