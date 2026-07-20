"""Network-free SR-V2.3 replay, calibration, and evidence orchestration."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.models.sr.detection.causal_swing_reversal import (
    CausalSwingReversalConfig,
    detect_causal_swing_reversal_bands,
)
from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.provenance.repository import (
    repository_commit,
    resolve_repository_path,
)

from .artifacts import publish_evaluation_bundle
from .calibration import HistoricalLabel, calibrate
from .config import AdaptiveContextCalibrationConfig, load_adaptive_context_calibration_config
from .contracts import (
    CANONICAL_COHORTS,
    CandidateCase,
    CaseMembership,
    NormalizationStatus,
    PredictionRecord,
    SalienceBucket,
    StudyResult,
    SwingObservation,
    V23SourceBundle,
    V23SourceMember,
)
from .metrics import bootstrap_summary, compute_metrics, disposition
from .normalization import NormalizationResult, SaliencePoint, normalize_salience
from .outcomes import build_candidate_cases, build_model_bars, build_swing_observations
from .source import source_bundle_for_offline_evaluation


@dataclass(frozen=True)
class CohortReplay:
    member: V23SourceMember
    model_bar_count: int
    observations: tuple[SwingObservation, ...]
    normalization: dict[tuple[str, str, str], NormalizationResult]
    cases: tuple[CandidateCase, ...]


def _cohort_key(member: V23SourceMember) -> str:
    return f"{member.asset}/{member.timeframe}"


def _cohort_index(member: V23SourceMember) -> int:
    try:
        return CANONICAL_COHORTS.index((member.asset, member.timeframe))
    except ValueError as exc:
        raise ContractValidationError("source member is outside canonical V2.3 cohorts") from exc


def _normalize_observations(
    member: V23SourceMember,
    bars: tuple,
    observations: tuple[SwingObservation, ...],
    *,
    config: AdaptiveContextCalibrationConfig,
) -> dict[tuple[str, str, str], NormalizationResult]:
    points = tuple(
        SaliencePoint(
            asset=member.asset,
            timeframe=member.timeframe,
            confirmation_at=bars[item.confirmation_index].closed_at,
            raw_salience_atr=item.raw_salience_atr,
        )
        for item in observations
    )
    result: dict[tuple[str, str, str], NormalizationResult] = {}
    for index, (observation, point) in enumerate(zip(observations, points)):
        result[(member.asset, member.timeframe, observation.confirmation_bar_id)] = normalize_salience(
            point,
            points[:index],
            history_days=config.normalization.expected["history_days"],
        )
    return result


def _replay_cohort(
    member: V23SourceMember,
    *,
    config: AdaptiveContextCalibrationConfig,
) -> CohortReplay:
    model_bars = build_model_bars(member, config=config)
    observations, _ = build_swing_observations(member, model_bars)
    normalization = _normalize_observations(member, model_bars, observations, config=config)
    cases = build_candidate_cases(
        member,
        model_bars,
        observations,
        config=config,
        normalized=normalization,
    )
    return CohortReplay(member, len(model_bars), observations, normalization, cases)


def _historical_labels(cases: tuple[CandidateCase, ...]) -> tuple[HistoricalLabel, ...]:
    return tuple(
        HistoricalLabel(
            asset=item.asset,
            timeframe=item.timeframe,
            bucket=item.bucket,
            label=item.label,
            label_available_at=item.label_available_at,
            paired_excess_quality_atr=item.paired_excess_quality_atr,
        )
        for item in cases
        if item.normalization_status is NormalizationStatus.READY
        and type(item.bucket) is SalienceBucket
        and item.label in (0, 1)
        and item.label_available_at is not None
        and item.paired_excess_quality_atr is not None
    )


def _build_predictions(
    cases: tuple[CandidateCase, ...],
    *,
    labels: tuple[HistoricalLabel, ...],
) -> tuple[PredictionRecord, ...]:
    predictions = []
    for case in cases:
        if case.membership is CaseMembership.HISTORY_ONLY:
            continue
        if case.normalization_status is not NormalizationStatus.READY:
            continue
        if type(case.bucket) is not SalienceBucket:
            raise ContractValidationError("ready V2.3 case has no salience bucket")
        calibration = calibrate(
            target_asset=case.asset,
            target_timeframe=case.timeframe,
            bucket=case.bucket,
            prediction_at=case.candidate.available_at,
            labels=labels,
        )
        predictions.append(
            PredictionRecord(
                case_id=case.case_id,
                asset=case.asset,
                timeframe=case.timeframe,
                fold=case.fold,
                prediction_at=case.candidate.available_at,
                bucket=case.bucket,
                adaptive_global=calibration.global_state,
                adaptive_asset=calibration.asset_state,
                adaptive_final=calibration.final_state,
                null=calibration.null_state,
                label=case.label,
                label_available_at=case.label_available_at,
            )
        )
    return tuple(predictions)


def _source_diagnostics(source_bundle: V23SourceBundle) -> dict[str, Any]:
    return {
        _cohort_key(member): {
            "row_count": member.row_count,
            "first_open_time": member.first_open_time.isoformat().replace("+00:00", "Z"),
            "last_closed_at": member.last_closed_at.isoformat().replace("+00:00", "Z"),
            "bars_sha256": member.bars_sha256,
            "grid_sha256": member.grid_sha256,
            "source_id": member.source_id,
            "source_bundle_id": member.source_bundle_id,
            "provider_calls": member.provider_calls,
            "source_kind": member.source_kind,
        }
        for member in source_bundle.assets
    }


def _candidate_diagnostics(replays: tuple[CohortReplay, ...]) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for replay in replays:
        key = _cohort_key(replay.member)
        candidates = [item for item in replay.observations if item.candidate is not None]
        in_fold = [item for item in replay.cases]
        diagnostics[key] = {
            "model_bar_count": replay.model_bar_count,
            "swing_confirmation_count": len(replay.observations),
            "candidate_count": len(candidates),
            "zero_wick_confirmation_count": len(replay.observations) - len(candidates),
            "in_fold_candidate_case_count": len(in_fold),
            "history_only_case_count": sum(
                item.membership is CaseMembership.HISTORY_ONLY for item in in_fold
            ),
            "normalization_warmup_case_count": sum(
                item.normalization_status is NormalizationStatus.NORMALIZATION_WARMUP
                for item in in_fold
            ),
            "ready_case_count": sum(
                item.normalization_status is NormalizationStatus.READY for item in in_fold
            ),
            "labeled_case_count": sum(item.label in (0, 1) for item in in_fold),
            "completed_real_outcome_count": sum(item.real_status.value == "COMPLETED" for item in in_fold),
            "right_censored_real_outcome_count": sum(item.real_status.value == "RIGHT_CENSORED" for item in in_fold),
        }
    return diagnostics


def _normalization_diagnostics(replays: tuple[CohortReplay, ...]) -> dict[str, Any]:
    return {
        _cohort_key(replay.member): {
            "confirmation_count": len(replay.normalization),
            "warmup_count": sum(
                item.status is NormalizationStatus.NORMALIZATION_WARMUP
                for item in replay.normalization.values()
            ),
            "ready_count": sum(
                item.status is NormalizationStatus.READY for item in replay.normalization.values()
            ),
            "prior_count_min": min((item.prior_count for item in replay.normalization.values()), default=0),
            "prior_count_max": max((item.prior_count for item in replay.normalization.values()), default=0),
        }
        for replay in replays
    }


def _fixed_v22_diagnostic(
    replays: tuple[CohortReplay, ...],
    *,
    config: AdaptiveContextCalibrationConfig,
) -> dict[str, Any]:
    reference = next(
        (item for item in replays if (item.member.asset, item.member.timeframe) == ("TAOUSDT", "1d")),
        None,
    )
    if reference is None:
        raise ContractValidationError("V2.3 source is missing the fixed V2.2 diagnostic cohort")
    model_bars = build_model_bars(reference.member, config=config)
    emitted = detect_causal_swing_reversal_bands(model_bars, CausalSwingReversalConfig(1.5))
    return {
        "scope": "TAOUSDT/1d",
        "candidate_count": len(emitted),
        "detector": "causal_swing_reversal_v2_2",
        "reversal_atr": 1.5,
        "affects_v2_3_disposition": False,
    }

def compute_study(
    config: AdaptiveContextCalibrationConfig,
    *,
    source_bundle: V23SourceBundle,
    implementation_commit: str,
) -> StudyResult:
    """Replay all six cohorts from immutable source bytes without network access."""

    if type(config) is not AdaptiveContextCalibrationConfig or type(source_bundle) is not V23SourceBundle:
        raise ContractValidationError("V2.3 study requires typed config and source bundle")
    if source_bundle.config_hash != config.config_hash:
        raise ContractValidationError("V2.3 source/config identities do not match")
    if tuple((item.asset, item.timeframe) for item in source_bundle.assets) != CANONICAL_COHORTS:
        raise ContractValidationError("V2.3 source cohort order is invalid")
    replays = tuple(_replay_cohort(member, config=config) for member in source_bundle.assets)
    swings = tuple(item for replay in replays for item in replay.observations)
    unsorted_cases = tuple(item for replay in replays for item in replay.cases)
    cases = tuple(
        sorted(
            unsorted_cases,
            key=lambda item: (
                item.candidate.available_at,
                CANONICAL_COHORTS.index((item.asset, item.timeframe)),
                item.case_id,
            ),
        )
    )
    labels = _historical_labels(cases)
    predictions = _build_predictions(cases, labels=labels)
    metrics = compute_metrics(predictions, cases)
    metrics["source_diagnostics"] = _source_diagnostics(source_bundle)
    metrics["candidate_diagnostics"] = _candidate_diagnostics(replays)
    metrics["normalization_diagnostics"] = _normalization_diagnostics(replays)
    metrics["fixed_v2_2_detector_candidate_counts"] = _fixed_v22_diagnostic(replays, config=config)
    metrics["historical_label_count"] = len(labels)
    metrics["history_only_case_count"] = sum(
        item.membership is CaseMembership.HISTORY_ONLY for item in cases
    )
    metrics["cohort_case_counts"] = dict(Counter(_cohort_key(replay.member) for replay in replays for _ in replay.cases))
    metrics["cohort_prediction_counts"] = dict(Counter(f"{item.asset}/{item.timeframe}" for item in predictions))
    boot = bootstrap_summary(predictions, cases, config=config)
    return StudyResult(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        source_bundle_id=source_bundle.bundle_id,
        swings=swings,
        cases=cases,
        predictions=predictions,
        metrics=metrics,
        bootstrap=boot,
        disposition=disposition(boot),
    )


def run_evaluation(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    source_bundle_path: str | Path,
    implementation_commit: str | None = None,
) -> tuple[str, Path, StudyResult]:
    """Run and publish one network-free evaluation from a frozen source bundle."""

    config = load_adaptive_context_calibration_config(str(config_path))
    source_bundle = source_bundle_for_offline_evaluation(
        config,
        repo_root=repo_root,
        source_bundle_path=source_bundle_path,
    )
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_study(config, source_bundle=source_bundle, implementation_commit=commit)
    output_root = resolve_repository_path(
        repo_root,
        config.artifact.output_root,
        field_name="artifact.output_root",
    )
    bundle_id, path = publish_evaluation_bundle(study, config=config, output_root=output_root)
    return bundle_id, path, study


__all__ = [
    "CohortReplay",
    "compute_study",
    "run_evaluation",
]
