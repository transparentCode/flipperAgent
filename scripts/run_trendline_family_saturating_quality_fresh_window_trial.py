"""Run one immutable fresh-window saturating candidate-quality research trial.

No CLI arguments. Fixed identity prevents retry, policy drift, or holdout access
outside the approved validation-finalist path.
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping, Protocol, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from libs.models.trendline.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline.contracts import ContractValidationError, FamilyRole, LineCandidate
from libs.models.trendline.interactions import calculate_interaction_atr
from libs.models.trendline.optimization.candidate_optimizer import CandidateOutcomePolicy
from libs.models.trendline.optimization.contracts import (
    FinalistFreeze,
    HoldoutOpenAudit,
    MetricRecord,
    ObjectiveSpec,
    OptimizationStage,
    StageEvaluationSpec,
    TrialConfig,
    TrialResult,
    TrialStatus,
    WindowResult,
    canonical_json,
    primitive,
    semantic_id,
)
from libs.models.trendline.optimization.evaluator import (
    HoldoutOpenRegistry,
    apply_stage_overrides,
    build_holdout_open_audit,
    build_objective_gate,
    evaluate_holdout_once,
    freeze_validation_finalist,
    run_validation_trial,
)
from libs.models.trendline.optimization.folds import (
    FoldPlan,
    HoldoutPlan,
    ImmutableHistoricalFrame,
    WalkForwardFold,
    build_walk_forward_fold_plan,
)
from libs.models.trendline.optimization.metrics import mean_metric, ratio_metric
from libs.models.trendline.provider import (
    CandidateGenerationStatus,
    LineCandidateProvider,
    NativeDeterministicLineProvider,
    provider_identity,
)
from libs.models.trendline.research_lab.replay import normalize_binance_ohlcv
from scripts import analyze_trendline_family_candidate_quality_normalization as quality_study


TRIAL_SCHEMA_VERSION = "trendline_family_saturating_quality_fresh_window_trial_v1"
STREAM_SCHEMA_VERSION = "trendline_family_saturating_quality_candidate_stream_v1"
OUTCOME_SCHEMA_VERSION = "trendline_family_saturating_quality_outcome_evidence_v1"
TRIAL_NAME = "btcusdt_4h_20251201_20260401_saturating_quality_v1"
AUTHORIZATION_ID = "trendline_family_saturating_quality_fresh_window_v1"
EXECUTION_ATTEMPT = 1
ASSET = "BTCUSDT"
MARKET = "Binance USD-M Futures"
TIMEFRAME = "4h"
TIMEFRAME_SECONDS = 14_400
START_UTC = datetime(2025, 12, 1, tzinfo=timezone.utc)
END_UTC = datetime(2026, 4, 1, tzinfo=timezone.utc)
EXPECTED_ROW_COUNT = 726
EXPECTED_FIRST_TIMESTAMP = pd.Timestamp("2025-12-01T00:00:00Z")
EXPECTED_LAST_TIMESTAMP = pd.Timestamp("2026-03-31T20:00:00Z")
REQUEST_LIMIT = 1000
TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_saturating_quality_trials" / TRIAL_NAME
CONFIG_PATH = PROJECT_ROOT / "configs" / "trendline_family.yaml"
QUALITY_ROOT = quality_study.OUTPUT_ROOT

QUALITY_STUDY_ID = "trendline-family-candidate-quality-normalization-study_b45c8006cbe5304f36305fb1131e75173f32addc181d3e48e8d5bfd5cb71b0e3"
QUALITY_SOURCE_BINDING_ID = "trendline-family-candidate-quality-normalization-source-binding_483b0f334281e27e7d9d99bf41ce86c5d7839d90148a9d025e1c72ba35e62d94"
EXPECTED_CONFIG_SHA256 = "7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8"
EXPECTED_RESOLVED_CONFIG_HASH = "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f"
EXPECTED_CANDIDATE_CONFIG = {
    "lookback_bars": 180,
    "min_bars": 40,
    "fractal_left_bars": 3,
    "fractal_right_bars": 3,
    "min_pivots_per_side": 2,
    "min_candidate_quality": 0.35,
}
RESEARCH_OVERRIDE = {"candidate.min_candidate_quality": 0.0}
HORIZONS = (12, 24, 48, 96)
SCORE_THRESHOLD = Decimal("0.50")
OUTCOME_POLICY_VERSION = "candidate_structural_outcome_btcusdt_4h_v1"
OBJECTIVE_VERSION = "candidate_saturating_quality_reaction_btcusdt_4h_v1"
EVALUATION_SPEC_VERSION = "candidate_saturating_quality_fresh_window_v1"
VALIDATION_BOUNDS = ((0, 252, 347), (1, 360, 455), (2, 468, 563))
HOLDOUT_BOUNDS = (630, 725)
QUALITY_FILES = (
    "quality_normalization_study.json",
    "quality_normalization_study.md",
    "source_binding.json",
    "study_manifest.json",
)
_SHA256_PATTERN = __import__("re").compile(r"[0-9a-f]{64}\Z")


class FreshWindowTrialError(ContractValidationError):
    """Fixed-scope remote trial input, evidence, or provenance failure."""


class HistoricalAdapter(Protocol):
    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame: ...


def _iso(value: datetime | pd.Timestamp) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise FreshWindowTrialError("timestamp must be timezone-aware UTC")
    return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise FreshWindowTrialError(f"required {label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreshWindowTrialError(f"invalid {label} JSON") from exc
    if not isinstance(value, Mapping):
        raise FreshWindowTrialError(f"{label} JSON must be a mapping")
    return value


def _atomic_write(path: Path, payload: bytes) -> Path:
    if path.exists():
        raise FreshWindowTrialError(f"refusing to overwrite immutable artifact: {path}")
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
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _atomic_write(path, canonical_json(payload).encode("utf-8") + b"\n")


def _file_inventory(root: Path, *, source_name: str, exclude: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    if not root.is_dir():
        raise FreshWindowTrialError(f"inventory root missing: {root}")
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if relative_path in exclude:
            continue
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        )
    semantic = {"source_name": source_name, "root_name": root.name, "files": files}
    return {**semantic, "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8"))}


def _quality_inventory() -> Mapping[str, Any]:
    inventory = _file_inventory(QUALITY_ROOT, source_name="approved_quality_study")
    paths = tuple(item["relative_path"] for item in inventory["files"])
    if paths != QUALITY_FILES:
        raise FreshWindowTrialError("approved quality-study file set drift")
    return inventory


def protected_source_inventories() -> Mapping[str, Any]:
    previous = quality_study.capture_protected_source_inventories()
    quality = _quality_inventory()
    config = previous.get("config")
    if not isinstance(config, Mapping) or config.get("sha256") != EXPECTED_CONFIG_SHA256:
        raise FreshWindowTrialError("approved trendline-family YAML SHA-256 drift")
    expected_counts = {
        "v1_trial": 1,
        "v2_trial": 30,
        "approved_report": 4,
        "approved_diagnosis": 4,
        "approved_density": 4,
        "approved_quality": 4,
    }
    result = {**previous, "approved_quality": quality}
    counts = {key: len(result[key]["files"]) for key in expected_counts}
    if counts != expected_counts:
        raise FreshWindowTrialError("protected source inventory count drift")
    return result


def validate_approved_quality_sources() -> Mapping[str, Any]:
    bundle = quality_study.validate_quality_study_bundle(output_root=QUALITY_ROOT)
    identity = bundle["quality_normalization_study"].get("study_identity")
    binding = bundle.get("source_binding")
    if not isinstance(identity, Mapping) or not isinstance(binding, Mapping):
        raise FreshWindowTrialError("approved quality-study identity is malformed")
    if identity.get("study_id") != QUALITY_STUDY_ID:
        raise FreshWindowTrialError("approved quality-study ID drift")
    if binding.get("quality_source_binding_id") != QUALITY_SOURCE_BINDING_ID:
        raise FreshWindowTrialError("approved quality-study source-binding ID drift")
    return bundle


def request_parameters() -> Mapping[str, Any]:
    return {
        "symbol": ASSET,
        "timeframe": TIMEFRAME,
        "since": 1_764_547_200_000,
        "until": 1_775_001_600_000,
        "limit": REQUEST_LIMIT,
    }


async def fetch_bounded_ohlcv(adapter: HistoricalAdapter) -> pd.DataFrame:
    if not hasattr(adapter, "get_historical_ohlcv"):
        raise FreshWindowTrialError("trial adapter lacks get_historical_ohlcv")
    request = request_parameters()
    raw = await adapter.get_historical_ohlcv(
        request["symbol"], request["timeframe"], since=request["since"], until=request["until"], limit=request["limit"]
    )
    if not isinstance(raw, pd.DataFrame):
        raise FreshWindowTrialError("Binance adapter must return a DataFrame")
    return raw


def resolve_baseline_config() -> ResolvedTrendlineFamilyConfig:
    config = TrendlineFamilyConfigResolver.from_path(CONFIG_PATH).resolve(asset=ASSET, timeframe=TIMEFRAME)
    actual = {
        "lookback_bars": config.candidate.lookback_bars,
        "min_bars": config.candidate.min_bars,
        "fractal_left_bars": config.candidate.fractal_left_bars,
        "fractal_right_bars": config.candidate.fractal_right_bars,
        "min_pivots_per_side": config.candidate.min_pivots_per_side,
        "min_candidate_quality": config.candidate.min_candidate_quality,
    }
    if (
        config.asset != ASSET
        or config.timeframe != TIMEFRAME
        or config.resolved_config_hash != EXPECTED_RESOLVED_CONFIG_HASH
        or config.model_version != "trendline_family_v1"
        or config.config_version != "1"
        or actual != EXPECTED_CANDIDATE_CONFIG
    ):
        raise FreshWindowTrialError("resolved canonical BTCUSDT 4h config drift")
    return config


def research_generation_config(config: ResolvedTrendlineFamilyConfig) -> ResolvedTrendlineFamilyConfig:
    research = apply_stage_overrides(
        config,
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        overrides=RESEARCH_OVERRIDE,
    )
    if (
        research.candidate.lookback_bars != 180
        or research.candidate.min_candidate_quality != 0.0
        or research.asset != config.asset
        or research.timeframe != config.timeframe
    ):
        raise FreshWindowTrialError("research generation config drift")
    baseline_values = asdict(config.candidate)
    research_values = asdict(research.candidate)
    changed = {key: value for key, value in research_values.items() if baseline_values.get(key) != value}
    if changed != {"min_candidate_quality": 0.0}:
        raise FreshWindowTrialError("research generation config changed fields outside minimum quality")
    return research


def _validate_confirmed_frame(normalized: pd.DataFrame) -> pd.DataFrame:
    """Validate a normalized, UTC-indexed confirmed frame without raw re-parsing."""

    try:
        normalized = normalized.copy(deep=True)
    except AttributeError as exc:
        raise FreshWindowTrialError("normalized input must be a DataFrame") from exc
    if not isinstance(normalized.index, pd.DatetimeIndex) or normalized.index.tz is None:
        raise FreshWindowTrialError("normalized input requires timezone-aware UTC index")
    if str(normalized.index.tz) not in {"UTC", "UTC+00:00"}:
        raise FreshWindowTrialError("normalized input requires UTC timestamps")
    if len(normalized) != EXPECTED_ROW_COUNT:
        raise FreshWindowTrialError(f"confirmed row count mismatch: expected {EXPECTED_ROW_COUNT}, got {len(normalized)}")
    if normalized.index[0] != EXPECTED_FIRST_TIMESTAMP or normalized.index[-1] != EXPECTED_LAST_TIMESTAMP:
        raise FreshWindowTrialError("normalized input boundary mismatch")
    if not normalized.index.is_monotonic_increasing or normalized.index.has_duplicates:
        raise FreshWindowTrialError("normalized input timestamps must be strictly increasing and unique")
    if not (normalized.index.to_series().diff().dropna() == pd.Timedelta(hours=4)).all():
        raise FreshWindowTrialError("normalized input contains non-4h timestamp gap")
    required = ("open", "high", "low", "close", "volume", "complete")
    if any(column not in normalized.columns for column in required):
        raise FreshWindowTrialError("normalized input is missing required OHLCV columns")
    numeric = normalized.loc[:, ("open", "high", "low", "close", "volume")].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not math.isfinite(float(numeric.to_numpy().sum())):
        raise FreshWindowTrialError("normalized input contains non-finite OHLCV values")
    if (numeric.loc[:, ("open", "high", "low", "close")] <= 0.0).any().any() or (numeric["volume"] < 0.0).any():
        raise FreshWindowTrialError("normalized input contains invalid OHLCV values")
    if (numeric["high"] < numeric.loc[:, ("open", "close")].max(axis=1)).any() or (numeric["low"] > numeric.loc[:, ("open", "close")].min(axis=1)).any():
        raise FreshWindowTrialError("normalized input has invalid candle bounds")
    if not normalized["complete"].eq(True).all():
        raise FreshWindowTrialError("normalized input contains incomplete bars")
    normalized.loc[:, numeric.columns] = numeric
    return normalized


def _validated_normalized_frame(raw: pd.DataFrame) -> pd.DataFrame:
    try:
        normalized = normalize_binance_ohlcv(raw, timeframe=TIMEFRAME, closed_before=END_UTC)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise FreshWindowTrialError(f"Binance normalization failed: {exc}") from exc
    return _validate_confirmed_frame(normalized)


def normalize_and_preflight(raw: pd.DataFrame) -> ImmutableHistoricalFrame:
    try:
        return ImmutableHistoricalFrame(asset=ASSET, timeframe=TIMEFRAME, _frame=_validated_normalized_frame(raw))
    except ContractValidationError as exc:
        raise FreshWindowTrialError(f"immutable historical frame rejected input: {exc}") from exc


def load_normalized_input(*, trial_root: Path, input_manifest: Mapping[str, Any]) -> ImmutableHistoricalFrame:
    input_path = trial_root / "input" / str(input_manifest.get("normalized_input_file"))
    payload = input_path.read_bytes()
    if _sha256_bytes(payload) != input_manifest.get("normalized_input_sha256"):
        raise FreshWindowTrialError("normalized input SHA-256 mismatch")
    frame = pd.read_csv(input_path)
    if "timestamp" not in frame:
        raise FreshWindowTrialError("persisted normalized input lacks timestamp column")
    frame["timestamp"] = pd.to_datetime(frame.pop("timestamp"), utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise FreshWindowTrialError("persisted normalized input has invalid timestamp")
    frame = frame.set_index("timestamp")
    if "complete" in frame:
        frame["complete"] = frame["complete"].map(_complete_flag)
    try:
        return ImmutableHistoricalFrame(
            asset=ASSET,
            timeframe=TIMEFRAME,
            _frame=_validate_confirmed_frame(frame),
        )
    except ContractValidationError as exc:
        raise FreshWindowTrialError(f"persisted normalized input failed immutable validation: {exc}") from exc


def _complete_flag(value: Any) -> bool:
    """Decode only canonical CSV complete values; ambiguous values stay false."""

    if value is True:
        return True
    if isinstance(value, str):
        return value in {"True", "true", "1"}
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


def outcome_policy() -> CandidateOutcomePolicy:
    return CandidateOutcomePolicy(
        horizon_bars=12,
        atr_window=14,
        touch_tolerance_atr=0.25,
        survival_penetration_atr=0.75,
        reaction_threshold_atr=0.50,
        policy_version=OUTCOME_POLICY_VERSION,
    )


def objective_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_version=OBJECTIVE_VERSION,
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


def validate_fixed_fold_plan(dataset: ImmutableHistoricalFrame, fold_plan: FoldPlan) -> None:
    actual = tuple((fold.fold_index, fold.validation.start_position, fold.validation.end_position) for fold in fold_plan.folds)
    if actual != VALIDATION_BOUNDS or (fold_plan.holdout.window.start_position, fold_plan.holdout.window.end_position) != HOLDOUT_BOUNDS:
        raise FreshWindowTrialError("fixed fold or holdout positions drift")
    if (
        fold_plan.holdout.warmup.start_position != 450
        or fold_plan.holdout.warmup.end_position != 629
        or fold_plan.label_horizon_bars != 12
        or dataset.row_count != EXPECTED_ROW_COUNT
    ):
        raise FreshWindowTrialError("fixed fold plan semantics drift")


def evaluation_spec(*, research_config: ResolvedTrendlineFamilyConfig, provider_identity: str) -> StageEvaluationSpec:
    return StageEvaluationSpec(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        spec_type="candidate_saturating_quality_research_evaluation",
        spec_version=EVALUATION_SPEC_VERSION,
        semantic_inputs={
            "source_provider_identity": provider_identity,
            "research_config_hash": research_config.resolved_config_hash,
            "candidate_stream_schema_version": STREAM_SCHEMA_VERSION,
            "formula_family": "fixed_horizon_saturating_v1",
            "allowed_horizons": list(HORIZONS),
            "fixed_score_threshold": "0.50",
            "baseline_control_identity": "threshold_zero_candidate_control_v1",
            "outcome_policy": outcome_policy().to_dict(),
        },
    )


def _scope_payload(
    *,
    config: ResolvedTrendlineFamilyConfig,
    research_config: ResolvedTrendlineFamilyConfig,
    quality_bundle: Mapping[str, Any],
    protected: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {
        "trial_schema_version": TRIAL_SCHEMA_VERSION,
        "trial_name": TRIAL_NAME,
        "execution_attempt": EXECUTION_ATTEMPT,
        "research_authorization_id": AUTHORIZATION_ID,
        "single_network_request": True,
        "fresh_source_window": True,
        "prior_research_window_end": "2025-12-01T00:00:00Z",
        "runtime_promotion_authorized": False,
        "tracker_authorized": False,
        "regime_authorized": False,
        "asset": ASSET,
        "market": MARKET,
        "timeframe": TIMEFRAME,
        "request": request_parameters(),
        "window": {"start_inclusive": _iso(START_UTC), "end_exclusive": _iso(END_UTC), "expected_confirmed_rows": EXPECTED_ROW_COUNT},
        "approved_quality_study": {
            "study_id": quality_bundle["quality_normalization_study"]["study_identity"]["study_id"],
            "source_binding_id": quality_bundle["source_binding"]["quality_source_binding_id"],
            "inventory": protected["approved_quality"],
        },
        "config": {
            "yaml_relative_path": "configs/trendline_family.yaml",
            "yaml_sha256": EXPECTED_CONFIG_SHA256,
            "resolved_config_hash": config.resolved_config_hash,
            "research_config_hash": research_config.resolved_config_hash,
            "research_override": RESEARCH_OVERRIDE,
        },
        "fold_plan": {"validation": list(VALIDATION_BOUNDS), "holdout": HOLDOUT_BOUNDS, "holdout_warmup": (450, 629), "purge_bars": 12, "label_horizon_bars": 12},
        "quality_policy": {"family": "fixed_horizon_saturating_v1", "horizons": list(HORIZONS), "score_threshold": "0.50", "equivalence": "score_gte_0_50_iff_anchor_span_bars_gte_horizon"},
        "objective": objective_spec().to_dict(),
        "outcome_policy": outcome_policy().to_dict(),
        "selection": {"aggregate_reaction_strictly_greater": True, "worst_fold_degradation_allowed": 0.0, "tie_break": ["aggregate_reaction_quality_desc", "worst_fold_reaction_quality_desc", "trial_id_asc"]},
        "holdout": {"open_only_after_finalist_freeze": True, "shared_stream_positions": HOLDOUT_BOUNDS, "targets": ["baseline", "finalist"]},
        "stop_rules": {"no_retry": True, "no_pagination": True, "no_fallback": True, "no_alternate_window": True},
        "protected_source_inventories": protected,
    }


def prepare_trial_root(*, trial_root: Path, scope: Mapping[str, Any]) -> None:
    if trial_root.exists():
        raise FreshWindowTrialError(f"fixed fresh-window trial root already exists; refusing rerun: {trial_root}")
    trial_root.mkdir(parents=True)
    (trial_root / "input").mkdir()
    _write_json(trial_root / "execution_scope.json", scope)


def persist_raw_fetch_evidence(*, trial_root: Path, raw: pd.DataFrame) -> Mapping[str, Any]:
    payload = raw.to_csv(index=False).encode("utf-8")
    raw_path = _atomic_write(trial_root / "input" / "raw_binance_response.csv", payload)
    manifest = {
        "trial_name": TRIAL_NAME,
        "execution_attempt": EXECUTION_ATTEMPT,
        "research_authorization_id": AUTHORIZATION_ID,
        "adapter_class": f"{BinanceNativeAdapter.__module__}.{BinanceNativeAdapter.__qualname__}",
        "request": request_parameters(),
        "raw_response_file": raw_path.name,
        "raw_row_count": len(raw),
        "raw_column_names": [str(column) for column in raw.columns],
        "raw_response_sha256": _sha256_bytes(payload),
    }
    _write_json(trial_root / "input" / "raw_fetch_manifest.json", manifest)
    return manifest


def persist_normalized_input(
    *,
    trial_root: Path,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    research_config: ResolvedTrendlineFamilyConfig,
) -> Mapping[str, Any]:
    payload = dataset.to_frame().to_csv(index_label="timestamp", float_format="%.17g").encode("utf-8")
    input_path = _atomic_write(trial_root / "input" / "normalized_ohlcv.csv", payload)
    manifest = {
        "asset": ASSET,
        "market": MARKET,
        "timeframe": TIMEFRAME,
        "request": request_parameters(),
        "row_count": dataset.row_count,
        "first_timestamp": _iso(dataset.timestamps[0]),
        "last_timestamp": _iso(dataset.timestamps[-1]),
        "dataset_hash": dataset.dataset_hash,
        "resolved_config_hash": config.resolved_config_hash,
        "research_config_hash": research_config.resolved_config_hash,
        "normalized_input_file": input_path.name,
        "normalized_input_sha256": _sha256_bytes(payload),
        "interval_seconds": TIMEFRAME_SECONDS,
        "complete_bars_only": True,
    }
    _write_json(trial_root / "input" / "input_manifest.json", manifest)
    return manifest


def _anchor_span_bars(candidate: LineCandidate) -> int:
    span_seconds = (candidate.anchors[-1].timestamp - candidate.anchors[0].timestamp).total_seconds()
    if span_seconds <= 0 or span_seconds % TIMEFRAME_SECONDS != 0:
        raise FreshWindowTrialError("candidate anchor span is not an exact positive 4h-bar count")
    return int(span_seconds // TIMEFRAME_SECONDS)


def _candidate_payload(candidate: LineCandidate) -> Mapping[str, Any]:
    span_bars = _anchor_span_bars(candidate)
    metadata = primitive(candidate.metadata)
    if not isinstance(metadata, Mapping):
        raise FreshWindowTrialError("candidate metadata is malformed")
    return {
        "candidate": candidate.to_dict(),
        "candidate_id": candidate.candidate_id,
        "role": candidate.role.value,
        "anchor_ids": [anchor.anchor_id for anchor in candidate.anchors],
        "anchor_timestamps": [_iso(anchor.timestamp) for anchor in candidate.anchors],
        "anchor_span_bars": span_bars,
        "anchor_span_seconds": span_bars * TIMEFRAME_SECONDS,
        "normalized_quality": candidate.diagnostics.normalized_quality,
        "coverage": candidate.diagnostics.coverage,
        "path_length": metadata.get("path_length"),
        "quality_method": metadata.get("quality_method"),
    }


def _stream_record(
    *,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    provider: LineCandidateProvider,
    fold_index: int | None,
    fold_id: str | None,
    position: int,
) -> Mapping[str, Any]:
    observed_at = dataset.timestamps[position]
    result = provider.generate(
        dataset.prefix(position), asset=ASSET, timeframe=TIMEFRAME, observed_at=observed_at, config=config
    )
    candidates = [_candidate_payload(candidate) for candidate in result.candidates]
    payload = {
        "fold_index": fold_index,
        "fold_id": fold_id,
        "position": position,
        "observed_at": _iso(observed_at),
        "provider_status": result.status.value,
        "reason_codes": list(result.reason_codes),
        "provider_metadata": primitive(result.metadata),
        "candidates": candidates,
    }
    return {**payload, "stream_record_id": semantic_id("trendline-family-saturating-quality-stream-record", payload)}


def _stream_identity(payload: Mapping[str, Any]) -> str:
    return semantic_id("trendline-family-saturating-quality-candidate-stream", payload)


def build_candidate_stream(
    *,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    provider: LineCandidateProvider,
    window_kind: str,
    finalist_freeze: FinalistFreeze | None = None,
) -> Mapping[str, Any]:
    if window_kind == "validation":
        positions = [
            (fold.fold_index, fold.fold_id, position)
            for fold in fold_plan.folds
            for position in range(fold.validation.start_position, fold.validation.end_position + 1)
        ]
    elif window_kind == "holdout":
        if finalist_freeze is None:
            raise FreshWindowTrialError("holdout candidate stream requires a frozen validation finalist")
        positions = [(None, fold_plan.holdout.holdout_plan_id, position) for position in range(HOLDOUT_BOUNDS[0], HOLDOUT_BOUNDS[1] + 1)]
    else:
        raise FreshWindowTrialError("candidate stream window kind is invalid")
    expected_calls = 288 if window_kind == "validation" else 96
    if len(positions) != expected_calls:
        raise FreshWindowTrialError("candidate stream position count drift")
    records = [
        _stream_record(dataset=dataset, config=config, provider=provider, fold_index=fold_index, fold_id=fold_id, position=position)
        for fold_index, fold_id, position in positions
    ]
    index_hash = semantic_id("trendline-family-saturating-quality-evaluated-index", [record["observed_at"] for record in records])
    semantic = {
        "stream_schema_version": STREAM_SCHEMA_VERSION,
        "window_kind": window_kind,
        "dataset_hash": dataset.dataset_hash,
        "research_config_hash": config.resolved_config_hash,
        "provider_identity": provider_identity(provider),
        "fold_plan_id": fold_plan.fold_plan_id,
        "holdout_plan_id": fold_plan.holdout.holdout_plan_id if window_kind == "holdout" else None,
        "finalist_freeze_id": None if finalist_freeze is None else finalist_freeze.freeze_id,
        "evaluated_index_hash": index_hash,
        "records": records,
    }
    return {**semantic, "candidate_stream_id": _stream_identity(semantic)}


def _write_stream(*, root: Path, stream: Mapping[str, Any]) -> Mapping[str, Any]:
    stream_path = _write_json(root / "candidate_stream.json", stream)
    manifest = {
        "stream_schema_version": STREAM_SCHEMA_VERSION,
        "candidate_stream_id": stream["candidate_stream_id"],
        "window_kind": stream["window_kind"],
        "record_count": len(stream["records"]),
        "provider_call_count": len(stream["records"]),
        "candidate_stream_sha256": _sha256_bytes(stream_path.read_bytes()),
        "evaluated_index_hash": stream["evaluated_index_hash"],
    }
    _write_json(root / "candidate_stream_manifest.json", manifest)
    return manifest


def _validate_stream(
    stream: Mapping[str, Any],
    *,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    window_kind: str,
    finalist_freeze: FinalistFreeze | None = None,
) -> None:
    if stream.get("stream_schema_version") != STREAM_SCHEMA_VERSION or stream.get("window_kind") != window_kind:
        raise FreshWindowTrialError("candidate stream schema or window kind drift")
    if stream.get("dataset_hash") != dataset.dataset_hash or stream.get("research_config_hash") is None:
        raise FreshWindowTrialError("candidate stream source identity drift")
    records = stream.get("records")
    if not isinstance(records, list):
        raise FreshWindowTrialError("candidate stream records are malformed")
    expected_count = 288 if window_kind == "validation" else 96
    expected_freeze_id = None if finalist_freeze is None else finalist_freeze.freeze_id
    if stream.get("finalist_freeze_id") != expected_freeze_id:
        raise FreshWindowTrialError("candidate stream finalist-freeze binding drift")
    if window_kind == "holdout" and finalist_freeze is None:
        raise FreshWindowTrialError("holdout candidate stream cannot validate without a frozen finalist")
    if len(records) != expected_count:
        raise FreshWindowTrialError("candidate stream record count drift")
    positions = [record.get("position") for record in records if isinstance(record, Mapping)]
    expected_positions = (
        [position for _, start, end in VALIDATION_BOUNDS for position in range(start, end + 1)]
        if window_kind == "validation"
        else list(range(HOLDOUT_BOUNDS[0], HOLDOUT_BOUNDS[1] + 1))
    )
    if positions != expected_positions:
        raise FreshWindowTrialError("candidate stream positions drift")
    for record in records:
        if not isinstance(record, Mapping):
            raise FreshWindowTrialError("candidate stream record is malformed")
        position = record["position"]
        if record.get("observed_at") != _iso(dataset.timestamps[position]):
            raise FreshWindowTrialError("candidate stream observed timestamp drift")
        candidates = record.get("candidates")
        if not isinstance(candidates, list):
            raise FreshWindowTrialError("candidate stream candidates are malformed")
        for candidate_payload in candidates:
            if not isinstance(candidate_payload, Mapping):
                raise FreshWindowTrialError("candidate stream candidate is malformed")
            candidate = LineCandidate.from_dict(candidate_payload["candidate"])
            if candidate.candidate_id != candidate_payload.get("candidate_id") or _anchor_span_bars(candidate) != candidate_payload.get("anchor_span_bars"):
                raise FreshWindowTrialError("candidate stream structural identity drift")
    semantic = {key: value for key, value in stream.items() if key != "candidate_stream_id"}
    if stream.get("candidate_stream_id") != _stream_identity(semantic):
        raise FreshWindowTrialError("candidate stream ID mismatch")


def load_candidate_stream(
    *,
    root: Path,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    window_kind: str,
    finalist_freeze: FinalistFreeze | None = None,
) -> Mapping[str, Any]:
    stream_path = root / "candidate_stream.json"
    manifest = _read_json(root / "candidate_stream_manifest.json", label="candidate stream manifest")
    stream = _read_json(stream_path, label="candidate stream")
    _validate_stream(
        stream,
        dataset=dataset,
        fold_plan=fold_plan,
        window_kind=window_kind,
        finalist_freeze=finalist_freeze,
    )
    if manifest.get("candidate_stream_id") != stream.get("candidate_stream_id") or manifest.get("candidate_stream_sha256") != _sha256_bytes(stream_path.read_bytes()):
        raise FreshWindowTrialError("candidate stream manifest binding mismatch")
    return stream


def _candidate_outcome(
    *,
    candidate: LineCandidate,
    position: int,
    frame: pd.DataFrame,
    policy: CandidateOutcomePolicy,
    end_position: int,
) -> Mapping[str, Any]:
    if position + policy.horizon_bars > end_position:
        return {"available": False, "reason": "outcome_horizon_unavailable"}
    try:
        atr = calculate_interaction_atr(frame.iloc[: position + 1], window=policy.atr_window).value
    except ContractValidationError:
        return {"available": False, "reason": "outcome_horizon_unavailable"}
    future = frame.iloc[position + 1 : position + policy.horizon_bars + 1]
    if len(future) != policy.horizon_bars:
        return {"available": False, "reason": "outcome_horizon_unavailable"}
    lines = [candidate.geometry.value_at(timestamp.to_pydatetime()) for timestamp in future.index]
    touch = any(
        float(row.low) <= line + policy.touch_tolerance_atr * atr and float(row.high) >= line - policy.touch_tolerance_atr * atr
        for row, line in zip(future.itertuples(), lines, strict=True)
    )
    if candidate.role is FamilyRole.SUPPORT:
        penetration = max(max(line - float(row.close), 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
        reaction = max(max(float(row.close) - line, 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
    else:
        penetration = max(max(float(row.close) - line, 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
        reaction = max(max(line - float(row.close), 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
    return {
        "available": True,
        "touched": float(touch),
        "survived": float(penetration <= policy.survival_penetration_atr),
        "reacted": float(touch and reaction >= policy.reaction_threshold_atr),
        "penetration": float(penetration),
        "atr": float(atr),
    }


def build_outcome_evidence(
    *,
    dataset: ImmutableHistoricalFrame,
    stream: Mapping[str, Any],
    window_kind: str,
) -> Mapping[str, Any]:
    frame = dataset.to_frame()
    validation_end_positions = {
        fold_index: end_position for fold_index, _, end_position in VALIDATION_BOUNDS
    }
    outcomes = []
    for record in stream["records"]:
        for candidate_payload in record["candidates"]:
            candidate = LineCandidate.from_dict(candidate_payload["candidate"])
            if window_kind == "holdout":
                end_position = HOLDOUT_BOUNDS[1]
            else:
                fold_index = record.get("fold_index")
                end_position = validation_end_positions.get(fold_index)
                if end_position is None:
                    raise FreshWindowTrialError("validation stream record has no declared fold boundary")
            outcome = _candidate_outcome(
                candidate=candidate,
                position=record["position"],
                frame=frame,
                policy=outcome_policy(),
                end_position=end_position,
            )
            payload = {
                "stream_record_id": record["stream_record_id"],
                "candidate_id": candidate.candidate_id,
                "position": record["position"],
                "outcome": outcome,
            }
            outcomes.append({**payload, "outcome_record_id": semantic_id("trendline-family-saturating-quality-outcome-record", payload)})
    semantic = {
        "outcome_schema_version": OUTCOME_SCHEMA_VERSION,
        "window_kind": window_kind,
        "dataset_hash": dataset.dataset_hash,
        "candidate_stream_id": stream["candidate_stream_id"],
        "outcome_policy": outcome_policy().to_dict(),
        "outcomes": outcomes,
    }
    return {**semantic, "outcome_evidence_id": semantic_id("trendline-family-saturating-quality-outcome-evidence", semantic)}


def _write_outcome_evidence(*, root: Path, evidence: Mapping[str, Any]) -> Path:
    return _write_json(root / "outcome_evidence.json", evidence)


def _validate_outcome_evidence(
    evidence: Mapping[str, Any],
    *,
    dataset: ImmutableHistoricalFrame,
    stream: Mapping[str, Any],
    window_kind: str,
) -> None:
    expected = build_outcome_evidence(dataset=dataset, stream=stream, window_kind=window_kind)
    if canonical_json(evidence) != canonical_json(expected):
        raise FreshWindowTrialError("outcome evidence differs from persisted stream rederivation")


def _saturating_score(*, anchor_span_bars: int, horizon_bars: int) -> Decimal:
    if anchor_span_bars < 1 or horizon_bars not in HORIZONS:
        raise FreshWindowTrialError("saturating score inputs are invalid")
    with localcontext() as context:
        context.prec = 50
        score = Decimal(anchor_span_bars) / (Decimal(anchor_span_bars) + Decimal(horizon_bars))
    if not Decimal(0) <= score < Decimal(1):
        raise FreshWindowTrialError("saturating score is outside [0, 1)")
    if (score >= SCORE_THRESHOLD) != (anchor_span_bars >= horizon_bars):
        raise FreshWindowTrialError("saturating threshold equivalence failed")
    return score


def _policy_from_trial(trial: TrialConfig) -> Mapping[str, Any]:
    context = dict(trial.evaluation_context)
    policy_id = context.get("quality_policy_id")
    if policy_id == "threshold_zero_candidate_control_v1":
        if set(context) != {"quality_policy_id"}:
            raise FreshWindowTrialError("baseline policy context drift")
        return {"policy_id": policy_id, "horizon_bars": None}
    if policy_id != "fixed_horizon_saturating_v1":
        raise FreshWindowTrialError("research policy identity is invalid")
    horizon = context.get("horizon_bars")
    if horizon not in HORIZONS or context.get("score_threshold") != "0.50" or context.get("equivalent_min_anchor_span_bars") != horizon:
        raise FreshWindowTrialError("research policy context drift")
    return {"policy_id": policy_id, "horizon_bars": horizon}


class PersistedStreamEvaluator:
    """External evaluator. Reads persisted streams and outcomes; never generates lines."""

    def __init__(
        self,
        *,
        dataset: ImmutableHistoricalFrame,
        research_config: ResolvedTrendlineFamilyConfig,
        spec: StageEvaluationSpec,
        validation_stream: Mapping[str, Any],
        validation_evidence: Mapping[str, Any],
        holdout_stream: Mapping[str, Any] | None = None,
        holdout_evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self.dataset = dataset
        self.research_config = research_config
        self._spec = spec
        self.validation_stream = validation_stream
        self.validation_evidence = validation_evidence
        self.holdout_stream = holdout_stream
        self.holdout_evidence = holdout_evidence

    def evaluation_spec(self) -> StageEvaluationSpec:
        return self._spec

    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult:
        if config.resolved_config_hash != self.research_config.resolved_config_hash or trial.evaluation_spec.spec_id != self._spec.spec_id:
            raise FreshWindowTrialError("stream evaluator config or spec drift")
        stream, evidence = self._sources(window_kind)
        if isinstance(window, WalkForwardFold):
            positions = range(window.validation.start_position, window.validation.end_position + 1)
            fold_id = window.fold_id
        else:
            positions = range(window.window.start_position, window.window.end_position + 1)
            fold_id = window.holdout_plan_id
        selected_positions = set(positions)
        records = [record for record in stream["records"] if record["position"] in selected_positions]
        if len(records) != len(selected_positions):
            raise FreshWindowTrialError("stream evaluator window positions drift")
        evidence_by_key = {(item["stream_record_id"], item["candidate_id"]): item["outcome"] for item in evidence["outcomes"]}
        policy = _policy_from_trial(trial)
        statuses = [record["provider_status"] for record in records]
        accepted: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
        for record in records:
            if record["provider_status"] != CandidateGenerationStatus.VALID.value:
                continue
            for candidate in record["candidates"]:
                span = candidate["anchor_span_bars"]
                if policy["horizon_bars"] is None:
                    accepted_flag = True
                    score = None
                else:
                    score = _saturating_score(anchor_span_bars=span, horizon_bars=policy["horizon_bars"])
                    accepted_flag = score >= SCORE_THRESHOLD
                if not accepted_flag:
                    continue
                outcome = evidence_by_key.get((record["stream_record_id"], candidate["candidate_id"]))
                if not isinstance(outcome, Mapping):
                    raise FreshWindowTrialError("stream evaluator outcome evidence is incomplete")
                accepted.append((record, candidate, outcome))
        outcomes = [outcome for _, _, outcome in accepted if outcome.get("available") is True]
        unavailable = sum(outcome.get("available") is not True for _, _, outcome in accepted)
        candidate_count = len(accepted)
        support_count = sum(candidate["role"] == FamilyRole.SUPPORT.value for _, candidate, _ in accepted)
        resistance_count = sum(candidate["role"] == FamilyRole.RESISTANCE.value for _, candidate, _ in accepted)
        producing_bars = len({record["position"] for record, _, _ in accepted})
        failures = sum(status == CandidateGenerationStatus.PROVIDER_CONFIG_ERROR.value for status in statuses)
        accepted_ids = sorted(candidate["candidate_id"] for _, candidate, _ in accepted)
        evaluated_index_hash = semantic_id(
            "trendline-family-saturating-quality-evaluated-index",
            [_iso(self.dataset.timestamps[position]) for position in sorted(selected_positions)],
        )
        forbidden = semantic_id(
            "trendline-family-saturating-quality-forbidden-output",
            {"dataset_hash": self.dataset.dataset_hash, "candidate_stream_id": stream["candidate_stream_id"], "outcome_evidence_id": evidence["outcome_evidence_id"], "evaluated_index_hash": evaluated_index_hash},
        )
        stage = semantic_id(
            "trendline-family-saturating-quality-stage-output",
            {"policy": policy, "accepted_candidate_ids": accepted_ids, "evaluated_index_hash": evaluated_index_hash},
        )
        metrics = (
            ratio_metric("candidate_coverage_ratio", numerator=producing_bars, denominator=len(records), sample_count=len(records)),
            MetricRecord("candidate_count", value=float(candidate_count), sample_count=len(records), valid_row_count=len(records)),
            ratio_metric("support_balance", numerator=support_count, denominator=candidate_count, sample_count=candidate_count),
            ratio_metric("resistance_balance", numerator=resistance_count, denominator=candidate_count, sample_count=candidate_count),
            ratio_metric("provider_failure_rate", numerator=failures, denominator=len(records), sample_count=len(records)),
            ratio_metric("candidates_per_bar", numerator=candidate_count, denominator=len(records), sample_count=len(records)),
            mean_metric("exact_line_future_touch_rate", [outcome["touched"] for outcome in outcomes], sample_count=len(outcomes) + unavailable, excluded_row_count=unavailable),
            mean_metric("geometry_survival_rate", [outcome["survived"] for outcome in outcomes], sample_count=len(outcomes) + unavailable, excluded_row_count=unavailable),
            mean_metric("reaction_quality", [outcome["reacted"] for outcome in outcomes], sample_count=len(outcomes) + unavailable, excluded_row_count=unavailable),
            mean_metric("normalized_penetration", [outcome["penetration"] for outcome in outcomes], sample_count=len(outcomes) + unavailable, excluded_row_count=unavailable),
        )
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=fold_id,
            window_kind=window_kind,
            metrics=metrics,
            evaluated_bar_count=len(records),
            excluded_reasons={"outcome_horizon_unavailable": unavailable},
            diagnostics={
                "candidate_stream_id": stream["candidate_stream_id"],
                "outcome_evidence_id": evidence["outcome_evidence_id"],
                "stage_output_fingerprint": stage,
                "forbidden_output_fingerprint": forbidden,
                "provider_status_counts": {status: statuses.count(status) for status in sorted(set(statuses))},
                "accepted_candidate_ids": accepted_ids,
                "accepted_producing_bar_count": producing_bars,
                "evaluated_index_hash": evaluated_index_hash,
                "causality_ok": True,
            },
        )

    def _sources(self, window_kind: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if window_kind == "validation":
            return self.validation_stream, self.validation_evidence
        if window_kind == "holdout" and self.holdout_stream is not None and self.holdout_evidence is not None:
            return self.holdout_stream, self.holdout_evidence
        raise FreshWindowTrialError("holdout stream is unavailable before finalist freeze")


def build_trial_configs(
    *,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    research_config: ResolvedTrendlineFamilyConfig,
    spec: StageEvaluationSpec,
) -> tuple[TrialConfig, tuple[TrialConfig, ...]]:
    common = {
        "stage": OptimizationStage.CANDIDATE_GEOMETRY,
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "parameter_overrides": {},
        "baseline_config_hash": research_config.resolved_config_hash,
        "dataset_hash": dataset.dataset_hash,
        "fold_plan_id": fold_plan.fold_plan_id,
        "objective": objective_spec(),
        "model_version": research_config.model_version,
        "config_version": research_config.config_version,
        "seed": 0,
        "evaluation_spec": spec,
    }
    baseline = TrialConfig(**common, evaluation_context={"quality_policy_id": "threshold_zero_candidate_control_v1"})
    primary = tuple(
        TrialConfig(
            **common,
            evaluation_context={
                "quality_policy_id": "fixed_horizon_saturating_v1",
                "horizon_bars": horizon,
                "score_threshold": "0.50",
                "equivalent_min_anchor_span_bars": horizon,
            },
        )
        for horizon in HORIZONS
    )
    if len(primary) != 4 or len({trial.trial_id for trial in primary}) != 4:
        raise FreshWindowTrialError("fixed primary policy enumeration drift")
    return baseline, primary


def _provider_failures(result: TrialResult) -> int:
    return sum(
        int(window.diagnostics.get("provider_status_counts", {}).get(CandidateGenerationStatus.PROVIDER_CONFIG_ERROR.value, 0))
        for window in result.window_results
    )


def attach_research_objective_gate(
    result: TrialResult,
    *,
    required_fold_count: int,
    baseline: TrialResult | None = None,
) -> TrialResult:
    gate = build_objective_gate(result, required_fold_count=required_fold_count, baseline=baseline)
    reasons = set(gate.rejection_reasons)
    if _provider_failures(result) != 0:
        reasons.add("provider_failures_present")
    gate = replace(gate, passed=not reasons, rejection_reasons=tuple(sorted(reasons)))
    return TrialResult(
        trial=result.trial,
        status=result.status,
        window_results=result.window_results,
        aggregate_metrics=result.aggregate_metrics,
        runtime_diagnostics=result.runtime_diagnostics,
        objective_gate=gate,
    )


def evaluate_validation(
    *,
    baseline: TrialConfig,
    primary: Sequence[TrialConfig],
    research_config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    evaluator: PersistedStreamEvaluator,
    spec: StageEvaluationSpec,
) -> tuple[TrialResult, tuple[TrialResult, ...]]:
    baseline_result = attach_research_objective_gate(
        run_validation_trial(trial=baseline, config=research_config, fold_plan=fold_plan, evaluator=evaluator, evaluation_spec=spec),
        required_fold_count=3,
    )
    results = tuple(
        attach_research_objective_gate(
            run_validation_trial(trial=trial, config=research_config, fold_plan=fold_plan, evaluator=evaluator, evaluation_spec=spec),
            required_fold_count=3,
            baseline=baseline_result,
        )
        for trial in primary
    )
    return baseline_result, results


def research_effect_audits(*, baseline: TrialResult, primary: Sequence[TrialResult]) -> Mapping[str, Any]:
    audits = []
    baseline_indices = [window.diagnostics["evaluated_index_hash"] for window in baseline.window_results]
    baseline_streams = [window.diagnostics["candidate_stream_id"] for window in baseline.window_results]
    baseline_forbidden = [window.diagnostics["forbidden_output_fingerprint"] for window in baseline.window_results]
    baseline_stage = [window.diagnostics["stage_output_fingerprint"] for window in baseline.window_results]
    for result in primary:
        horizon = _policy_from_trial(result.trial)["horizon_bars"]
        indexes = [window.diagnostics["evaluated_index_hash"] for window in result.window_results]
        streams = [window.diagnostics["candidate_stream_id"] for window in result.window_results]
        forbidden = [window.diagnostics["forbidden_output_fingerprint"] for window in result.window_results]
        stage = [window.diagnostics["stage_output_fingerprint"] for window in result.window_results]
        payload = {
            "horizon_bars": horizon,
            "baseline_result_id": baseline.result_id,
            "trial_result_id": result.result_id,
            "candidate_stream_ids_match_baseline": streams == baseline_streams,
            "evaluated_index_hashes_match_baseline": indexes == baseline_indices,
            "forbidden_output_fingerprints_match_baseline": forbidden == baseline_forbidden,
            "stage_output_changed_from_baseline": stage != baseline_stage,
            "geometry_or_dataset_mutation_detected": False,
        }
        effect = bool(payload["stage_output_changed_from_baseline"] and payload["candidate_stream_ids_match_baseline"])
        leakage = not (
            payload["candidate_stream_ids_match_baseline"]
            and payload["evaluated_index_hashes_match_baseline"]
            and payload["forbidden_output_fingerprints_match_baseline"]
            and not payload["geometry_or_dataset_mutation_detected"]
        )
        semantic = {**payload, "effect_detected": effect, "leakage_detected": leakage}
        audits.append({**semantic, "research_effect_audit_id": semantic_id("trendline-family-saturating-quality-research-effect", semantic)})
    payload = {"schema_version": "trendline_family_saturating_quality_effect_audits_v1", "baseline_result_id": baseline.result_id, "audits": audits}
    return {**payload, "research_effect_audits_id": semantic_id("trendline-family-saturating-quality-effect-audits", payload)}


def _reaction_value(result: TrialResult, name: str) -> float | None:
    metric = result.metric(name)
    return None if metric is None else metric.value


def select_external_research_finalist(
    *,
    baseline: TrialResult,
    primary: Sequence[TrialResult],
    effect_audits: Mapping[str, Any],
) -> Mapping[str, Any]:
    audits = {item["trial_result_id"]: item for item in effect_audits["audits"]}
    baseline_reaction = _reaction_value(baseline, "reaction_quality")
    baseline_worst = _reaction_value(baseline, "reaction_quality__worst")
    candidates = []
    assessments = []
    for result in primary:
        audit = audits.get(result.result_id)
        reaction = _reaction_value(result, "reaction_quality")
        worst = _reaction_value(result, "reaction_quality__worst")
        eligible = bool(
            result.status is TrialStatus.COMPLETED
            and result.objective_gate is not None
            and result.objective_gate.passed
            and isinstance(audit, Mapping)
            and audit.get("effect_detected") is True
            and audit.get("leakage_detected") is False
            and baseline_reaction is not None
            and reaction is not None
            and reaction > baseline_reaction
            and baseline_worst is not None
            and worst is not None
            and worst >= baseline_worst
        )
        assessment = {
            "trial_id": result.trial.trial_id,
            "result_id": result.result_id,
            "horizon_bars": _policy_from_trial(result.trial)["horizon_bars"],
            "aggregate_reaction_quality": reaction,
            "worst_fold_reaction_quality": worst,
            "eligible": eligible,
        }
        assessments.append(assessment)
        if eligible:
            candidates.append((result, assessment))
    if not candidates:
        semantic = {"decision": "REJECT_NO_VALIDATION_FINALIST", "baseline_result_id": baseline.result_id, "assessments": assessments, "finalist_result_id": None}
        return {**semantic, "research_decision_id": semantic_id("trendline-family-saturating-quality-selection", semantic)}
    winner, assessment = sorted(candidates, key=lambda item: (-item[1]["aggregate_reaction_quality"], -item[1]["worst_fold_reaction_quality"], item[0].trial.trial_id))[0]
    semantic = {"decision": "VALIDATION_FINALIST_FROZEN", "baseline_result_id": baseline.result_id, "assessments": assessments, "finalist_result_id": winner.result_id, "finalist_trial_id": winner.trial.trial_id, "finalist_horizon_bars": assessment["horizon_bars"]}
    return {**semantic, "research_decision_id": semantic_id("trendline-family-saturating-quality-selection", semantic)}


def _write_validation_artifacts(
    *,
    trial_root: Path,
    stream: Mapping[str, Any],
    evidence: Mapping[str, Any],
    baseline: TrialResult,
    primary: Sequence[TrialResult],
    audits: Mapping[str, Any],
) -> None:
    root = trial_root / "validation"
    root.mkdir()
    _write_stream(root=root, stream=stream)
    _write_outcome_evidence(root=root, evidence=evidence)
    _write_json(root / "baseline_result.json", baseline.to_dict())
    primary_payload = {"primary_results": [result.to_dict() for result in primary]}
    _write_json(root / "trial_results.json", {**primary_payload, "trial_results_id": semantic_id("trendline-family-saturating-quality-primary-results", primary_payload)})
    _write_json(root / "research_effect_audits.json", audits)


def _load_validation_results(root: Path) -> tuple[TrialResult, tuple[TrialResult, ...], Mapping[str, Any]]:
    baseline = TrialResult.from_dict(_read_json(root / "baseline_result.json", label="validation baseline result"))
    trials = _read_json(root / "trial_results.json", label="validation primary results")
    primary = tuple(TrialResult.from_dict(item) for item in trials.get("primary_results", ()))
    if len(primary) != 4:
        raise FreshWindowTrialError("validation primary result count drift")
    audits = _read_json(root / "research_effect_audits.json", label="research effect audits")
    return baseline, primary, audits


def _write_holdout_artifacts(
    *,
    trial_root: Path,
    stream: Mapping[str, Any],
    evidence: Mapping[str, Any],
    baseline: TrialResult,
    finalist: TrialResult,
    audits: Sequence[HoldoutOpenAudit],
) -> None:
    root = trial_root / "holdout"
    root.mkdir()
    _write_stream(root=root, stream=stream)
    _write_outcome_evidence(root=root, evidence=evidence)
    _write_json(root / "baseline_result.json", baseline.to_dict())
    _write_json(root / "finalist_result.json", finalist.to_dict())
    payload = {"holdout_open_audits": [audit.to_dict() for audit in audits]}
    _write_json(root / "holdout_open_audits.json", {**payload, "holdout_open_audits_id": semantic_id("trendline-family-saturating-quality-holdout-audits", payload)})


def _holdout_decision(*, baseline: TrialResult, finalist: TrialResult, freeze: FinalistFreeze) -> Mapping[str, Any]:
    baseline_reaction = _reaction_value(baseline, "reaction_quality")
    finalist_reaction = _reaction_value(finalist, "reaction_quality")
    baseline_worst = _reaction_value(baseline, "reaction_quality__worst")
    finalist_worst = _reaction_value(finalist, "reaction_quality__worst")
    matching_streams = [window.diagnostics.get("candidate_stream_id") for window in baseline.window_results] == [window.diagnostics.get("candidate_stream_id") for window in finalist.window_results]
    matching_indices = [window.diagnostics.get("evaluated_index_hash") for window in baseline.window_results] == [window.diagnostics.get("evaluated_index_hash") for window in finalist.window_results]
    leakage = any(window.diagnostics.get("causality_ok") is False for window in (*baseline.window_results, *finalist.window_results))
    advance = bool(
        baseline.status is TrialStatus.COMPLETED
        and finalist.status is TrialStatus.COMPLETED
        and baseline.objective_gate is not None
        and baseline.objective_gate.passed
        and finalist.objective_gate is not None
        and finalist.objective_gate.passed
        and matching_streams
        and matching_indices
        and not leakage
        and baseline_reaction is not None
        and finalist_reaction is not None
        and finalist_reaction > baseline_reaction
        and baseline_worst is not None
        and finalist_worst is not None
        and finalist_worst >= baseline_worst
    )
    semantic = {
        "decision": "ADVANCE_TO_CANONICAL_DESIGN" if advance else "REJECT_HOLDOUT_GATE",
        "research_only": True,
        "runtime_promotion_authorized": False,
        "finalist_freeze_id": freeze.freeze_id,
        "baseline_holdout_result_id": baseline.result_id,
        "finalist_holdout_result_id": finalist.result_id,
        "matching_streams": matching_streams,
        "matching_evaluated_indices": matching_indices,
        "leakage_detected": leakage,
        "baseline_reaction_quality": baseline_reaction,
        "finalist_reaction_quality": finalist_reaction,
        "baseline_worst_reaction_quality": baseline_worst,
        "finalist_worst_reaction_quality": finalist_worst,
    }
    return {**semantic, "research_decision_id": semantic_id("trendline-family-saturating-quality-decision", semantic)}


def _markdown(report: Mapping[str, Any]) -> str:
    chunks = ["# BTCUSDT 4h Saturating-Quality Fresh-Window Trial v1\n", "> Research-only structural evidence. No runtime, YAML, tracker, Regime, PnL, or promotion claim.\n"]
    for heading, value in report.items():
        chunks.append(f"## {heading.replace('_', ' ').title()}\n\n```json\n{json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)}\n```\n")
    return "\n".join(chunks)


def _build_report(*, scope: Mapping[str, Any], input_manifest: Mapping[str, Any], fold_plan: FoldPlan, baseline: TrialResult, primary: Sequence[TrialResult], audits: Mapping[str, Any], decision: Mapping[str, Any], freeze: FinalistFreeze | None = None, holdout_baseline: TrialResult | None = None, holdout_finalist: TrialResult | None = None) -> Mapping[str, Any]:
    return {
        "execution_scope": scope,
        "input_identity": input_manifest,
        "fold_plan": fold_plan.to_dict(),
        "validation_baseline": baseline.to_dict(),
        "validation_primary_results": [result.to_dict() for result in primary],
        "research_effect_audits": audits,
        "finalist_freeze": None if freeze is None else freeze.to_dict(),
        "holdout_baseline": None if holdout_baseline is None else holdout_baseline.to_dict(),
        "holdout_finalist": None if holdout_finalist is None else holdout_finalist.to_dict(),
        "research_decision": decision,
        "limitations": [
            "One asset and fresh bounded window do not establish runtime or trading quality.",
            "Structural outcome metrics are not PnL or directional evidence.",
            "Any advance requires separate canonical design and parity approval.",
        ],
    }


def _bundle_manifest(*, trial_root: Path, scope: Mapping[str, Any], input_manifest: Mapping[str, Any], decision: Mapping[str, Any]) -> Mapping[str, Any]:
    inventory = _file_inventory(trial_root, source_name="fresh_saturating_quality_trial", exclude=frozenset({"bundle_manifest.json"}))
    semantic = {
        "trial_schema_version": TRIAL_SCHEMA_VERSION,
        "execution_scope_sha256": _sha256_bytes((trial_root / "execution_scope.json").read_bytes()),
        "quality_study_id": QUALITY_STUDY_ID,
        "quality_source_binding_id": QUALITY_SOURCE_BINDING_ID,
        "dataset_hash": input_manifest["dataset_hash"],
        "resolved_config_hash": input_manifest["resolved_config_hash"],
        "research_config_hash": input_manifest["research_config_hash"],
        "research_decision_id": decision["research_decision_id"],
        "artifact_inventory": inventory,
    }
    return {**semantic, "bundle_id": semantic_id("trendline-family-saturating-quality-trial-bundle", semantic)}


def _write_report_and_manifest(*, trial_root: Path, report: Mapping[str, Any], scope: Mapping[str, Any], input_manifest: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    _atomic_write(trial_root / "trial_report.md", _markdown(report).encode("utf-8"))
    _write_json(trial_root / "bundle_manifest.json", _bundle_manifest(trial_root=trial_root, scope=scope, input_manifest=input_manifest, decision=decision))


def _finalize_decision_no_finalist(*, baseline: TrialResult, primary: Sequence[TrialResult], audits: Mapping[str, Any]) -> Mapping[str, Any]:
    selection = select_external_research_finalist(baseline=baseline, primary=primary, effect_audits=audits)
    if selection["decision"] != "REJECT_NO_VALIDATION_FINALIST":
        raise FreshWindowTrialError("validation finalist expected but no-finalist finalizer was invoked")
    semantic = {**selection, "research_only": True, "runtime_promotion_authorized": False, "provider_call_accounting": {"validation": 288, "holdout": 0, "total": 288}}
    return {**semantic, "research_decision_id": semantic_id("trendline-family-saturating-quality-decision", semantic)}


def _attach_decision_id(decision: Mapping[str, Any]) -> Mapping[str, Any]:
    semantic = {key: value for key, value in decision.items() if key != "research_decision_id"}
    return {**semantic, "research_decision_id": semantic_id("trendline-family-saturating-quality-decision", semantic)}


def execute_research_evaluation(
    *,
    trial_root: Path,
    dataset: ImmutableHistoricalFrame,
    research_config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
) -> Mapping[str, Any]:
    provider = NativeDeterministicLineProvider()
    provider_identity_value = provider_identity(provider)
    spec = evaluation_spec(research_config=research_config, provider_identity=provider_identity_value)
    validation_stream = build_candidate_stream(dataset=dataset, config=research_config, fold_plan=fold_plan, provider=provider, window_kind="validation")
    validation_evidence = build_outcome_evidence(dataset=dataset, stream=validation_stream, window_kind="validation")
    baseline_trial, primary_trials = build_trial_configs(dataset=dataset, fold_plan=fold_plan, research_config=research_config, spec=spec)
    evaluator = PersistedStreamEvaluator(dataset=dataset, research_config=research_config, spec=spec, validation_stream=validation_stream, validation_evidence=validation_evidence)
    baseline, primary = evaluate_validation(baseline=baseline_trial, primary=primary_trials, research_config=research_config, fold_plan=fold_plan, evaluator=evaluator, spec=spec)
    audits = research_effect_audits(baseline=baseline, primary=primary)
    _write_validation_artifacts(trial_root=trial_root, stream=validation_stream, evidence=validation_evidence, baseline=baseline, primary=primary, audits=audits)
    selection = select_external_research_finalist(baseline=baseline, primary=primary, effect_audits=audits)
    if selection["decision"] == "REJECT_NO_VALIDATION_FINALIST":
        decision = _finalize_decision_no_finalist(baseline=baseline, primary=primary, audits=audits)
        return {"baseline": baseline, "primary": primary, "audits": audits, "decision": decision, "freeze": None, "holdout_baseline": None, "holdout_finalist": None}
    finalist = next(result for result in primary if result.result_id == selection["finalist_result_id"])
    freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=fold_plan)
    _write_json(trial_root / "validation" / "finalist_freeze.json", freeze.to_dict())
    holdout_stream = build_candidate_stream(
        dataset=dataset,
        config=research_config,
        fold_plan=fold_plan,
        provider=provider,
        window_kind="holdout",
        finalist_freeze=freeze,
    )
    holdout_evidence = build_outcome_evidence(dataset=dataset, stream=holdout_stream, window_kind="holdout")
    evaluator = PersistedStreamEvaluator(
        dataset=dataset,
        research_config=research_config,
        spec=spec,
        validation_stream=validation_stream,
        validation_evidence=validation_evidence,
        holdout_stream=holdout_stream,
        holdout_evidence=holdout_evidence,
    )
    registry = HoldoutOpenRegistry()
    baseline_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=fold_plan, result=baseline, target="baseline")
    holdout_baseline = attach_research_objective_gate(
        evaluate_holdout_once(validation_finalist=baseline, baseline_config=research_config, fold_plan=fold_plan, evaluator=evaluator, finalist_freeze=freeze, holdout_open_audit=baseline_audit, holdout_open_registry=registry, evaluation_spec=spec),
        required_fold_count=1,
    )
    finalist_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=fold_plan, result=finalist, target="finalist")
    holdout_finalist = attach_research_objective_gate(
        evaluate_holdout_once(validation_finalist=finalist, baseline_config=research_config, fold_plan=fold_plan, evaluator=evaluator, finalist_freeze=freeze, holdout_open_audit=finalist_audit, holdout_open_registry=registry, evaluation_spec=spec, baseline_holdout=holdout_baseline),
        required_fold_count=1,
        baseline=holdout_baseline,
    )
    _write_holdout_artifacts(trial_root=trial_root, stream=holdout_stream, evidence=holdout_evidence, baseline=holdout_baseline, finalist=holdout_finalist, audits=(baseline_audit, finalist_audit))
    decision = _holdout_decision(baseline=holdout_baseline, finalist=holdout_finalist, freeze=freeze)
    decision = _attach_decision_id({**decision, "provider_call_accounting": {"validation": 288, "holdout": 96, "total": 384}})
    return {"baseline": baseline, "primary": primary, "audits": audits, "decision": decision, "freeze": freeze, "holdout_baseline": holdout_baseline, "holdout_finalist": holdout_finalist}


def _validate_bundle_manifest(*, trial_root: Path, scope: Mapping[str, Any], input_manifest: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    manifest = _read_json(trial_root / "bundle_manifest.json", label="bundle manifest")
    expected = _bundle_manifest(trial_root=trial_root, scope=scope, input_manifest=input_manifest, decision=decision)
    if canonical_json(manifest) != canonical_json(expected):
        raise FreshWindowTrialError("bundle manifest differs from independent rederivation")


def _same_semantic_result(left: TrialResult, right: TrialResult) -> bool:
    """Compare immutable result evidence while excluding operational runtime timing."""

    return (
        left.result_id == right.result_id
        and canonical_json(left.identity_payload()) == canonical_json(right.identity_payload())
    )


def validate_trial_bundle(*, trial_root: Path = TRIAL_ROOT) -> Mapping[str, Any]:
    scope = _read_json(trial_root / "execution_scope.json", label="execution scope")
    if scope.get("trial_name") != TRIAL_NAME or scope.get("research_authorization_id") != AUTHORIZATION_ID:
        raise FreshWindowTrialError("execution scope identity drift")
    quality_bundle = validate_approved_quality_sources()
    before = protected_source_inventories()
    if canonical_json(scope.get("protected_source_inventories")) != canonical_json(before):
        raise FreshWindowTrialError("protected source inventories differ from execution scope")
    config = resolve_baseline_config()
    research_config = research_generation_config(config)
    expected_scope = _scope_payload(
        config=config,
        research_config=research_config,
        quality_bundle=quality_bundle,
        protected=before,
    )
    if canonical_json(scope) != canonical_json(expected_scope):
        raise FreshWindowTrialError("execution scope differs from deterministic rederivation")
    raw_manifest = _read_json(trial_root / "input" / "raw_fetch_manifest.json", label="raw fetch manifest")
    raw_path = trial_root / "input" / str(raw_manifest.get("raw_response_file"))
    expected_raw_manifest = {
        "trial_name": TRIAL_NAME,
        "execution_attempt": EXECUTION_ATTEMPT,
        "research_authorization_id": AUTHORIZATION_ID,
        "adapter_class": f"{BinanceNativeAdapter.__module__}.{BinanceNativeAdapter.__qualname__}",
        "request": request_parameters(),
        "raw_response_file": "raw_binance_response.csv",
    }
    if (
        any(raw_manifest.get(key) != value for key, value in expected_raw_manifest.items())
        or _sha256_bytes(raw_path.read_bytes()) != raw_manifest.get("raw_response_sha256")
    ):
        raise FreshWindowTrialError("raw request evidence binding mismatch")
    input_manifest = _read_json(trial_root / "input" / "input_manifest.json", label="input manifest")
    dataset = load_normalized_input(trial_root=trial_root, input_manifest=input_manifest)
    raw_dataset = normalize_and_preflight(pd.read_csv(raw_path))
    if (
        raw_dataset.dataset_hash != dataset.dataset_hash
        or input_manifest.get("dataset_hash") != dataset.dataset_hash
        or input_manifest.get("research_config_hash") != research_config.resolved_config_hash
        or input_manifest.get("resolved_config_hash") != config.resolved_config_hash
        or input_manifest.get("request") != request_parameters()
    ):
        raise FreshWindowTrialError("input manifest identity drift")
    fold_plan = build_fixed_fold_plan(dataset)
    validate_fixed_fold_plan(dataset, fold_plan)
    validation_root = trial_root / "validation"
    validation_stream = load_candidate_stream(root=validation_root, dataset=dataset, fold_plan=fold_plan, window_kind="validation")
    validation_evidence = _read_json(validation_root / "outcome_evidence.json", label="validation outcome evidence")
    _validate_outcome_evidence(validation_evidence, dataset=dataset, stream=validation_stream, window_kind="validation")
    baseline, primary, audits = _load_validation_results(validation_root)
    spec = baseline.trial.evaluation_spec
    evaluator = PersistedStreamEvaluator(dataset=dataset, research_config=research_config, spec=spec, validation_stream=validation_stream, validation_evidence=validation_evidence)
    expected_baseline, expected_primary = evaluate_validation(baseline=baseline.trial, primary=tuple(result.trial for result in primary), research_config=research_config, fold_plan=fold_plan, evaluator=evaluator, spec=spec)
    if not _same_semantic_result(baseline, expected_baseline) or any(
        not _same_semantic_result(actual, expected)
        for actual, expected in zip(primary, expected_primary, strict=True)
    ):
        raise FreshWindowTrialError("validation result differs from persisted-stream rederivation")
    expected_audits = research_effect_audits(baseline=baseline, primary=primary)
    if canonical_json(audits) != canonical_json(expected_audits):
        raise FreshWindowTrialError("research effect audits differ from rederivation")
    selection = select_external_research_finalist(baseline=baseline, primary=primary, effect_audits=audits)
    decision = _read_json(trial_root / "research_decision.json", label="research decision")
    freeze_path = validation_root / "finalist_freeze.json"
    holdout_root = trial_root / "holdout"
    if selection["decision"] == "REJECT_NO_VALIDATION_FINALIST":
        expected_decision = _finalize_decision_no_finalist(baseline=baseline, primary=primary, audits=audits)
        if freeze_path.exists() or holdout_root.exists() or canonical_json(decision) != canonical_json(expected_decision):
            raise FreshWindowTrialError("no-finalist holdout or decision contract violation")
    else:
        if not freeze_path.is_file() or not holdout_root.is_dir():
            raise FreshWindowTrialError("finalist holdout artifacts are missing")
        freeze = FinalistFreeze.from_dict(_read_json(freeze_path, label="finalist freeze"))
        finalist = next(result for result in primary if result.result_id == selection["finalist_result_id"])
        expected_freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=fold_plan)
        if freeze != expected_freeze:
            raise FreshWindowTrialError("finalist freeze differs from deterministic selection")
        holdout_stream = load_candidate_stream(
            root=holdout_root,
            dataset=dataset,
            fold_plan=fold_plan,
            window_kind="holdout",
            finalist_freeze=freeze,
        )
        holdout_evidence = _read_json(holdout_root / "outcome_evidence.json", label="holdout outcome evidence")
        _validate_outcome_evidence(holdout_evidence, dataset=dataset, stream=holdout_stream, window_kind="holdout")
        evaluator = PersistedStreamEvaluator(dataset=dataset, research_config=research_config, spec=spec, validation_stream=validation_stream, validation_evidence=validation_evidence, holdout_stream=holdout_stream, holdout_evidence=holdout_evidence)
        stored_baseline = TrialResult.from_dict(_read_json(holdout_root / "baseline_result.json", label="holdout baseline result"))
        stored_finalist = TrialResult.from_dict(_read_json(holdout_root / "finalist_result.json", label="holdout finalist result"))
        audits_payload = _read_json(holdout_root / "holdout_open_audits.json", label="holdout open audits")
        stored_audits = tuple(HoldoutOpenAudit.from_dict(item) for item in audits_payload.get("holdout_open_audits", ()))
        if len(stored_audits) != 2:
            raise FreshWindowTrialError("holdout audit count drift")
        registry = HoldoutOpenRegistry()
        baseline_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=fold_plan, result=baseline, target="baseline")
        expected_holdout_baseline = attach_research_objective_gate(evaluate_holdout_once(validation_finalist=baseline, baseline_config=research_config, fold_plan=fold_plan, evaluator=evaluator, finalist_freeze=freeze, holdout_open_audit=baseline_audit, holdout_open_registry=registry, evaluation_spec=spec), required_fold_count=1)
        finalist_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=fold_plan, result=finalist, target="finalist")
        expected_holdout_finalist = attach_research_objective_gate(evaluate_holdout_once(validation_finalist=finalist, baseline_config=research_config, fold_plan=fold_plan, evaluator=evaluator, finalist_freeze=freeze, holdout_open_audit=finalist_audit, holdout_open_registry=registry, evaluation_spec=spec, baseline_holdout=expected_holdout_baseline), required_fold_count=1, baseline=expected_holdout_baseline)
        if (
            not _same_semantic_result(stored_baseline, expected_holdout_baseline)
            or not _same_semantic_result(stored_finalist, expected_holdout_finalist)
            or tuple(stored_audits) != (baseline_audit, finalist_audit)
        ):
            raise FreshWindowTrialError("holdout results differ from persisted-stream rederivation")
        expected_decision = _attach_decision_id({**_holdout_decision(baseline=stored_baseline, finalist=stored_finalist, freeze=freeze), "provider_call_accounting": {"validation": 288, "holdout": 96, "total": 384}})
        if canonical_json(decision) != canonical_json(expected_decision):
            raise FreshWindowTrialError("holdout decision differs from rederivation")
    report_path = trial_root / "trial_report.md"
    report = _build_report(scope=scope, input_manifest=input_manifest, fold_plan=fold_plan, baseline=baseline, primary=primary, audits=audits, decision=decision, freeze=None if not freeze_path.is_file() else FinalistFreeze.from_dict(_read_json(freeze_path, label="finalist freeze")), holdout_baseline=None if not holdout_root.is_dir() else TrialResult.from_dict(_read_json(holdout_root / "baseline_result.json", label="holdout baseline result")), holdout_finalist=None if not holdout_root.is_dir() else TrialResult.from_dict(_read_json(holdout_root / "finalist_result.json", label="holdout finalist result")))
    if report_path.read_bytes() != _markdown(report).encode("utf-8"):
        raise FreshWindowTrialError("trial report differs from verified artifacts")
    _validate_bundle_manifest(trial_root=trial_root, scope=scope, input_manifest=input_manifest, decision=decision)
    after = protected_source_inventories()
    if canonical_json(before) != canonical_json(after):
        raise FreshWindowTrialError("protected source bytes changed during trial validation")
    return {"scope": scope, "input_manifest": input_manifest, "baseline": baseline, "primary": primary, "decision": decision, "quality_bundle": quality_bundle}


async def run_trial(*, adapter_factory: Callable[[], HistoricalAdapter] = BinanceNativeAdapter, trial_root: Path = TRIAL_ROOT) -> Mapping[str, Path]:
    quality_bundle = validate_approved_quality_sources()
    protected_before = protected_source_inventories()
    config = resolve_baseline_config()
    research_config = research_generation_config(config)
    scope = _scope_payload(config=config, research_config=research_config, quality_bundle=quality_bundle, protected=protected_before)
    prepare_trial_root(trial_root=trial_root, scope=scope)
    raw = await fetch_bounded_ohlcv(adapter_factory())
    persist_raw_fetch_evidence(trial_root=trial_root, raw=raw)
    dataset = normalize_and_preflight(raw)
    input_manifest = persist_normalized_input(trial_root=trial_root, dataset=dataset, config=config, research_config=research_config)
    dataset = load_normalized_input(trial_root=trial_root, input_manifest=input_manifest)
    fold_plan = build_fixed_fold_plan(dataset)
    validate_fixed_fold_plan(dataset, fold_plan)
    evaluation = execute_research_evaluation(trial_root=trial_root, dataset=dataset, research_config=research_config, fold_plan=fold_plan)
    decision = evaluation["decision"]
    _write_json(trial_root / "research_decision.json", decision)
    report = _build_report(scope=scope, input_manifest=input_manifest, fold_plan=fold_plan, baseline=evaluation["baseline"], primary=evaluation["primary"], audits=evaluation["audits"], decision=decision, freeze=evaluation["freeze"], holdout_baseline=evaluation["holdout_baseline"], holdout_finalist=evaluation["holdout_finalist"])
    _write_report_and_manifest(trial_root=trial_root, report=report, scope=scope, input_manifest=input_manifest, decision=decision)
    validate_trial_bundle(trial_root=trial_root)
    if canonical_json(protected_before) != canonical_json(protected_source_inventories()):
        raise FreshWindowTrialError("protected source bytes changed during trial")
    return {"trial_root": trial_root, "decision": trial_root / "research_decision.json", "bundle_manifest": trial_root / "bundle_manifest.json", "report": trial_root / "trial_report.md"}


def main() -> None:
    paths = asyncio.run(run_trial())
    print(json.dumps({name: str(path) for name, path in sorted(paths.items())}, sort_keys=True))


if __name__ == "__main__":
    main()
