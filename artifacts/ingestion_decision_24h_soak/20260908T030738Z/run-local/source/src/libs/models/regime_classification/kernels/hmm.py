"""
HMM Classifier — N-state Gaussian HMM for regime posterior estimation.

Adapted from libs/regime/hmm_classifier.py — zero imports from old module.

Key changes from old module:
- Uses HMMStateLocal from local contracts (no libs.regime dependency)
- Uses local hurst kernel (no libs.regime.kernels dependency)
- Removed force_retrain() BCPD coupling — standalone retraining
- Emits full posteriors array, not just collapsed p_trending
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from scipy.stats import t as student_t

from libs.models.regime_classification.contracts import HMMStateLocal

logger = logging.getLogger(__name__)

_TRENDING = "TRENDING"
_NON_TRENDING = "NON_TRENDING"
_CRISIS = "CRISIS"
_MEAN_REVERTING = "MEAN_REVERTING"
_EPS = 1e-10


@dataclass(frozen=True)
class HMMClassifierConfig:
    retrain_window: int = 500
    min_train_bars: int = 200
    log_vol_lookback: int = 24
    hurst_lookback: int = 100
    use_hurst: bool = True
    use_volume: bool = True
    hmm_n_states: int = 0
    hmm_max_states: int = 4
    hmm_covariance_type: str = "full"
    hmm_robust_scoring: bool = True
    hmm_student_df: float = 5.0
    hmm_crisis_vol_mult: float = 2.0


class HMMClassifier:
    """
    N-state GaussianHMM with adaptive retraining.

    Emits full posterior probabilities per state — does NOT collapse
    to a single p_trending scalar. Downstream consumers decide how
    to use the posteriors.
    """

    def __init__(self, config: Optional[HMMClassifierConfig] = None):
        self.config = config or HMMClassifierConfig()
        self._model: Optional[GaussianHMM] = None
        self._model_age: int = 0
        self._n_states: int = 2
        self._state_labels: dict[int, str] = {}
        self._crisis_indices: list[int] = []
        self._trending_indices: list[int] = []
        self._diag = self._empty_diagnostics()

    def classify(self, df: pd.DataFrame) -> HMMStateLocal:
        """Classify regime at the last bar of df, returning full posteriors."""
        X = self._build_features(df)
        if X is None or len(X) < self.config.min_train_bars:
            return self._default_state()

        self._maybe_retrain(X)
        if self._model is None:
            return self._default_state()

        if self.config.hmm_robust_scoring and self._n_states >= 2:
            proba = self._robust_state_probs(X, self._model)
        else:
            proba = self._model.predict_proba(X)

        last_proba = proba[-1]
        posteriors = tuple(float(last_proba[i]) for i in range(self._n_states))
        crisis_prob = sum(float(last_proba[idx]) for idx in self._crisis_indices)

        transition_prob = 0.5
        if hasattr(self._model, "transmat_"):
            current_state = int(np.argmax(last_proba))
            transition_prob = float(
                self._model.transmat_[current_state, current_state]
            )

        return HMMStateLocal(
            posteriors=posteriors,
            n_states=self._n_states,
            transition_prob=transition_prob,
            crisis_prob=crisis_prob,
        )

    def classify_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify every bar, emitting full posteriors per state.

        Returns columns: hmm_p_state_0, hmm_p_state_1, ..., hmm_n_states,
                         hmm_crisis_prob, hmm_transition_prob.
        """
        X = self._build_features(df)
        if X is None or len(X) < self.config.min_train_bars:
            result = df.copy()
            result["hmm_p_state_0"] = 0.5
            result["hmm_p_state_1"] = 0.5
            result["hmm_n_states"] = 2
            result["hmm_crisis_prob"] = 0.0
            result["hmm_transition_prob"] = 0.5
            return result

        n = len(X)
        window = self.config.retrain_window
        max_states = self.config.hmm_max_states

        # Pre-allocate for max possible states
        all_proba = np.full((n, max_states), 0.0)
        all_proba[:, 0] = 0.5
        all_proba[:, 1] = 0.5
        all_n_states = np.full(n, 2, dtype=int)
        all_crisis = np.zeros(n)
        all_transition = np.full(n, 0.5)  # P(stay in current state)

        current_model = None
        current_trending_indices: list[int] = []
        current_crisis_indices: list[int] = []
        current_n_states = 2
        current_robust = self.config.hmm_robust_scoring

        segments = []
        for seg_start in range(0, n, window):
            seg_end = min(seg_start + window, n)
            segments.append((seg_start, seg_end))

        for seg_idx, (seg_start, seg_end) in enumerate(segments):
            segment = X[seg_start:seg_end]

            if len(segment) < self.config.min_train_bars:
                if current_model is not None:
                    try:
                        proba = self._get_proba(
                            segment, current_model, current_robust
                        )
                        ns = min(proba.shape[1], max_states)
                        all_proba[seg_start:seg_end, :ns] = proba[:, :ns]
                        all_n_states[seg_start:seg_end] = current_n_states
                        all_crisis[seg_start:seg_end] = (
                            proba[:, current_crisis_indices].sum(axis=1)
                            if current_crisis_indices
                            else 0.0
                        )
                        self._fill_transition_probs(
                            proba, current_model, all_transition, seg_start
                        )
                    except Exception:
                        pass
                continue

            if seg_idx == 0:
                # Warm-up: train + classify in-sample
                try:
                    model, labels = self._fit_and_label(segment)
                    proba = self._get_proba(segment, model, current_robust)
                    ns = min(proba.shape[1], max_states)
                    all_proba[seg_start:seg_end, :ns] = proba[:, :ns]

                    current_model = model
                    current_n_states = model.n_components
                    all_n_states[seg_start:seg_end] = current_n_states
                    current_crisis_indices = [
                        i for i, l in labels.items() if l == _CRISIS
                    ]
                    all_crisis[seg_start:seg_end] = (
                        proba[:, current_crisis_indices].sum(axis=1)
                        if current_crisis_indices
                        else 0.0
                    )
                    self._fill_transition_probs(
                        proba, model, all_transition, seg_start
                    )
                except Exception as exc:
                    logger.warning("HMM warm-up failed: %s", exc)
            else:
                # Out-of-sample: classify with prior segment's model
                if current_model is not None:
                    try:
                        proba = self._get_proba(
                            segment, current_model, current_robust
                        )
                        ns = min(proba.shape[1], max_states)
                        all_proba[seg_start:seg_end, :ns] = proba[:, :ns]
                        all_n_states[seg_start:seg_end] = current_n_states
                        all_crisis[seg_start:seg_end] = (
                            proba[:, current_crisis_indices].sum(axis=1)
                            if current_crisis_indices
                            else 0.0
                        )
                        self._fill_transition_probs(
                            proba, current_model, all_transition, seg_start
                        )
                    except Exception as exc:
                        logger.warning("HMM OOS classify failed: %s", exc)

                # Retrain for next segment
                try:
                    model, labels = self._fit_and_label(segment)
                    current_model = model
                    current_n_states = model.n_components
                    current_crisis_indices = [
                        i for i, l in labels.items() if l == _CRISIS
                    ]
                except Exception as exc:
                    logger.warning("HMM retrain failed: %s", exc)

        # Build output DataFrame
        result = df.copy()
        feature_offset = len(df) - n

        for s in range(max_states):
            col = f"hmm_p_state_{s}"
            pad = np.full(feature_offset, 0.0 if s >= 2 else 0.5)
            result[col] = np.concatenate([pad, all_proba[:, s]])

        pad_ns = np.full(feature_offset, 2)
        result["hmm_n_states"] = np.concatenate([pad_ns, all_n_states])
        pad_crisis = np.full(feature_offset, 0.0)
        result["hmm_crisis_prob"] = np.concatenate([pad_crisis, all_crisis])
        pad_trans = np.full(feature_offset, 0.5)
        result["hmm_transition_prob"] = np.concatenate([pad_trans, all_transition])

        return result

    def reset(self):
        """Reset model state."""
        self._model = None
        self._model_age = 0
        self._diag = self._empty_diagnostics()

    def diagnostics(self) -> dict:
        fit_attempts = max(int(self._diag["fit_attempts"]), 1)
        fit_successes = max(int(self._diag["fit_successes"]), 1)
        return {
            **self._diag,
            "fit_failure_rate": float(self._diag["fit_failures"] / fit_attempts),
            "unstable_fit_rate": float(
                self._diag["unstable_fits"] / fit_successes
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fill_transition_probs(
        proba: np.ndarray,
        model: GaussianHMM,
        out: np.ndarray,
        offset: int,
    ) -> None:
        """Write per-bar P(stay in current state) into *out* starting at *offset*."""
        if not hasattr(model, "transmat_"):
            return
        for i in range(len(proba)):
            state = int(np.argmax(proba[i]))
            out[offset + i] = float(model.transmat_[state, state])

    def _get_proba(
        self, X: np.ndarray, model: GaussianHMM, use_robust: bool
    ) -> np.ndarray:
        if use_robust:
            return self._robust_state_probs(X, model)
        return model.predict_proba(X)

    def _fit_and_label(
        self, X: np.ndarray
    ) -> tuple[GaussianHMM, dict[int, str]]:
        """Fit HMM and label states. Returns (model, labels)."""
        n_states = self._resolve_n_states(X)
        cov_type = self._resolve_covariance_type(n_states)
        model = self._fit_gaussian_hmm(X, n_states, cov_type)
        labels = self._label_states_nstate(X, model)
        return model, labels

    def _maybe_retrain(self, X: np.ndarray) -> None:
        need_retrain = (
            self._model is None
            or self._model_age >= self.config.retrain_window
        )
        if need_retrain:
            self._fit(X)
        self._model_age += 1

    def _fit(self, X: np.ndarray) -> None:
        window = X[-self.config.retrain_window :]
        try:
            model, labels = self._fit_and_label(window)
            self._model = model
            self._model_age = 0
            self._n_states = model.n_components
            self._state_labels = labels
            self._trending_indices = [
                i for i, l in labels.items() if l == _TRENDING
            ]
            self._crisis_indices = [
                i for i, l in labels.items() if l == _CRISIS
            ]
        except Exception as exc:
            logger.warning("HMMClassifier fit failed: %s", exc)
            self._model = None

    def _resolve_n_states(self, X: np.ndarray) -> int:
        if self.config.hmm_n_states >= 2:
            return self.config.hmm_n_states
        return self._select_n_states(X)

    def _resolve_covariance_type(self, n_states: int) -> str:
        if n_states == 2 and self.config.hmm_n_states == 0:
            return self.config.hmm_covariance_type
        if self.config.hmm_n_states == 2:
            return "diag"
        return self.config.hmm_covariance_type

    def _select_n_states(self, X: np.ndarray) -> int:
        best_n, best_bic = 2, np.inf
        for n in range(2, self.config.hmm_max_states + 1):
            try:
                model = self._fit_gaussian_hmm(
                    X, n, self.config.hmm_covariance_type, tol=None
                )
                d = X.shape[1]
                if self.config.hmm_covariance_type == "diag":
                    n_cov_params = n * d
                else:
                    n_cov_params = n * d * (d + 1) // 2
                k = n * (n - 1) + n * d + n_cov_params
                # hmmlearn score() returns total log-likelihood, not per-sample
                log_likelihood = model.score(X)
                bic = -2 * log_likelihood + k * np.log(len(X))
                if bic < best_bic:
                    best_bic = bic
                    best_n = n
                else:
                    break
            except Exception:
                continue
        return best_n

    def _fit_gaussian_hmm(
        self,
        X: np.ndarray,
        n_components: int,
        covariance_type: str,
        *,
        tol: Optional[float] = 1e-3,
    ) -> GaussianHMM:
        model_kwargs = {
            "n_components": n_components,
            "covariance_type": covariance_type,
            "n_iter": 100,
            "random_state": 42,
        }
        if tol is not None:
            model_kwargs["tol"] = tol

        model = GaussianHMM(**model_kwargs)
        self._diag["fit_attempts"] += 1
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="invalid value encountered in divide",
                    category=RuntimeWarning,
                )
                model.fit(X)
            self._validate_fitted_model(model)
        except Exception:
            self._diag["fit_failures"] += 1
            raise

        self._diag["fit_successes"] += 1
        if self._is_unstable_fit(model):
            self._diag["unstable_fits"] += 1
        return model

    @staticmethod
    def _validate_fitted_model(model: GaussianHMM) -> None:
        params = [model.startprob_, model.transmat_, model.means_, model.covars_]
        if not all(np.isfinite(param).all() for param in params):
            raise ValueError("GaussianHMM fit produced non-finite parameters")

    def _label_states_nstate(
        self, X: np.ndarray, model: GaussianHMM
    ) -> dict[int, str]:
        n_states = model.n_components
        state_seq = model.predict(X)
        returns = X[:, 0]

        if n_states == 2:
            trending_idx = self._label_states_binary(X, model)
            return {trending_idx: _TRENDING, 1 - trending_idx: _MEAN_REVERTING}

        state_stats = {}
        for s in range(n_states):
            mask = state_seq == s
            count = mask.sum()
            if count < 2:
                state_stats[s] = {
                    "mean_return": 0.0,
                    "vol": 0.0,
                    "de": 0.0,
                    "autocorr": 0.0,
                }
                continue

            s_returns = returns[mask]
            mean_ret = float(s_returns.mean())
            vol = float(s_returns.std())

            des = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 5:
                        run_ret = returns[i:j]
                        net = abs(run_ret.sum())
                        gross = np.abs(run_ret).sum() + _EPS
                        des.append(net / gross)
                    i = j
                else:
                    i += 1
            de = float(np.mean(des)) if des else 0.0

            acs = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 10:
                        run_ret = returns[i:j]
                        if len(run_ret) >= 2:
                            ac = float(
                                np.corrcoef(run_ret[:-1], run_ret[1:])[0, 1]
                            )
                            if np.isfinite(ac):
                                acs.append(ac)
                    i = j
                else:
                    i += 1
            autocorr = float(np.mean(acs)) if acs else 0.0

            state_stats[s] = {
                "mean_return": mean_ret,
                "vol": vol,
                "de": de,
                "autocorr": autocorr,
            }

        vols = [state_stats[s]["vol"] for s in range(n_states)]
        median_vol = float(np.median(vols))
        labels: dict[int, str] = {}

        crisis_candidates = [
            s
            for s in range(n_states)
            if state_stats[s]["vol"]
            > self.config.hmm_crisis_vol_mult * median_vol
            and state_stats[s]["mean_return"] < 0
        ]
        if crisis_candidates:
            crisis_state = max(
                crisis_candidates, key=lambda s: state_stats[s]["vol"]
            )
            labels[crisis_state] = _CRISIS

        remaining = [s for s in range(n_states) if s not in labels]
        if remaining:
            scores = {}
            for s in remaining:
                st = state_stats[s]
                scores[s] = (
                    abs(st["mean_return"])
                    * (1.0 + st["de"])
                    * (1.0 + max(st["autocorr"], 0.0))
                )
            trending_state = max(remaining, key=lambda s: scores[s])
            labels[trending_state] = _TRENDING
            for s in remaining:
                if s not in labels:
                    labels[s] = _MEAN_REVERTING

        return labels

    def _label_states_binary(
        self, X: np.ndarray, model: GaussianHMM
    ) -> int:
        """Identify trending state index for 2-state models."""
        state_seq = model.predict(X)
        returns = X[:, 0]
        votes = [0, 0]

        mean_abs = [
            abs(returns[state_seq == s].mean())
            if (state_seq == s).sum() > 0
            else 0.0
            for s in range(2)
        ]
        votes[int(np.argmax(mean_abs))] += 2

        run_de = []
        for s in range(2):
            des = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 5:
                        run_ret = returns[i:j]
                        net = abs(run_ret.sum())
                        gross = np.abs(run_ret).sum() + _EPS
                        des.append(net / gross)
                    i = j
                else:
                    i += 1
            run_de.append(np.mean(des) if des else 0.0)
        votes[int(np.argmax(run_de))] += 1

        autocorrs = []
        for s in range(2):
            acs = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 10:
                        run_ret = returns[i:j]
                        if len(run_ret) >= 2:
                            ac = float(
                                np.corrcoef(run_ret[:-1], run_ret[1:])[0, 1]
                            )
                            if np.isfinite(ac):
                                acs.append(ac)
                    i = j
                else:
                    i += 1
            autocorrs.append(np.mean(acs) if acs else 0.0)
        votes[int(np.argmax(autocorrs))] += 1

        return int(np.argmax(votes))

    def _robust_state_probs(
        self, X: np.ndarray, model: GaussianHMM
    ) -> np.ndarray:
        """Compute state posteriors using Student-t emission."""
        n_states = model.n_components
        n_obs = len(X)
        log_prob = np.zeros((n_obs, n_states))

        for k in range(n_states):
            mean = model.means_[k]
            covars = np.asarray(model.covars_[k], dtype=float)
            if covars.ndim == 2:
                scale = np.sqrt(np.diag(covars))
            else:
                scale = np.sqrt(covars)
            scale = np.maximum(scale, _EPS)

            for d in range(X.shape[1]):
                log_prob[:, k] += student_t.logpdf(
                    X[:, d],
                    df=self.config.hmm_student_df,
                    loc=mean[d],
                    scale=float(scale[d]),
                )

        if hasattr(model, "startprob_"):
            log_prob[0] += np.log(model.startprob_ + _EPS)

        log_prob -= np.max(log_prob, axis=1, keepdims=True)
        prob = np.exp(log_prob)
        prob /= prob.sum(axis=1, keepdims=True) + _EPS
        return prob

    def _build_features(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """Construct feature matrix [log_return, log_vol, (hurst), (volume)]."""
        if "close" not in df.columns or len(df) < self.config.log_vol_lookback + 2:
            return None

        close = df["close"].values
        log_ret = np.diff(np.log(close + _EPS))

        log_vol = (
            pd.Series(log_ret)
            .rolling(self.config.log_vol_lookback)
            .std()
            .apply(lambda x: np.log(x + _EPS))
            .ffill()
            .fillna(0.0)
            .values
        )

        features = [log_ret, log_vol]

        if self.config.use_hurst:
            from libs.models.regime_classification.kernels.hurst import (
                rolling_hurst,
            )

            hurst = rolling_hurst(
                close,
                lookback=self.config.hurst_lookback,
                min_periods=min(50, self.config.hurst_lookback // 2),
            )
            features.append(hurst[1:])

        if self.config.use_volume and "volume" in df.columns:
            volume = df["volume"].values
            log_vol_change = (
                pd.Series(np.log(volume + _EPS))
                .diff(self.config.log_vol_lookback)
                .ffill()
                .fillna(0.0)
                .values
            )
            features.append(log_vol_change[1:])

        X = np.column_stack(features).astype(np.float64)
        valid = np.isfinite(X).all(axis=1)
        return X[valid] if valid.any() else None

    def _default_state(self) -> HMMStateLocal:
        return HMMStateLocal(
            posteriors=(0.5, 0.5),
            n_states=2,
            transition_prob=0.5,
            crisis_prob=0.0,
        )

    @staticmethod
    def _empty_diagnostics() -> dict:
        return {
            "fit_attempts": 0,
            "fit_successes": 0,
            "fit_failures": 0,
            "unstable_fits": 0,
        }

    @staticmethod
    def _is_unstable_fit(model: GaussianHMM) -> bool:
        monitor = getattr(model, "monitor_", None)
        if monitor is None:
            return False
        converged = bool(getattr(monitor, "converged", True))
        history = list(getattr(monitor, "history", []))
        decreasing_ll = (
            len(history) >= 2 and history[-1] < history[-2] - 1e-8
        )
        return not converged or decreasing_ll
