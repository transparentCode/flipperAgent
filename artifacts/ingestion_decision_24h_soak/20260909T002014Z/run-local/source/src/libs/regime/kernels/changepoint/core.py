"""
Bayesian Online Changepoint Detection (BCPD).

Adams & MacKay (2007): "Bayesian Online Changepoint Detection"
https://arxiv.org/abs/0710.3742

Uses a Student-t predictive distribution with conjugate Normal-Gamma prior.
Runs forward-only (non-hindsight) via message-passing run-length update.
Pure NumPy — no Numba dependency.
"""

from __future__ import annotations

import numpy as np
from scipy.special import gammaln


def _student_t_log_predictive(
    x: float,
    alpha: np.ndarray,
    beta: np.ndarray,
    kappa: np.ndarray,
    mu: np.ndarray,
) -> np.ndarray:
    """
    Log predictive probability under Student-t marginal of Normal-Gamma conjugate.

    Parameters
    ----------
    x : scalar observation
    alpha, beta, kappa, mu : shape (r+1,) sufficient stat vectors at time t

    Returns
    -------
    log_pred : shape (r+1,) log P(x_t | run_length=r, data)
    """
    nu = 2.0 * alpha
    var = beta * (kappa + 1.0) / (alpha * kappa)
    diff = x - mu
    log_pred = (
        np.log(np.pi * nu * var) * (-0.5)
        + gammaln((nu + 1.0) / 2.0)
        - gammaln(nu / 2.0)
        - 0.5 * (nu + 1.0) * np.log1p(diff * diff / (nu * var))
    )
    return log_pred


def _update_sufficient_stats(
    x: float,
    alpha: np.ndarray,
    beta: np.ndarray,
    kappa: np.ndarray,
    mu: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Conjugate Normal-Gamma update for new observation x."""
    mu_new = (kappa * mu + x) / (kappa + 1.0)
    kappa_new = kappa + 1.0
    alpha_new = alpha + 0.5
    beta_new = beta + (kappa * (x - mu) ** 2) / (2.0 * (kappa + 1.0))
    return alpha_new, beta_new, kappa_new, mu_new


def bcpd_detect(
    returns: np.ndarray,
    hazard_lambda: float = 150.0,
    hazard_shape: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    kappa0: float = 1.0,
    mu0: float = 0.0,
    truncation: int = 500,
    return_posterior: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Online BCPD via run-length message passing.

    Parameters
    ----------
    returns : 1-D array of log-returns
    hazard_lambda : expected run length between changepoints (larger = rarer CPs)
    hazard_shape : Weibull shape parameter k.
        k=1.0 → constant hazard (original behavior, backward compatible).
        k>1.0 → increasing hazard (longer regimes more likely to end).
        k<1.0 → decreasing hazard (longer regimes less likely to end).
    alpha, beta : Normal-Gamma prior shape/rate
    kappa0, mu0 : Normal-Gamma prior precision weight and mean
    truncation : max run length tracked (caps memory/compute)
    return_posterior : if True, return full T×(truncation+1) posterior matrix.
        If False, use rolling 2-row buffer and return an empty array for the
        posterior (saves O(T*truncation) memory).

    Returns
    -------
    run_length_posterior : shape (T, truncation+1) if return_posterior else (0, 0)
        P(run_length=r | data[0:t]) at each time step t
    changepoint_probs : shape (T,)
        P(changepoint at t | data[0:t]) = sum of probability mass resetting to r=0
    """
    T = len(returns)

    # --- Hazard function ---
    if hazard_shape == 1.0:
        # Constant hazard (original behavior)
        hazard_prob = 1.0 / hazard_lambda
        hazard_vec = None  # signal to use scalar path
    else:
        # Weibull hazard: h(r) = (k/λ) * (r/λ)^(k-1)
        # Capped at 0.5 to prevent numerical issues
        r = np.arange(1, truncation + 1, dtype=np.float64)
        hazard_vec = (hazard_shape / hazard_lambda) * (r / hazard_lambda) ** (hazard_shape - 1.0)
        hazard_vec = np.clip(hazard_vec, 1e-10, 0.5)
        hazard_prob = None  # unused in vector path

    # Run-length posterior: log probabilities (log scale for numerical stability)
    if return_posterior:
        log_R = np.full((T + 1, truncation + 1), -np.inf)
        log_R[0, 0] = 0.0  # at t=0, run_length=0 with certainty
    else:
        # Rolling 2-row buffer: O(truncation) instead of O(T*truncation)
        log_R_prev = np.full(truncation + 1, -np.inf)
        log_R_prev[0] = 0.0
        log_R_curr = np.full(truncation + 1, -np.inf)

    # Sufficient statistics for each possible run length (vectorised)
    alpha_t = np.full(truncation + 1, alpha)
    beta_t = np.full(truncation + 1, beta)
    kappa_t = np.full(truncation + 1, kappa0)
    mu_t = np.full(truncation + 1, mu0)

    changepoint_probs = np.zeros(T)

    for t in range(T):
        x = returns[t]
        max_r = min(t + 1, truncation)  # active run lengths at this step

        # Slice active stats
        a = alpha_t[:max_r]
        b = beta_t[:max_r]
        k = kappa_t[:max_r]
        m = mu_t[:max_r]
        if return_posterior:
            lr = log_R[t, :max_r]
        else:
            lr = log_R_prev[:max_r]

        # Predictive log probs for each active run length (growth path)
        log_pred = _student_t_log_predictive(x, a, b, k, m)

        # Fresh-prior predictive for the new-run hypothesis (changepoint path)
        # P(x_t | r_t=0, fresh prior) — single scalar
        log_pred_fresh = _student_t_log_predictive(
            x,
            np.array([alpha]),
            np.array([beta]),
            np.array([kappa0]),
            np.array([mu0]),
        )[0]

        # --- Per-run-length hazard probabilities ---
        if hazard_vec is None:
            # Constant hazard (shape=1.0): scalar path, identical to original
            log_h = np.log(hazard_prob)
            log_1mh = np.log(1.0 - hazard_prob)
        else:
            # Weibull hazard: vector indexed by run length
            # Active run lengths are 0..max_r-1 (indices into hazard_vec)
            h = hazard_vec[:max_r]
            log_h = np.log(h)
            log_1mh = np.log(1.0 - h)

        # Growth probabilities: r → r+1 (no changepoint), predictive = current run
        log_grow = lr + log_pred + log_1mh

        # Changepoint probability: all r → 0, predictive = fresh prior
        # This is the key difference from growth: same transition weight (h) but
        # the predictive is evaluated under the initial prior, not the run history.
        log_cp_mass = lr + log_h + log_pred_fresh
        log_cp = np.logaddexp.reduce(log_cp_mass)

        if return_posterior:
            # Set new posteriors in full matrix
            log_R[t + 1, 1 : max_r + 1] = log_grow
            log_R[t + 1, 0] = log_cp

            # Normalise
            log_norm = np.logaddexp.reduce(log_R[t + 1, : max_r + 1])
            log_R[t + 1, : max_r + 1] -= log_norm
        else:
            # Rolling buffer: write into curr, then swap
            log_R_curr[:] = -np.inf
            log_R_curr[1 : max_r + 1] = log_grow
            log_R_curr[0] = log_cp

            # Normalise
            log_norm = np.logaddexp.reduce(log_R_curr[: max_r + 1])
            log_R_curr[: max_r + 1] -= log_norm

        # Changepoint prob = probability mass at run_length=0 AFTER this observation
        changepoint_probs[t] = np.exp(log_cp - log_norm)

        # Update sufficient statistics for surviving run lengths
        a_new, b_new, k_new, m_new = _update_sufficient_stats(x, a, b, k, m)
        alpha_t[1 : max_r + 1] = a_new
        beta_t[1 : max_r + 1] = b_new
        kappa_t[1 : max_r + 1] = k_new
        mu_t[1 : max_r + 1] = m_new
        # Reset stats for run_length=0 (fresh changepoint)
        alpha_t[0] = alpha
        beta_t[0] = beta
        kappa_t[0] = kappa0
        mu_t[0] = mu0

        if not return_posterior:
            # Swap: curr becomes prev for next iteration
            log_R_prev, log_R_curr = log_R_curr, log_R_prev

    if return_posterior:
        run_length_posterior = np.exp(log_R[1:, :])  # shape (T, truncation+1)
    else:
        run_length_posterior = np.empty((0, 0))
    return run_length_posterior, changepoint_probs


def _calc_entropy(run_length_posterior: np.ndarray) -> np.ndarray:
    """
    Shannon entropy of the run-length posterior at each time step.

    Parameters
    ----------
    run_length_posterior : shape (T, truncation+1)

    Returns
    -------
    entropy : shape (T,)
    """
    p = run_length_posterior
    with np.errstate(divide="ignore", invalid="ignore"):
        h = -np.where(p > 0, p * np.log(p), 0.0).sum(axis=1)
    return h


def _calc_kl_divergence_magnitude(
    run_length_posterior: np.ndarray,
) -> np.ndarray:
    """
    KL divergence between consecutive run-length posteriors as a change magnitude proxy.

    Parameters
    ----------
    run_length_posterior : shape (T, truncation+1)

    Returns
    -------
    kl_mag : shape (T,)  — 0.0 at t=0
    """
    T = run_length_posterior.shape[0]
    kl_mag = np.zeros(T)
    p = run_length_posterior
    for t in range(1, T):
        q = p[t - 1]
        r = p[t]
        mask = (q > 0) & (r > 0)
        if mask.any():
            kl_mag[t] = (r[mask] * np.log(r[mask] / q[mask])).sum()
    return kl_mag
