"""
Meta-Learned Ensemble Strategy
================================
XGBoost/LightGBM-based ensemble that learns to score zones
from their feature vectors instead of using fixed weights.

Trains on historical feature snapshots with labels derived from
zone outcomes (bounce vs breakout).  Falls back to
``WeightedAverageEnsemble`` when no trained model is available.

Config params (via ``config`` dict):
  * ``model_path``    — path to saved model (default: None → fallback)
  * ``use_lightgbm``  — use LightGBM instead of XGBoost (default: False)
  * ``feature_names`` — ordered list of features to extract (auto-detected)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import register_ensemble
from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
from app.sr.models import (
    CandidateLevel,
    LevelFeatureVector,
    ScoredLevel,
)

logger = logging.getLogger(__name__)

# Optional deps — graceful degradation
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    xgb = None  # type: ignore
    XGB_AVAILABLE = False

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    lgb = None  # type: ignore
    LGB_AVAILABLE = False


# Default feature extraction order (matches LevelFeatureVector fields)
DEFAULT_FEATURE_NAMES = [
    "touch_count", "rejection_ratio", "volume_at_touches",
    "time_since_formation", "cluster_density", "atr_distance_from_price",
    "poc_distance_atr", "value_area_overlap", "mtf_confluence_count",
    "breakout_recency", "volume_trend_at_level", "wick_depth_max_atr",
    "false_breakout_count", "kernel_agreement", "gap_proximity_atr",
    "gap_direction_alignment", "regime_alignment",
    "universe_agreement", "sector_cluster", "dominant_alignment",
]


@register_ensemble("meta_learned")
class MetaLearnedEnsemble(BaseEnsembleStrategy):
    """
    ML-based ensemble scoring.

    Uses a trained gradient boosting model to predict zone quality
    from the feature vector.  Falls back to weighted average when
    no model is loaded.
    """

    @property
    def strategy_name(self) -> str:
        return "meta_learned"

    def __init__(self):
        self._model = None
        self._feature_names: List[str] = DEFAULT_FEATURE_NAMES
        self._fallback = None  # lazy-loaded

    def load_model(self, model_path: str, use_lightgbm: bool = False) -> bool:
        """
        Load a trained model from disk.

        Args:
            model_path: Path to saved model file.
            use_lightgbm: If True, load as LightGBM Booster.

        Returns:
            True if loaded successfully.
        """
        try:
            if use_lightgbm:
                if not LGB_AVAILABLE:
                    logger.warning("LightGBM not installed")
                    return False
                self._model = lgb.Booster(model_file=model_path)
            else:
                if not XGB_AVAILABLE:
                    logger.warning("XGBoost not installed")
                    return False
                self._model = xgb.Booster()
                self._model.load_model(model_path)
            logger.info("Loaded meta-learned model from %s", model_path)
            return True
        except Exception as e:
            logger.error("Failed to load model: %s", e)
            return False

    def set_model(self, model: Any) -> None:
        """Set model directly (for testing or in-memory training)."""
        self._model = model

    def score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        """Score candidates using ML model or fallback."""
        meta_cfg = config.get("meta_learned", {})
        # Try loading model from config if not already loaded
        if self._model is None:
            model_path = meta_cfg.get("model_path", config.get("model_path"))
            if model_path:
                use_lgb = meta_cfg.get("use_lightgbm", config.get("use_lightgbm", False))
                self.load_model(model_path, use_lightgbm=use_lgb)

        # If still no model → fallback
        if self._model is None:
            return self._fallback_score(candidates, features, config)

        return self._ml_score(candidates, features, config)

    def _ml_score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        """Score using the loaded ML model."""
        results: List[ScoredLevel] = []

        # Build feature matrix
        feature_rows = []
        valid_candidates = []
        for c in candidates:
            key = self.candidate_key(c)
            fv = features.get(key, LevelFeatureVector())
            row = self._extract_features(fv)
            feature_rows.append(row)
            valid_candidates.append((c, fv))

        if not feature_rows:
            return results

        X = np.array(feature_rows, dtype=np.float32)

        # Predict
        try:
            if XGB_AVAILABLE and isinstance(self._model, xgb.Booster):
                dmat = xgb.DMatrix(X, feature_names=self._feature_names[:X.shape[1]])
                predictions = self._model.predict(dmat)
            elif LGB_AVAILABLE and hasattr(self._model, "predict"):
                predictions = self._model.predict(X)
            else:
                predictions = self._model.predict(X)
        except Exception as e:
            logger.error("ML prediction failed: %s — falling back", e)
            return self._fallback_score(candidates, features, config)

        for i, (c, fv) in enumerate(valid_candidates):
            strength = self._blend_strength(float(predictions[i]), fv, config)
            confidence = self.compute_standardized_confidence(c, fv, config, config.get("regime_state"))
            contributing_proximity = float(config.get("contributing_proximity_atr", 0.5))
            contributing = WeightedAverageEnsemble._find_contributing_kernels(
                c, candidates, contributing_proximity,
            )
            structural_set = set(config.get(
                "structural_kernels",
                ["pivot_hl", "fractal_channel", "regression_band"],
            ))
            zone_quality = self.compute_zone_quality(strength, confidence, c, fv, config)
            confluence_tier = self.compute_confluence_tier(fv, contributing, structural_set)
            results.append(ScoredLevel(
                candidate=c,
                features=fv,
                strength=strength,
                confidence=confidence,
                contributing_kernels=contributing,
                ensemble_method="meta_learned",
                zone_quality=zone_quality,
                confluence_tier=confluence_tier,
            ))

        return results

    def _fallback_score(
        self,
        candidates: List[CandidateLevel],
        features: Dict[str, LevelFeatureVector],
        config: Dict[str, Any],
    ) -> List[ScoredLevel]:
        """Fall back to WeightedAverageEnsemble."""
        if self._fallback is None:
            from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
            self._fallback = WeightedAverageEnsemble()
        return self._fallback.score(candidates, features, config)

    def _extract_features(self, fv: LevelFeatureVector) -> List[float]:
        """Extract feature values in canonical order."""
        return [getattr(fv, name, 0.0) for name in self._feature_names]

    @staticmethod
    def _blend_strength(
        prediction: float,
        fv: LevelFeatureVector,
        config: Dict[str, Any],
    ) -> float:
        meta_cfg = config.get("meta_learned", {})
        coeff_keys = (
            "confidence_strength_coeff",
            "confidence_touch_coeff",
            "confidence_agreement_coeff",
        )
        if not any(key in meta_cfg for key in coeff_keys):
            return float(np.clip(prediction, 0.0, 1.0))

        conf_cfg = config.get("confidence", {})
        touch_div = float(conf_cfg.get("touch_divisor", 5.0))
        agreement_div = float(conf_cfg.get("agreement_divisor", 3.0))

        touch_factor = min(fv.touch_count / touch_div, 1.0) if touch_div > 0 else 0.0
        agreement_factor = min(fv.kernel_agreement / agreement_div, 1.0) if agreement_div > 0 else 0.0

        strength_coeff = max(0.0, float(meta_cfg.get("confidence_strength_coeff", 1.0)))
        touch_coeff = max(0.0, float(meta_cfg.get("confidence_touch_coeff", 0.0)))
        agreement_coeff = max(0.0, float(meta_cfg.get("confidence_agreement_coeff", 0.0)))
        total_coeff = strength_coeff + touch_coeff + agreement_coeff

        if total_coeff <= 0:
            return float(np.clip(prediction, 0.0, 1.0))

        blended = (
            strength_coeff * prediction
            + touch_coeff * touch_factor
            + agreement_coeff * agreement_factor
        ) / total_coeff
        return float(np.clip(blended, 0.0, 1.0))

    @staticmethod
    def prepare_training_data(
        feature_vectors: List[LevelFeatureVector],
        labels: List[float],
    ) -> tuple:
        """
        Prepare training data for model fitting.

        Args:
            feature_vectors: Historical feature snapshots.
            labels: Zone quality labels (0.0=bad, 1.0=perfect).

        Returns:
            (X, y) numpy arrays.
        """
        X = np.array([
            [getattr(fv, name, 0.0) for name in DEFAULT_FEATURE_NAMES]
            for fv in feature_vectors
        ], dtype=np.float32)
        y = np.array(labels, dtype=np.float32)
        return X, y
