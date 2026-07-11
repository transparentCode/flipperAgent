"""Optional HMM-backed state model for RegimeProbV1 semantic state probabilities."""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from scipy.special import logsumexp
from scipy.stats import t as student_t

from libs.models.regime_prob_v1.overlays import build_state_proxy_frame, state_entropy
from libs.models.regime_prob_v1.state.semantic_mapper import (
    SEMANTIC_STATES,
    SemanticMappingResult,
    map_latent_states,
)
from libs.models.regime_prob_v1.state.transition_risk import (
    combine_transition_probability,
    posterior_shift_series,
    transition_matrix_self_probability,
)

logger = logging.getLogger(__name__)

_EPS = 1e-10
_PROXY_FALLBACK_SOURCE = "deterministic_proxy_fallback"
_PROXY_FALLBACK_NOTE = (
    "The HMM state model was requested but fell back to deterministic RegimeV2 "
    "proxy states because there was insufficient usable history or the HMM fit "
    "did not converge safely."
)
_HMM_SOURCE = "hmm_state_model"
_HMM_SOURCE_NOTE = (
    "Semantic state probabilities are derived from causal forward-filtered HMM "
    "latent-state posteriors mapped onto RegimeProbV1 state labels. This "
    "remains a shadow/research overlay and does not authorize forced trades."
)
_EVAL_MODE_PROXY_FALLBACK = "proxy_fallback"
_EVAL_MODE_IN_SAMPLE_FIT = "in_sample_fit"
_EVAL_MODE_OOS_FILTERED = "oos_filtered"
_STATE_COLUMNS = tuple(f"p_{name}_state" for name in SEMANTIC_STATES)
_DEFAULT_STATE_FEATURE_COLUMNS = (
    "trend_strength",
    "trend_persistence",
    "trend_confidence",
    "volatility_percentile",
    "compression_score",
    "shock_risk",
    "mean_reversion_score",
    "range_quality",
    "chop_risk",
    "structural_break_risk",
    "breakout_quality",
    "false_breakout_risk",
    "confidence",
    "uncertainty",
    "changepoint_prob",
    "cp_recent_max",
    "transition_risk_raw",
    "hurst",
)


@dataclass(frozen=True)
class HMMStateModelConfig:
    """Config for the optional HMM-backed semantic state model."""

    min_train_bars: int = 200
    retrain_window: int = 500
    hmm_n_states: int = 0
    hmm_max_states: int = 4
    hmm_covariance_type: Literal["diag", "full"] = "diag"
    hmm_robust_scoring: bool = True
    hmm_student_df: float = 5.0
    fit_iterations: int = 100
    min_active_features: int = 6
    feature_columns: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_STATE_FEATURE_COLUMNS)


@dataclass(frozen=True)
class HMMStateModelResult:
    """State-model output frame plus metadata."""

    frame: pd.DataFrame
    state_source: str
    state_source_note: str
    diagnostics: dict[str, Any]


class HMMStateModel:
    """Build semantic state probabilities from an HMM over PIT regime features."""

    def __init__(self, config: HMMStateModelConfig | None = None) -> None:
        self.config = config or HMMStateModelConfig()
        self._diag = self._empty_diagnostics()

    def analyze(self, feature_frame: pd.DataFrame) -> HMMStateModelResult:
        """Return HMM-backed semantic state probabilities or a proxy fallback."""
        base = _default_output_frame(feature_frame, max_states=self._max_state_slots())
        feature_matrix = self._build_feature_matrix(feature_frame)
        diagnostics = {
            "status": "fallback_proxy",
            "ready": False,
            "used_feature_columns": (),
            "usable_rows": 0,
            "classified_rows": 0,
            "fit_diagnostics": {},
            "mapping_history": [],
            "posterior_filter": "causal_forward",
            "emission_model": "student_t" if self.config.hmm_robust_scoring else "gaussian",
            "hmm_in_sample_rows": 0,
            "hmm_oos_filtered_rows": 0,
            "hmm_proxy_fallback_rows": int(len(base)),
        }
        if feature_matrix is None:
            diagnostics["reason"] = "insufficient_usable_features"
            return HMMStateModelResult(
                frame=base,
                state_source=_PROXY_FALLBACK_SOURCE,
                state_source_note=_PROXY_FALLBACK_NOTE,
                diagnostics=diagnostics,
            )

        matrix, usable_frame, used_columns = feature_matrix
        diagnostics["used_feature_columns"] = tuple(used_columns)
        diagnostics["usable_rows"] = int(len(usable_frame))
        if len(usable_frame) < self.config.min_train_bars:
            diagnostics["reason"] = "insufficient_usable_rows"
            return HMMStateModelResult(
                frame=base,
                state_source=_PROXY_FALLBACK_SOURCE,
                state_source_note=_PROXY_FALLBACK_NOTE,
                diagnostics=diagnostics,
            )

        try:
            classified, fit_diag = self._classify_series(usable_frame, matrix)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("RegimeProbV1 HMM state model failed; falling back to proxy: %s", exc)
            diagnostics["reason"] = str(exc)
            return HMMStateModelResult(
                frame=base,
                state_source=_PROXY_FALLBACK_SOURCE,
                state_source_note=_PROXY_FALLBACK_NOTE,
                diagnostics=diagnostics,
            )

        if fit_diag["classified_rows"] <= 0:
            diagnostics.update(fit_diag)
            diagnostics["reason"] = "no_rows_classified"
            return HMMStateModelResult(
                frame=base,
                state_source=_PROXY_FALLBACK_SOURCE,
                state_source_note=_PROXY_FALLBACK_NOTE,
                diagnostics=diagnostics,
            )

        for column in classified.columns:
            base.loc[classified.index, column] = classified[column]
        eval_mode = base["hmm_state_eval_mode"].astype(str)
        diagnostics.update(fit_diag)
        diagnostics["status"] = "ok"
        diagnostics["ready"] = True
        diagnostics["hmm_in_sample_rows"] = int((eval_mode == _EVAL_MODE_IN_SAMPLE_FIT).sum())
        diagnostics["hmm_oos_filtered_rows"] = int((eval_mode == _EVAL_MODE_OOS_FILTERED).sum())
        diagnostics["hmm_proxy_fallback_rows"] = int((eval_mode == _EVAL_MODE_PROXY_FALLBACK).sum())
        return HMMStateModelResult(
            frame=base,
            state_source=_HMM_SOURCE,
            state_source_note=_HMM_SOURCE_NOTE,
            diagnostics=diagnostics,
        )

    def _build_feature_matrix(
        self,
        feature_frame: pd.DataFrame,
    ) -> tuple[np.ndarray, pd.DataFrame, tuple[str, ...]] | None:
        usable = feature_frame.get("row_quality_usable")
        if usable is None:
            usable_mask = pd.Series(True, index=feature_frame.index, dtype=bool)
        else:
            usable_mask = usable.fillna(False).astype(bool)

        transformed: dict[str, pd.Series] = {}
        active: list[str] = []
        for column in self.config.feature_columns:
            series = _transform_feature(feature_frame, column)
            if series is None:
                continue
            valid_values = series[usable_mask & series.notna()]
            if valid_values.empty:
                continue
            if float(valid_values.std(ddof=0)) <= 1e-8:
                continue
            transformed[column] = series
            active.append(column)

        if len(active) < self.config.min_active_features:
            return None

        matrix_frame = pd.DataFrame(transformed, index=feature_frame.index)
        valid_mask = usable_mask & matrix_frame.notna().all(axis=1)
        if not bool(valid_mask.any()):
            return None
        usable_frame = matrix_frame.loc[valid_mask, active].copy()
        if len(usable_frame) < self.config.min_train_bars:
            return None
        return usable_frame.to_numpy(dtype=float), usable_frame, tuple(active)

    def _classify_series(
        self,
        usable_frame: pd.DataFrame,
        matrix: np.ndarray,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        max_states = self._max_state_slots()
        out = pd.DataFrame(index=usable_frame.index)
        for state_idx in range(max_states):
            out[f"hmm_p_state_{state_idx}"] = np.nan
        out["hmm_n_states"] = np.nan
        out["hmm_transition_prob"] = np.nan
        out["hmm_crisis_prob"] = np.nan
        out["transition_matrix_self_prob"] = np.nan
        out["latent_state_entropy"] = np.nan
        out["posterior_shift"] = np.nan
        out["hmm_state_eval_mode"] = pd.Series(index=usable_frame.index, dtype=object)
        for column in _STATE_COLUMNS:
            out[column] = np.nan
        out["state_entropy"] = np.nan
        out["dominant_state"] = pd.Series(index=usable_frame.index, dtype=object)
        out["dominant_state_prob"] = np.nan

        current_model: GaussianHMM | None = None
        current_mapping: SemanticMappingResult | None = None
        current_n_states = 2
        window = max(int(self.config.retrain_window), int(self.config.min_train_bars))
        classified_rows = 0
        mapping_history: list[dict[str, Any]] = []

        for seg_start in range(0, len(matrix), window):
            seg_end = min(seg_start + window, len(matrix))
            segment = matrix[seg_start:seg_end]
            segment_frame = usable_frame.iloc[seg_start:seg_end]
            if len(segment) < self.config.min_train_bars:
                if current_model is not None and current_mapping is not None:
                    classified_rows += self._write_segment_output(
                        out,
                        segment_frame=segment_frame,
                        segment=segment,
                        model=current_model,
                        mapping=current_mapping,
                        n_states=current_n_states,
                        eval_mode=_EVAL_MODE_OOS_FILTERED,
                    )
                continue

            if seg_start == 0:
                fitted = self._fit_and_map(segment_frame, segment)
                if fitted is None:
                    continue
                current_model, current_mapping, current_n_states, mapping_meta = fitted
                mapping_history.append(mapping_meta)
                classified_rows += self._write_segment_output(
                    out,
                    segment_frame=segment_frame,
                    segment=segment,
                    model=current_model,
                    mapping=current_mapping,
                    n_states=current_n_states,
                    eval_mode=_EVAL_MODE_IN_SAMPLE_FIT,
                )
                continue

            if current_model is not None and current_mapping is not None:
                classified_rows += self._write_segment_output(
                    out,
                    segment_frame=segment_frame,
                    segment=segment,
                    model=current_model,
                    mapping=current_mapping,
                    n_states=current_n_states,
                    eval_mode=_EVAL_MODE_OOS_FILTERED,
                )

            fitted = self._fit_and_map(segment_frame, segment)
            if fitted is None:
                continue
            current_model, current_mapping, current_n_states, mapping_meta = fitted
            mapping_history.append(mapping_meta)

        diagnostics = {
            "classified_rows": int(classified_rows),
            "fit_diagnostics": self.diagnostics(),
            "mapping_history": mapping_history,
            "posterior_filter": "causal_forward",
            "emission_model": "student_t" if self.config.hmm_robust_scoring else "gaussian",
            "hmm_in_sample_rows": int((out["hmm_state_eval_mode"] == _EVAL_MODE_IN_SAMPLE_FIT).sum()),
            "hmm_oos_filtered_rows": int((out["hmm_state_eval_mode"] == _EVAL_MODE_OOS_FILTERED).sum()),
            "hmm_proxy_fallback_rows": 0,
        }
        return out.loc[out.loc[:, list(_STATE_COLUMNS)].notna().any(axis=1)].copy(), diagnostics

    def _fit_and_map(
        self,
        feature_frame: pd.DataFrame,
        matrix: np.ndarray,
    ) -> tuple[GaussianHMM, SemanticMappingResult, int, dict[str, Any]] | None:
        try:
            n_states = self._resolve_n_states(matrix)
            model = self._fit_gaussian_hmm(matrix, n_states=n_states)
            posteriors = self._get_proba(matrix, model)
            self_prob = pd.Series(
                transition_matrix_self_probability(posteriors, getattr(model, "transmat_", None)),
                index=feature_frame.index,
                dtype=float,
            )
            mapping = map_latent_states(
                feature_frame,
                posteriors[:, : model.n_components],
                self_transition_prob=self_prob,
            )
        except Exception as exc:
            logger.warning("RegimeProbV1 HMM fit failed: %s", exc)
            return None
        mapping_meta = {
            "index_start": str(feature_frame.index[0]),
            "index_end": str(feature_frame.index[-1]),
            "n_states": int(model.n_components),
            "state_to_label": dict(mapping.state_to_label),
        }
        return model, mapping, int(model.n_components), mapping_meta

    def _write_segment_output(
        self,
        out: pd.DataFrame,
        *,
        segment_frame: pd.DataFrame,
        segment: np.ndarray,
        model: GaussianHMM,
        mapping: SemanticMappingResult,
        n_states: int,
        eval_mode: str,
    ) -> int:
        if len(segment_frame) == 0:
            return 0
        posteriors = self._get_proba(segment, model)[:, :n_states]
        self_prob = pd.Series(
            transition_matrix_self_probability(posteriors, getattr(model, "transmat_", None)),
            index=segment_frame.index,
            dtype=float,
        )
        semantic = _semantic_probability_frame(
            segment_frame,
            posteriors=posteriors,
            mapping=mapping,
            self_transition_prob=self_prob,
        )
        for state_idx in range(n_states):
            out.loc[segment_frame.index, f"hmm_p_state_{state_idx}"] = posteriors[:, state_idx]
        out.loc[segment_frame.index, "hmm_n_states"] = float(n_states)
        out.loc[segment_frame.index, "hmm_transition_prob"] = self_prob
        out.loc[segment_frame.index, "hmm_crisis_prob"] = semantic["p_vol_shock_state"]
        out.loc[segment_frame.index, "hmm_state_eval_mode"] = eval_mode
        for column in semantic.columns:
            out.loc[segment_frame.index, column] = semantic[column]
        return int(len(segment_frame))

    def _get_proba(self, matrix: np.ndarray, model: GaussianHMM) -> np.ndarray:
        emission_log_likelihood = self._emission_log_likelihood(matrix, model)
        return self._forward_filter_probabilities(
            emission_log_likelihood,
            startprob=np.asarray(model.startprob_, dtype=float),
            transmat=np.asarray(model.transmat_, dtype=float),
        )

    def _emission_log_likelihood(self, matrix: np.ndarray, model: GaussianHMM) -> np.ndarray:
        if self.config.hmm_robust_scoring:
            return self._student_t_emission_log_likelihood(matrix, model)
        return self._gaussian_emission_log_likelihood(matrix, model)

    @staticmethod
    def _gaussian_emission_log_likelihood(matrix: np.ndarray, model: GaussianHMM) -> np.ndarray:
        # hmmlearn exposes Gaussian emission scoring through a private helper.
        # Keep the usage isolated so library drift is easy to detect in tests.
        return np.asarray(model._compute_log_likelihood(matrix), dtype=float)

    def _student_t_emission_log_likelihood(self, matrix: np.ndarray, model: GaussianHMM) -> np.ndarray:
        n_states = int(model.n_components)
        log_prob = np.zeros((len(matrix), n_states), dtype=float)
        for state_idx in range(n_states):
            mean = np.asarray(model.means_[state_idx], dtype=float)
            covars = np.asarray(model.covars_[state_idx], dtype=float)
            if covars.ndim == 2:
                scale = np.sqrt(np.diag(covars))
            else:
                scale = np.sqrt(covars)
            scale = np.maximum(scale, _EPS)
            for dim in range(matrix.shape[1]):
                log_prob[:, state_idx] += student_t.logpdf(
                    matrix[:, dim],
                    df=float(self.config.hmm_student_df),
                    loc=float(mean[dim]),
                    scale=float(scale[dim]),
                )
        return log_prob

    @staticmethod
    def _forward_filter_probabilities(
        emission_log_likelihood: np.ndarray,
        *,
        startprob: np.ndarray,
        transmat: np.ndarray,
    ) -> np.ndarray:
        if emission_log_likelihood.size == 0:
            return np.empty((0, len(startprob)), dtype=float)

        n_obs, n_states = emission_log_likelihood.shape
        log_start = np.log(np.clip(np.asarray(startprob, dtype=float), _EPS, 1.0))
        log_trans = np.log(np.clip(np.asarray(transmat, dtype=float), _EPS, 1.0))
        log_alpha = np.full((n_obs, n_states), -np.inf, dtype=float)

        log_alpha[0] = log_start + emission_log_likelihood[0]
        log_alpha[0] -= logsumexp(log_alpha[0])

        for obs_idx in range(1, n_obs):
            predicted = logsumexp(log_alpha[obs_idx - 1][:, None] + log_trans, axis=0)
            log_alpha[obs_idx] = emission_log_likelihood[obs_idx] + predicted
            log_alpha[obs_idx] -= logsumexp(log_alpha[obs_idx])

        probabilities = np.exp(log_alpha)
        probabilities /= probabilities.sum(axis=1, keepdims=True) + _EPS
        return probabilities

    def _resolve_n_states(self, matrix: np.ndarray) -> int:
        if int(self.config.hmm_n_states) >= 2:
            return int(self.config.hmm_n_states)
        return self._select_n_states(matrix)

    def _select_n_states(self, matrix: np.ndarray) -> int:
        best_n = 2
        best_bic = np.inf
        for n_states in range(2, self._max_state_slots() + 1):
            try:
                model = self._fit_gaussian_hmm(matrix, n_states=n_states, bic_mode=True)
                dims = matrix.shape[1]
                if self.config.hmm_covariance_type == "diag":
                    covar_params = n_states * dims
                else:
                    covar_params = n_states * dims * (dims + 1) // 2
                params = n_states * (n_states - 1) + n_states * dims + covar_params
                bic = -2.0 * float(model.score(matrix)) + params * np.log(max(len(matrix), 2))
                if bic < best_bic:
                    best_bic = bic
                    best_n = n_states
                else:
                    break
            except Exception:
                continue
        return best_n

    def _fit_gaussian_hmm(
        self,
        matrix: np.ndarray,
        *,
        n_states: int,
        bic_mode: bool = False,
    ) -> GaussianHMM:
        model = GaussianHMM(
            n_components=int(n_states),
            covariance_type=self.config.hmm_covariance_type,
            n_iter=int(self.config.fit_iterations),
            tol=1e-3,
            random_state=42,
        )
        self._diag["fit_attempts"] += 1
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="invalid value encountered in divide",
                    category=RuntimeWarning,
                )
                model.fit(matrix)
            self._validate_fitted_model(model)
        except Exception:
            self._diag["fit_failures"] += 1
            raise
        self._diag["fit_successes"] += 1
        if self._is_unstable_fit(model):
            self._diag["unstable_fits"] += 1
            if not bic_mode:
                logger.debug("RegimeProbV1 HMM fit marked unstable for n_states=%s", n_states)
        return model

    @staticmethod
    def _validate_fitted_model(model: GaussianHMM) -> None:
        params = (model.startprob_, model.transmat_, model.means_, model.covars_)
        if not all(np.isfinite(np.asarray(param)).all() for param in params):
            raise ValueError("GaussianHMM fit produced non-finite parameters")
        startprob = np.asarray(model.startprob_, dtype=float)
        transmat = np.asarray(model.transmat_, dtype=float)
        if startprob.ndim != 1 or len(startprob) != int(model.n_components):
            raise ValueError("GaussianHMM fit produced invalid start probabilities")
        if transmat.shape != (int(model.n_components), int(model.n_components)):
            raise ValueError("GaussianHMM fit produced invalid transition matrix shape")
        if (startprob < 0.0).any() or not np.isclose(startprob.sum(), 1.0, atol=1e-5):
            raise ValueError("GaussianHMM fit produced invalid start-probability mass")
        if (transmat < 0.0).any() or not np.allclose(transmat.sum(axis=1), 1.0, atol=1e-5):
            raise ValueError("GaussianHMM fit produced invalid transition rows")

    @staticmethod
    def _is_unstable_fit(model: GaussianHMM) -> bool:
        monitor = getattr(model, "monitor_", None)
        if monitor is None:
            return False
        converged = bool(getattr(monitor, "converged", True))
        history = list(getattr(monitor, "history", []))
        decreasing = len(history) >= 2 and history[-1] < history[-2] - 1e-8
        return (not converged) or decreasing

    def _max_state_slots(self) -> int:
        return int(max(2, self.config.hmm_n_states if self.config.hmm_n_states > 0 else self.config.hmm_max_states))

    def diagnostics(self) -> dict[str, float | int]:
        attempts = max(int(self._diag["fit_attempts"]), 1)
        successes = max(int(self._diag["fit_successes"]), 1)
        return {
            **self._diag,
            "fit_failure_rate": float(self._diag["fit_failures"] / attempts),
            "unstable_fit_rate": float(self._diag["unstable_fits"] / successes),
        }

    @staticmethod
    def _empty_diagnostics() -> dict[str, int]:
        return {
            "fit_attempts": 0,
            "fit_successes": 0,
            "fit_failures": 0,
            "unstable_fits": 0,
        }


def _semantic_probability_frame(
    segment_frame: pd.DataFrame,
    *,
    posteriors: np.ndarray,
    mapping: SemanticMappingResult,
    self_transition_prob: pd.Series,
) -> pd.DataFrame:
    semantic = pd.DataFrame(0.0, index=segment_frame.index, columns=_STATE_COLUMNS)
    for state_idx in range(posteriors.shape[1]):
        label = mapping.state_to_label.get(state_idx, "transition")
        semantic[f"p_{label}_state"] += posteriors[:, state_idx]
    shift = posterior_shift_series(posteriors, segment_frame.index)
    transition = combine_transition_probability(
        segment_frame,
        base_transition=semantic["p_transition_state"],
        self_transition_prob=self_transition_prob,
        posterior_shift=shift,
    )
    remainder_cols = [column for column in _STATE_COLUMNS if column != "p_transition_state"]
    other = semantic.loc[:, remainder_cols].sum(axis=1)
    residual = (1.0 - transition).clip(lower=0.0)
    scaled = semantic.loc[:, remainder_cols].div(other.replace(0.0, np.nan), axis=0).mul(residual, axis=0)
    scaled = scaled.where(other.gt(0.0), 0.0).fillna(0.0)
    semantic.loc[:, remainder_cols] = scaled
    semantic["p_transition_state"] = transition
    semantic["state_entropy"] = state_entropy(semantic.loc[:, list(_STATE_COLUMNS)])
    semantic["dominant_state"] = (
        semantic.loc[:, list(_STATE_COLUMNS)].idxmax(axis=1).str.removeprefix("p_").str.removesuffix("_state")
    )
    semantic["dominant_state_prob"] = semantic.loc[:, list(_STATE_COLUMNS)].max(axis=1)
    semantic["transition_matrix_self_prob"] = self_transition_prob
    semantic["hmm_transition_prob"] = self_transition_prob
    semantic["latent_state_entropy"] = _latent_entropy(posteriors, index=segment_frame.index)
    semantic["posterior_shift"] = shift
    return semantic


def _default_output_frame(feature_frame: pd.DataFrame, *, max_states: int) -> pd.DataFrame:
    proxy = build_state_proxy_frame(feature_frame)
    for state_idx in range(max_states):
        proxy[f"hmm_p_state_{state_idx}"] = 0.0 if state_idx >= 2 else 0.5
    proxy["hmm_n_states"] = 2.0
    proxy["hmm_transition_prob"] = 0.5
    proxy["hmm_crisis_prob"] = proxy["p_vol_shock_state"]
    proxy["transition_matrix_self_prob"] = 0.5
    proxy["latent_state_entropy"] = 1.0
    proxy["posterior_shift"] = 0.0
    proxy["hmm_state_eval_mode"] = _EVAL_MODE_PROXY_FALLBACK
    return proxy


def _latent_entropy(posteriors: np.ndarray, *, index: pd.Index) -> pd.Series:
    if len(posteriors) == 0:
        return pd.Series(dtype=float, index=index)
    probs = np.clip(np.asarray(posteriors, dtype=float), 0.0, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_probs = np.where(probs > 0.0, np.log(probs), 0.0)
    entropy = -(probs * log_probs).sum(axis=1)
    max_entropy = np.log(max(probs.shape[1], 2))
    normalized = np.clip(entropy / max(max_entropy, _EPS), 0.0, 1.0)
    return pd.Series(normalized, index=index, dtype=float)


def _transform_feature(feature_frame: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in feature_frame.columns:
        return None
    series = pd.to_numeric(feature_frame[column], errors="coerce")
    if column == "volatility_percentile":
        return series.clip(0.0, 100.0) / 100.0
    if column == "hurst":
        return series.clip(0.0, 1.0)
    return series.clip(0.0, 1.0)


__all__ = [
    "HMMStateModel",
    "HMMStateModelConfig",
    "HMMStateModelResult",
]
