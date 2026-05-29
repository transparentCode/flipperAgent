"""Two-stage automated optimizer: fANOVA screening → focused search + OOS gate.

Stage 1: Run a quick screening study (all params, fewer trials), compute
         fANOVA importances, classify params as FREEZE or OPTIMIZE.

Stage 2: Run the main study on the reduced search space using Optuna's
         PartialFixedSampler, then gate deployment on OOS performance.

Works for all 4 direction models without modifying per-model optimizers.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any

import optuna
import pandas as pd

from libs.common.config import ConfigManager
from libs.contracts.optimization import ScreeningSummary, TwoStageResult
from libs.models.registry import ModelRegistry
from libs.optim_utils.callbacks import ConvergenceCallback
from libs.optim_utils.walk_forward import WalkForwardSplitter

logger = logging.getLogger("app.optimization.two_stage")

# Model name → optimizer module path (snake_case convention).
_MODEL_MODULE_MAP: dict[str, str] = {
    "MeanReversion": "libs.models.mean_reversion.optimization.optimizer",
    "Momentum": "libs.models.momentum.optimization.optimizer",
    "SqueezeBreakout": "libs.models.squeeze_breakout.optimization.optimizer",
    "TrendFollowing": "libs.models.trend_following.optimization.optimizer",
}


def _to_snake(name: str) -> str:
    """CamelCase → snake_case (fallback for unknown models)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _resolve_optimizer_module(model_name: str):
    """Import and return the per-model optimizer module."""
    module_path = _MODEL_MODULE_MAP.get(model_name)
    if module_path is None:
        module_path = f"libs.models.{_to_snake(model_name)}.optimization.optimizer"
    return importlib.import_module(module_path)


# Hardcoded fallbacks used when risk.yaml is missing or incomplete.
_FALLBACK_TP_PCTS = (0.015, 0.03, 0.05)
_FALLBACK_TP_PORTIONS = (0.40, 0.30, 0.30)
_FALLBACK_SL_PCT = 0.02
_FALLBACK_TRAIL_TO_BE = True


class TwoStageOptimizer:
    """Automated two-stage optimization with importance screening and OOS gating."""

    @staticmethod
    def _load_risk_tp_sl() -> dict[str, Any]:
        """Read multi-level TP/SL config from risk.yaml via ConfigManager."""
        try:
            cfg = ConfigManager()
            tp_cfg = cfg.get("risk.take_profit", {})
            sl_cfg = cfg.get("risk.stop_loss", {})
        except Exception:
            logger.warning("Could not load risk.yaml — using hardcoded fallbacks")
            return {
                "tp_pcts": _FALLBACK_TP_PCTS,
                "tp_portions": _FALLBACK_TP_PORTIONS,
                "sl_pct": _FALLBACK_SL_PCT,
                "trail_to_breakeven": _FALLBACK_TRAIL_TO_BE,
            }

        # Parse multi_level TP config
        levels = tp_cfg.get("multi_level", {}).get("levels", [])
        if levels:
            tp_pcts = tuple(lvl["pct"] / 100.0 for lvl in levels)
            tp_portions = tuple(lvl["portion"] / 100.0 if lvl["portion"] > 1 else lvl["portion"] for lvl in levels)
            trail = tp_cfg.get("multi_level", {}).get("trail_to_breakeven", _FALLBACK_TRAIL_TO_BE)
        else:
            tp_pcts = _FALLBACK_TP_PCTS
            tp_portions = _FALLBACK_TP_PORTIONS
            trail = _FALLBACK_TRAIL_TO_BE

        # Parse SL config
        sl_pct = sl_cfg.get("fixed_pct", {}).get("pct", _FALLBACK_SL_PCT * 100) / 100.0

        return {
            "tp_pcts": tp_pcts,
            "tp_portions": tp_portions,
            "sl_pct": sl_pct,
            "trail_to_breakeven": trail,
        }

    def __init__(
        self,
        screening_trials: int = 50,
        main_trials: int = 200,
        importance_threshold: float = 0.05,
        convergence_patience: int = 50,
        oos_sharpe_ratio: float = 0.50,
        seed: int = 42,
    ) -> None:
        self.screening_trials = screening_trials
        self.main_trials = main_trials
        self.importance_threshold = importance_threshold
        self.convergence_patience = convergence_patience
        self.oos_sharpe_ratio = oos_sharpe_ratio
        self.seed = seed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        model_name: str,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
        tp_pcts: tuple[float, ...] | None = None,
        tp_portions: tuple[float, ...] | None = None,
        sl_pct: float | None = None,
        trail_to_breakeven: bool | None = None,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        purge_bars: int = 24,
    ) -> TwoStageResult:
        """Execute the full two-stage pipeline and return the result.

        TP/SL parameters default to values from ``configs/risk.yaml``
        (multi_level take-profit and fixed_pct stop-loss).  Pass explicit
        values to override.
        """
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Resolve TP/SL from risk.yaml when not explicitly provided
        if any(v is None for v in (tp_pcts, tp_portions, sl_pct, trail_to_breakeven)):
            risk_defaults = self._load_risk_tp_sl()
            if tp_pcts is None:
                tp_pcts = risk_defaults["tp_pcts"]
            if tp_portions is None:
                tp_portions = risk_defaults["tp_portions"]
            if sl_pct is None:
                sl_pct = risk_defaults["sl_pct"]
            if trail_to_breakeven is None:
                trail_to_breakeven = risk_defaults["trail_to_breakeven"]

        mod = _resolve_optimizer_module(model_name)
        model_cls = ModelRegistry.get(model_name)
        schema = model_cls.meta.hyperparameter_schema
        default_params = {k: v.default for k, v in schema.items()}
        study_defaults = getattr(mod, "STUDY_DEFAULTS", {})
        is_multi = (
            study_defaults.get("directions") is not None
            and len(study_defaults.get("directions", [])) > 1
        )

        # Shared kwargs for make_objective / evaluate_oos
        obj_kwargs: dict[str, Any] = dict(
            feature_df=feature_df,
            timeframe=timeframe,
            cost_bps=cost_bps,
            tp_pcts=tp_pcts,
            tp_portions=tp_portions,
            sl_pct=sl_pct,
            trail_to_breakeven=trail_to_breakeven,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            purge_bars=purge_bars,
        )

        # ── Stage 1: Screening ──
        logger.info(
            f"[{model_name}] Stage 1: screening with "
            f"{self.screening_trials} trials"
        )
        screening_objective = mod.make_objective(**obj_kwargs)
        screening_study = self._create_study(
            model_name, "screening", study_defaults, is_multi
        )
        screening_study.optimize(
            screening_objective, n_trials=self.screening_trials
        )

        importances = self._compute_importances(screening_study, is_multi)
        frozen_params, active_params = self._classify_params(
            importances, schema
        )

        screening = ScreeningSummary(
            screening_trials=self.screening_trials,
            importance_threshold=self.importance_threshold,
            importances=importances,
            frozen_params=frozen_params,
            active_params=active_params,
            total_params=len(schema),
            reduced_params=len(active_params),
        )
        logger.info(
            f"[{model_name}] Screening: {len(frozen_params)} frozen, "
            f"{len(active_params)} active "
            f"(threshold={self.importance_threshold})"
        )

        # ── Stage 2: Focused optimization ──
        logger.info(
            f"[{model_name}] Stage 2: focused optimization with "
            f"{self.main_trials} trials"
        )
        main_objective = mod.make_objective(**obj_kwargs)
        main_study = self._create_study(
            model_name,
            "focused",
            study_defaults,
            is_multi,
            fixed_params=frozen_params if frozen_params else None,
        )
        main_study.optimize(
            main_objective,
            n_trials=self.main_trials,
            callbacks=[
                ConvergenceCallback(patience=self.convergence_patience)
            ],
        )

        # Extract best params
        best_raw = self._extract_best_params(main_study, is_multi)
        best_params = mod.post_process_params(best_raw)
        best_score = self._extract_best_score(main_study, is_multi)

        # ── OOS Gate ──
        splitter = WalkForwardSplitter(
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            oos_ratio=1.0 - train_ratio - val_ratio,
            purge_bars=purge_bars,
        )
        split = splitter.split(len(feature_df))
        oos_results = mod.evaluate_oos(
            feature_df=feature_df,
            params=best_params,
            split=split,
            timeframe=timeframe,
            cost_bps=cost_bps,
            tp_pcts=tp_pcts,
            tp_portions=tp_portions,
            sl_pct=sl_pct,
            trail_to_breakeven=trail_to_breakeven,
        )

        deployed, rejection_reason = self._apply_oos_gate(oos_results)

        if deployed:
            logger.info(
                f"[{model_name}] OOS gate PASSED — deploying optimized params"
            )
            final_params = best_params
        else:
            logger.warning(
                f"[{model_name}] OOS gate REJECTED: {rejection_reason} "
                f"— falling back to defaults"
            )
            final_params = default_params

        # Remove internal degradation_warning key from oos_metrics
        oos_metrics = {
            k: v for k, v in oos_results.items() if k != "degradation_warning"
        }

        return TwoStageResult(
            model_name=model_name,
            asset="",  # caller fills if needed
            timeframe=timeframe,
            best_params=final_params,
            deployed=deployed,
            rejection_reason=rejection_reason,
            screening=screening,
            oos_metrics=oos_metrics,
            default_params=default_params,
            stage2_best_score=best_score,
            stage2_n_trials=len(
                [
                    t
                    for t in main_study.trials
                    if t.values is not None or t.value is not None
                ]
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_study(
        self,
        model_name: str,
        stage: str,
        study_defaults: dict,
        is_multi: bool,
        fixed_params: dict[str, Any] | None = None,
    ) -> optuna.Study:
        """Create an Optuna study with appropriate sampler and direction."""
        if is_multi:
            base_sampler = optuna.samplers.NSGAIISampler(seed=self.seed)
            directions = study_defaults.get(
                "directions", ["maximize", "maximize"]
            )
        else:
            base_sampler = optuna.samplers.TPESampler(seed=self.seed)
            directions = None

        sampler = base_sampler
        if fixed_params:
            sampler = optuna.samplers.PartialFixedSampler(
                fixed_params=fixed_params,
                base_sampler=base_sampler,
            )

        name = f"{model_name}_{stage}"
        if is_multi:
            return optuna.create_study(
                study_name=name, directions=directions, sampler=sampler
            )
        else:
            return optuna.create_study(
                study_name=name, direction="maximize", sampler=sampler
            )

    def _compute_importances(
        self, study: optuna.Study, is_multi: bool
    ) -> dict[str, float]:
        """Compute fANOVA param importances from a completed study."""
        try:
            if is_multi:
                importances = optuna.importance.get_param_importances(
                    study, target=lambda t: t.values[0]
                )
            else:
                importances = optuna.importance.get_param_importances(study)
        except Exception as exc:
            logger.warning(
                f"fANOVA failed ({exc}), treating all params as active"
            )
            importances = {}
        return importances

    def _classify_params(
        self,
        importances: dict[str, float],
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """Split params into frozen (below threshold) and active (above).

        If fANOVA returned no importances (error), all params are active.
        Params not in fANOVA output are treated as active.
        """
        frozen: dict[str, Any] = {}
        active: list[str] = []

        if not importances:
            active = list(schema.keys())
            return frozen, active

        for param_name, pdef in schema.items():
            imp = importances.get(param_name, None)
            if imp is not None and imp < self.importance_threshold:
                frozen[param_name] = pdef.default
            else:
                active.append(param_name)

        # Safety: if ALL params frozen, keep the most important one active
        if not active and importances:
            best_param = max(importances, key=importances.get)
            active.append(best_param)
            frozen.pop(best_param, None)

        return frozen, active

    def _extract_best_params(
        self, study: optuna.Study, is_multi: bool
    ) -> dict[str, Any]:
        """Get best params from single- or multi-objective study."""
        if is_multi:
            pareto = study.best_trials
            if not pareto:
                return {}
            best_trial = max(pareto, key=lambda t: t.values[0])
            return dict(best_trial.params)
        else:
            return dict(study.best_params)

    def _extract_best_score(
        self, study: optuna.Study, is_multi: bool
    ) -> float | None:
        """Get best score value from the study."""
        if is_multi:
            pareto = study.best_trials
            if not pareto:
                return None
            return max(t.values[0] for t in pareto)
        else:
            return study.best_value

    def _apply_oos_gate(
        self, oos_results: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Apply OOS gating rules. Returns (deployed, rejection_reason)."""
        val_sharpe = oos_results.get("validate", {}).get("sharpe", 0.0)
        oos_sharpe = oos_results.get("oos", {}).get("sharpe", 0.0)

        # Rule 1: OOS Sharpe negative when validate positive → REJECT
        if val_sharpe > 0 and oos_sharpe < 0:
            return False, (
                f"OOS Sharpe negative ({oos_sharpe:.3f}) while validate "
                f"positive ({val_sharpe:.3f}) — likely overfit"
            )

        # Rule 2: OOS Sharpe < threshold fraction of validate → REJECT
        if val_sharpe > 0 and oos_sharpe < self.oos_sharpe_ratio * val_sharpe:
            return False, (
                f"OOS Sharpe ({oos_sharpe:.3f}) < "
                f"{self.oos_sharpe_ratio:.0%} of validate Sharpe "
                f"({val_sharpe:.3f}) — excessive degradation"
            )

        # Rule 3: Both negative → REJECT (no edge found)
        if val_sharpe <= 0 and oos_sharpe <= 0:
            return False, (
                f"Both validate ({val_sharpe:.3f}) and OOS "
                f"({oos_sharpe:.3f}) Sharpe non-positive — no edge detected"
            )

        return True, None
