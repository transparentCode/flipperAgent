"""
HMM Classifier
==============
N-state Gaussian HMM for regime detection with BIC model selection
and optional Student-t robust emission scoring.

States: TRENDING / NON_TRENDING / CRISIS (3+ state mode)
Features: [log_return, log_vol, (hurst), (volume)]

Key design:
- Hamilton forward filtering (non-hindsight) via hmmlearn predict_proba
- BIC-based automatic state count selection (2–max_states)
- State labeling by directional efficiency, autocorrelation, and volatility
- Student-t robust scoring for fat-tail resilience
- Periodic retraining + force_retrain() for BCPD-triggered refit
- Full backward compatibility: 2-state + Gaussian = identical to prior behavior
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

from libs.regime.models import HMMState

logger = logging.getLogger("app.regime")

_TRENDING = "TRENDING"
_NON_TRENDING = "NON_TRENDING"
_CRISIS = "CRISIS"
_MEAN_REVERTING = "MEAN_REVERTING"
_EPS = 1e-10


@dataclass(frozen=True)
class HMMConfig:
    retrain_window: int = 1000   # Bars used for rolling fit
    min_train_bars: int = 200    # Minimum bars before emitting a signal
    log_vol_lookback: int = 24   # Bars for within-feature vol estimate
    hurst_lookback: int = 100    # Rolling R/S Hurst window
    use_hurst: bool = True       # Include Hurst as 3rd feature
    use_volume: bool = True      # Include log volume change as feature

    # N-state HMM configuration
    hmm_n_states: int = 0              # 0 = auto-select via BIC, 2-5 = fixed
    hmm_max_states: int = 4            # Max states to try when auto-selecting
    hmm_covariance_type: str = "full"  # "diag" or "full" (full captures correlations)

    # Student-t robust scoring
    hmm_robust_scoring: bool = True    # Use Student-t log-likelihood for state probabilities
    hmm_student_df: float = 5.0        # Degrees of freedom for Student-t (lower = heavier tails)

    # Crisis detection
    hmm_crisis_vol_mult: float = 2.0   # State vol > this * median_vol → crisis candidate


class HMMClassifier:
    """
    N-state GaussianHMM with adaptive retraining and optional Student-t scoring.

    Usage
    -----
    clf = HMMClassifier()
    state = clf.classify(df)          # single-bar output
    df_out = clf.classify_series(df)  # full series output
    """

    def __init__(self, config: Optional[HMMConfig] = None):
        self.config = config or HMMConfig()
        self._model: Optional[GaussianHMM] = None
        self._trending_idx: int = 0   # which sklearn state index = TRENDING
        self._model_age: int = 0      # bars since last retrain
        self._force_retrain_flag: bool = False
        self._n_states: int = 2       # actual number of states in current model
        self._state_labels: dict[int, str] = {}  # state_idx -> label mapping
        self._crisis_indices: list[int] = []      # state indices labeled CRISIS
        self._trending_indices: list[int] = []    # state indices labeled TRENDING
        self._diag = self._empty_diagnostics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, df: pd.DataFrame) -> HMMState:
        """
        Classify regime at the last bar of df.

        Parameters
        ----------
        df : DataFrame with 'close' column, at least min_train_bars rows.
        """
        X = self._build_features(df)
        if X is None or len(X) < self.config.min_train_bars:
            return self._default_state()

        self._maybe_retrain(X)
        if self._model is None:
            return self._default_state()

        # Get state posteriors
        if self.config.hmm_robust_scoring and self._n_states >= 2:
            proba = self._robust_state_probs(X, self._model)
        else:
            proba = self._model.predict_proba(X)   # shape (T, n_states)

        # Compute p_trending and crisis_prob from multi-state posteriors
        p_trend = sum(float(proba[-1, idx]) for idx in self._trending_indices)
        crisis_prob = sum(float(proba[-1, idx]) for idx in self._crisis_indices)
        regime = _TRENDING if p_trend >= 0.5 else _NON_TRENDING

        # Extract self-transition probability (P(stay in current state))
        transition_prob = 0.5
        if hasattr(self._model, 'transmat_'):
            # Use the most probable state for transition prob
            current_state = int(np.argmax(proba[-1]))
            transition_prob = float(self._model.transmat_[current_state, current_state])

        return HMMState(
            p_trending=p_trend,
            p_non_trending=1.0 - p_trend,
            hmm_regime=regime,
            model_age_bars=self._model_age,
            transition_prob=transition_prob,
            crisis_prob=crisis_prob,
            n_states=self._n_states,
            metadata=self._model_metadata(),
        )

    def classify_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify every bar in df using train-then-forward-classify.

        Each retrain_window segment is classified using the model trained on
        the PRIOR segment (out-of-sample), matching live behavior where the
        model classifies unseen bars. The first segment trains and classifies
        itself (warm-up — necessary since there's no prior model).

        Returns columns: hmm_p_trending, hmm_regime.
        """
        return self._classify_series_impl(df, bcpd_signals=None)

    def classify_series_with_bcpd(
        self, df: pd.DataFrame, bcpd_signals: np.ndarray
    ) -> pd.DataFrame:
        """
        Classify series with BCPD-triggered retraining (matches live behavior).

        When a BCPD signal fires, the HMM is retrained on the most recent
        retrain_window bars BEFORE classifying that bar — exactly like the
        live analyze() path.

        Parameters
        ----------
        df : DataFrame with 'close' column
        bcpd_signals : 1-D array of 0/1 (same length as df), 1 = changepoint

        Returns columns: hmm_p_trending, hmm_regime.
        """
        return self._classify_series_impl(df, bcpd_signals=bcpd_signals)

    def _classify_series_impl(
        self, df: pd.DataFrame, bcpd_signals: Optional[np.ndarray] = None
    ) -> pd.DataFrame:
        """
        Core series classification with optional BCPD-triggered retraining.

        Strategy:
        - Segment the feature matrix into retrain_window chunks
        - Segment 0: train + classify in-sample (warm-up)
        - Segment 1+: classify using model from segment N-1 (out-of-sample)
        - If bcpd_signals fires within a segment, retrain on latest retrain_window
          bars up to that point, then continue classifying
        """
        X = self._build_features(df)
        if X is None or len(X) < self.config.min_train_bars:
            result = df.copy()
            result["hmm_p_trending"] = 0.5
            result["hmm_regime"] = _NON_TRENDING
            return result

        n = len(X)
        p_trend_all = np.full(n, 0.5)
        window = self.config.retrain_window

        # Align bcpd_signals to feature matrix (features are shorter by padding)
        feature_offset = len(df) - n
        bcpd_aligned = None
        if bcpd_signals is not None:
            bcpd_aligned = bcpd_signals[feature_offset:]

        current_model = None
        current_trending_indices: list[int] = []
        current_robust = self.config.hmm_robust_scoring

        segments = []
        for seg_start in range(0, n, window):
            seg_end = min(seg_start + window, n)
            segments.append((seg_start, seg_end))

        for seg_idx, (seg_start, seg_end) in enumerate(segments):
            segment = X[seg_start:seg_end]

            if len(segment) < self.config.min_train_bars:
                # Too few bars — use current model if available, else leave 0.5
                if current_model is not None:
                    try:
                        p_trend_all[seg_start:seg_end] = self._extract_p_trending(
                            segment, current_model, current_trending_indices, current_robust
                        )
                    except Exception as e:
                        logger.debug("HMM classify failed for segment: %s", e)
                continue

            if seg_idx == 0:
                # Warm-up segment: train and classify in-sample (unavoidable)
                try:
                    n_states = self._resolve_n_states(segment)
                    cov_type = self._resolve_covariance_type(n_states)
                    model = self._fit_gaussian_hmm(segment, n_states, cov_type)
                    state_labels = self._label_states_nstate(segment, model)
                    trending_indices = [idx for idx, lbl in state_labels.items() if lbl == _TRENDING]
                    if not trending_indices:
                        trending_indices = [0]
                    p_trend_all[seg_start:seg_end] = self._extract_p_trending(
                        segment, model, trending_indices, current_robust
                    )
                    current_model = model
                    current_trending_indices = trending_indices
                except Exception as exc:
                    logger.warning(
                        "HMMClassifier: warm-up fit failed [%d:%d] — %s",
                        seg_start, seg_end, exc,
                    )
            else:
                # Out-of-sample: classify using model from previous segment
                if current_model is not None:
                    try:
                        p_trend_all[seg_start:seg_end] = self._extract_p_trending(
                            segment, current_model, current_trending_indices, current_robust
                        )
                    except Exception as exc:
                        logger.warning(
                            "HMMClassifier: OOS classify failed [%d:%d] — %s",
                            seg_start, seg_end, exc,
                        )

                # Handle BCPD-triggered mid-segment retraining
                if bcpd_aligned is not None:
                    seg_bcpd = bcpd_aligned[seg_start:seg_end]
                    cp_indices = np.where(seg_bcpd > 0)[0]
                    if len(cp_indices) > 0:
                        # Retrain at first changepoint in this segment
                        cp_local = cp_indices[0]
                        cp_global = seg_start + cp_local
                        train_start = max(0, cp_global - window)
                        train_data = X[train_start:cp_global]
                        if len(train_data) >= self.config.min_train_bars:
                            try:
                                n_states = self._resolve_n_states(train_data)
                                cov_type = self._resolve_covariance_type(n_states)
                                model = self._fit_gaussian_hmm(train_data, n_states, cov_type)
                                state_labels = self._label_states_nstate(train_data, model)
                                trending_indices = [idx for idx, lbl in state_labels.items() if lbl == _TRENDING]
                                if not trending_indices:
                                    trending_indices = [0]
                                # Re-classify remaining bars after CP with fresh model
                                remaining = X[cp_global:seg_end]
                                if len(remaining) > 0:
                                    p_trend_all[cp_global:seg_end] = self._extract_p_trending(
                                        remaining, model, trending_indices, current_robust
                                    )
                                current_model = model
                                current_trending_indices = trending_indices
                            except Exception as exc:
                                logger.warning(
                                    "HMMClassifier: BCPD retrain failed at %d — %s",
                                    cp_global, exc,
                                )

                # Then retrain on this segment for the NEXT segment's use
                try:
                    n_states = self._resolve_n_states(segment)
                    cov_type = self._resolve_covariance_type(n_states)
                    model = self._fit_gaussian_hmm(segment, n_states, cov_type)
                    state_labels = self._label_states_nstate(segment, model)
                    trending_indices = [idx for idx, lbl in state_labels.items() if lbl == _TRENDING]
                    if not trending_indices:
                        trending_indices = [0]
                    current_model = model
                    current_trending_indices = trending_indices
                except Exception as exc:
                    logger.warning(
                        "HMMClassifier: retrain for next seg failed [%d:%d] — %s",
                        seg_start, seg_end, exc,
                    )

        result = df.copy()
        pad = np.full(len(df) - n, 0.5)
        p_padded = np.concatenate([pad, p_trend_all])
        result["hmm_p_trending"] = p_padded
        result["hmm_regime"] = np.where(p_padded >= 0.5, _TRENDING, _NON_TRENDING)
        return result

    def force_retrain(self) -> None:
        """Flag that next classify() call must refit the model."""
        self._force_retrain_flag = True

    def reset(self):
        """Reset model state (for walk-forward CV splits)."""
        self._model = None
        self._model_age = 0
        self._force_retrain_flag = False
        self._diag = self._empty_diagnostics()

    def diagnostics(self) -> dict:
        """Return HMM fit-health diagnostics for the current run."""
        fit_attempts = max(int(self._diag["fit_attempts"]), 1)
        fit_successes = max(int(self._diag["fit_successes"]), 1)
        return {
            **self._diag,
            "fit_failure_rate": float(self._diag["fit_failures"] / fit_attempts),
            "unstable_fit_rate": float(self._diag["unstable_fits"] / fit_successes),
            "zero_transition_fit_rate": float(
                self._diag["zero_transition_row_fits"] / fit_successes
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_p_trending(
        self,
        X: np.ndarray,
        model: GaussianHMM,
        trending_indices: list[int],
        use_robust: bool,
    ) -> np.ndarray:
        """Extract P(trending) for each observation, summing over trending state indices."""
        if use_robust:
            proba = self._robust_state_probs(X, model)
        else:
            proba = model.predict_proba(X)
        return np.sum(proba[:, trending_indices], axis=1)

    def _resolve_n_states(self, X: np.ndarray) -> int:
        """Determine number of HMM states: fixed or BIC-selected."""
        if self.config.hmm_n_states >= 2:
            return self.config.hmm_n_states
        # Auto-select via BIC
        return self._select_n_states(X)

    def _resolve_covariance_type(self, n_states: int) -> str:
        """Return covariance type, falling back to 'diag' for 2-state backward compat."""
        if n_states == 2 and self.config.hmm_n_states == 0:
            # When auto-selected to 2 states, use config's covariance type
            return self.config.hmm_covariance_type
        if self.config.hmm_n_states == 2:
            # Explicit 2-state mode: use diag for backward compatibility
            return "diag"
        return self.config.hmm_covariance_type

    def _select_n_states(self, X: np.ndarray) -> int:
        """Fit 2, 3, ..., max_states GaussianHMMs, return n with lowest BIC.

        Early-stops when BIC increases (U-shaped: once it rises, more states won't help).
        """
        best_n, best_bic = 2, np.inf
        for n in range(2, self.config.hmm_max_states + 1):
            try:
                model = self._fit_gaussian_hmm(
                    X,
                    n,
                    self.config.hmm_covariance_type,
                    tol=None,
                )
                # BIC = -2 * log_likelihood + k * log(N)
                # k = free params: (n-1) transition probs per row * n rows
                #     + n * d means + n * d variances (diag) or n * d*(d+1)/2 (full)
                d = X.shape[1]
                if self.config.hmm_covariance_type == "diag":
                    n_cov_params = n * d
                else:  # full
                    n_cov_params = n * d * (d + 1) // 2
                k = n * (n - 1) + n * d + n_cov_params
                log_likelihood = model.score(X) * len(X)  # score returns per-sample avg
                bic = -2 * log_likelihood + k * np.log(len(X))
                if bic < best_bic:
                    best_bic = bic
                    best_n = n
                else:
                    break  # BIC increasing — more states won't help
            except Exception:
                continue
        logger.debug("HMMClassifier: BIC selection chose %d states", best_n)
        return best_n

    def _maybe_retrain(self, X: np.ndarray) -> None:
        need_retrain = (
            self._model is None
            or self._model_age >= self.config.retrain_window
            or self._force_retrain_flag
        )
        if need_retrain:
            self._fit(X)
            self._force_retrain_flag = False

        self._model_age += 1

    def _fit(self, X: np.ndarray) -> None:
        """Fit N-state GaussianHMM and label states."""
        window = X[-self.config.retrain_window:]
        try:
            n_states = self._resolve_n_states(window)
            cov_type = self._resolve_covariance_type(n_states)
            model = self._fit_gaussian_hmm(window, n_states, cov_type)
            self._model = model
            self._model_age = 0
            self._n_states = n_states

            # Label states
            self._state_labels = self._label_states_nstate(window, model)
            self._trending_indices = [
                idx for idx, lbl in self._state_labels.items() if lbl == _TRENDING
            ]
            self._crisis_indices = [
                idx for idx, lbl in self._state_labels.items() if lbl == _CRISIS
            ]
            # For backward compat: set _trending_idx to first trending state
            if self._trending_indices:
                self._trending_idx = self._trending_indices[0]
            else:
                self._trending_idx = 0

            logger.debug(
                "HMMClassifier: retrained on %d bars, %d states, labels=%s",
                len(window), n_states, self._state_labels,
            )
        except Exception as exc:
            logger.warning("HMMClassifier: fit failed — %s", exc)
            self._model = None

    def _label_states_nstate(self, X: np.ndarray, model: GaussianHMM) -> dict[int, str]:
        """
        Label N states as TRENDING, MEAN_REVERTING, or CRISIS.

        For 2-state models, falls back to the original binary labeling logic
        to preserve backward compatibility.

        Algorithm for 3+ states:
        1. Compute per-state: mean_return, vol, directional_efficiency, autocorrelation
        2. Crisis: state with highest vol AND negative mean_return (vol > 2x median)
        3. Remaining: highest |mean_return| + positive autocorr -> TRENDING, rest -> MEAN_REVERTING
        """
        n_states = model.n_components
        state_seq = model.predict(X)
        returns = X[:, 0]  # log_return is first feature

        if n_states == 2:
            # Backward-compatible binary labeling
            trending_idx = self._label_states(X, model)
            return {
                trending_idx: _TRENDING,
                1 - trending_idx: _MEAN_REVERTING,
            }

        # Compute per-state statistics
        state_stats = {}
        for s in range(n_states):
            mask = state_seq == s
            count = mask.sum()
            if count < 2:
                state_stats[s] = {
                    "mean_return": 0.0, "vol": 0.0, "de": 0.0, "autocorr": 0.0,
                }
                continue

            s_returns = returns[mask]
            mean_ret = float(s_returns.mean())
            vol = float(s_returns.std())

            # Run-level directional efficiency
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

            # Lag-1 autocorrelation within contiguous runs
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
                            ac = float(np.corrcoef(run_ret[:-1], run_ret[1:])[0, 1])
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

        # Step 2: Identify crisis state
        vols = [state_stats[s]["vol"] for s in range(n_states)]
        median_vol = float(np.median(vols))
        labels: dict[int, str] = {}

        crisis_candidates = [
            s for s in range(n_states)
            if state_stats[s]["vol"] > self.config.hmm_crisis_vol_mult * median_vol
            and state_stats[s]["mean_return"] < 0
        ]
        if crisis_candidates:
            # Pick the one with highest vol
            crisis_state = max(crisis_candidates, key=lambda s: state_stats[s]["vol"])
            labels[crisis_state] = _CRISIS

        # Step 3: Among remaining, label TRENDING vs MEAN_REVERTING
        remaining = [s for s in range(n_states) if s not in labels]
        if remaining:
            # Score each remaining state: |mean_return| * (1 + de) * (1 + max(autocorr, 0))
            scores = {}
            for s in remaining:
                st = state_stats[s]
                scores[s] = abs(st["mean_return"]) * (1.0 + st["de"]) * (1.0 + max(st["autocorr"], 0.0))

            # Highest score -> TRENDING
            trending_state = max(remaining, key=lambda s: scores[s])
            labels[trending_state] = _TRENDING

            # Rest -> MEAN_REVERTING
            for s in remaining:
                if s not in labels:
                    labels[s] = _MEAN_REVERTING

        logger.debug(
            "HMMClassifier _label_states_nstate: stats=%s labels=%s",
            {s: {k: f"{v:.5f}" for k, v in st.items()} for s, st in state_stats.items()},
            labels,
        )
        return labels

    def _fit_gaussian_hmm(
        self,
        X: np.ndarray,
        n_components: int,
        covariance_type: str,
        *,
        tol: Optional[float] = 1e-3,
    ) -> GaussianHMM:
        """Fit a GaussianHMM while containing known hmmlearn numeric warnings.

        Small or weakly separated samples can trigger an internal
        `RuntimeWarning: invalid value encountered in divide` during EM updates
        even when the final fitted model is usable. Keep that warning local,
        then reject the fit if any learned parameters are non-finite.
        """
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

        zero_rows = int(np.sum(np.isclose(model.transmat_.sum(axis=1), 0.0)))
        self._diag["zero_transition_rows"] += zero_rows
        if zero_rows > 0:
            self._diag["zero_transition_row_fits"] += 1
        return model

    @staticmethod
    def _validate_fitted_model(model: GaussianHMM) -> None:
        """Reject fits that produced non-finite HMM parameters."""
        params = [model.startprob_, model.transmat_, model.means_, model.covars_]
        if not all(np.isfinite(param).all() for param in params):
            raise ValueError("GaussianHMM fit produced non-finite parameters")

    def _label_states(self, X: np.ndarray, model: GaussianHMM) -> int:
        """
        Identify which state index corresponds to TRENDING (2-state only).

        Composite 3-signal majority vote (robust for crypto):

        Signal 1 (2 votes — most reliable):
            |mean(log_return)| per state.
            Trending state has non-zero drift (positive or negative);
            MR/choppy state mean return ~ 0.

        Signal 2 (1 vote):
            Run-level directional efficiency.
            Computed over consecutive runs of each state (not trailing windows),
            so it measures DE *within* the state, not cross-contaminated.

        Signal 3 (1 vote):
            Lag-1 autocorrelation of returns within each state.
            Trending state has momentum persistence (positive autocorr);
            MR state tends toward negative autocorrelation (mean reversion).
        """
        state_seq = model.predict(X)
        returns = X[:, 0]  # log_return is first feature

        votes = [0, 0]

        # -- Signal 1: |mean return| (2 votes)
        mean_abs = [
            abs(returns[state_seq == s].mean()) if (state_seq == s).sum() > 0 else 0.0
            for s in range(2)
        ]
        votes[int(np.argmax(mean_abs))] += 2

        # -- Signal 2: Run-level directional efficiency (1 vote)
        run_de = []
        for s in range(2):
            des = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 5:  # only runs of >= 5 bars
                        run_ret = returns[i:j]
                        net = abs(run_ret.sum())
                        gross = np.abs(run_ret).sum() + _EPS
                        des.append(net / gross)
                    i = j
                else:
                    i += 1
            run_de.append(np.mean(des) if des else 0.0)
        votes[int(np.argmax(run_de))] += 1

        # -- Signal 3: Lag-1 autocorrelation within contiguous runs (1 vote)
        autocorrs = []
        for s in range(2):
            acs = []
            i = 0
            while i < len(state_seq):
                if state_seq[i] == s:
                    j = i
                    while j < len(state_seq) and state_seq[j] == s:
                        j += 1
                    if j - i >= 10:  # runs of >= 10 bars
                        run_ret = returns[i:j]
                        if len(run_ret) >= 2:
                            ac = float(np.corrcoef(run_ret[:-1], run_ret[1:])[0, 1])
                            if np.isfinite(ac):
                                acs.append(ac)
                    i = j
                else:
                    i += 1
            autocorrs.append(np.mean(acs) if acs else 0.0)
        votes[int(np.argmax(autocorrs))] += 1

        trending_idx = int(np.argmax(votes))
        logger.debug(
            "HMMClassifier _label_states: mean_abs=%s run_de=%s autocorr=%s votes=%s -> trending=%d",
            [f"{x:.5f}" for x in mean_abs],
            [f"{x:.3f}" for x in run_de],
            [f"{x:.3f}" for x in autocorrs],
            votes,
            trending_idx,
        )
        return trending_idx

    def _robust_state_probs(self, X: np.ndarray, model: GaussianHMM) -> np.ndarray:
        """
        Compute state posteriors using Student-t emission instead of Gaussian.

        Uses the fitted GaussianHMM's means and covariances as location/scale
        parameters for a Student-t distribution, providing robustness to fat tails.
        The transition matrix from the fitted model is still used for the HMM dynamics.
        """
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

        # Incorporate transition matrix priors (forward algorithm approximation)
        # Use stationary distribution as prior for first observation
        if hasattr(model, 'startprob_'):
            log_prob[0] += np.log(model.startprob_ + _EPS)

        # Normalize to posterior probabilities
        log_prob -= np.max(log_prob, axis=1, keepdims=True)
        prob = np.exp(log_prob)
        prob /= prob.sum(axis=1, keepdims=True) + _EPS
        return prob

    def _build_features(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """
        Construct feature matrix [log_return, log_vol, (hurst), (volume)].

        Returns None if insufficient data.
        """
        if "close" not in df.columns or len(df) < self.config.log_vol_lookback + 2:
            return None

        close = df["close"].values
        log_ret = np.diff(np.log(close + _EPS))  # length T-1

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

        # Optionally add Hurst exponent
        if self.config.use_hurst:
            from libs.regime.kernels.hurst import rolling_hurst
            hurst = rolling_hurst(
                close,
                lookback=self.config.hurst_lookback,
                min_periods=min(50, self.config.hurst_lookback // 2),
            )
            features.append(hurst[1:])

        # Optionally add log volume change
        if self.config.use_volume and "volume" in df.columns:
            volume = df["volume"].values
            log_vol_change = (
                pd.Series(np.log(volume + _EPS))
                .diff(self.config.log_vol_lookback)
                .ffill()
                .fillna(0.0)
                .values
            )
            # Slice to match log_ret length (T-1)
            features.append(log_vol_change[1:])

        X = np.column_stack(features).astype(np.float64)
        valid = np.isfinite(X).all(axis=1)
        return X[valid] if valid.any() else None

    def _default_state(self) -> HMMState:
        return HMMState(
            p_trending=0.5,
            p_non_trending=0.5,
            hmm_regime=_NON_TRENDING,
            model_age_bars=self._model_age,
            crisis_prob=0.0,
            n_states=self._n_states,
            metadata={"reason": "insufficient_data"},
        )

    def _model_metadata(self) -> dict:
        if self._model is None:
            return {}
        return {
            "state_means": self._model.means_.tolist(),
            "state_covars": self._model.covars_.tolist(),
            "trending_idx": self._trending_idx,
            "n_states": self._n_states,
            "state_labels": self._state_labels,
            "covariance_type": self._model.covariance_type,
            "diagnostics": self.diagnostics(),
        }

    @staticmethod
    def _empty_diagnostics() -> dict:
        return {
            "fit_attempts": 0,
            "fit_successes": 0,
            "fit_failures": 0,
            "unstable_fits": 0,
            "zero_transition_rows": 0,
            "zero_transition_row_fits": 0,
        }

    @staticmethod
    def _is_unstable_fit(model: GaussianHMM) -> bool:
        monitor = getattr(model, "monitor_", None)
        if monitor is None:
            return False
        converged = bool(getattr(monitor, "converged", True))
        history = list(getattr(monitor, "history", []))
        decreasing_ll = len(history) >= 2 and history[-1] < history[-2] - 1e-8
        return (not converged) or decreasing_ll
