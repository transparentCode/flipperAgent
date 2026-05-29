from __future__ import annotations

from typing import Dict, List

from .schema import ResolvedPipelineConfig


class ConfigValidationError(Exception):
    """Raised when config validation fails."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__(f"Config validation failed with {len(errors)} error(s):\n" + "\n".join(f"  - {e}" for e in errors))


class ConfigValidator:
    """Validates a ResolvedPipelineConfig before pipeline execution.

    Checks:
    - Window bounds
    - Method existence (referenced methods must be enabled)
    - Feature/method dependency compatibility
    - ATR fraction bounds
    """

    # Known feature names → what they provide
    KNOWN_FEATURES: Dict[str, list] = {
        "log_price": ["log_prices", "close_raw", "valid_mask"],
        "volume_weighted": ["volume_weights", "volume_raw", "volume_clipped"],
        "session_aware": ["session_mask"],
    }

    # Known method names → what they require from features
    KNOWN_METHOD_REQUIRES: Dict[str, list] = {
        "theil_sen": ["log_prices", "volume_weights"],
        "vwr": ["log_prices", "volume_weights"],
    }

    def validate(self, config: ResolvedPipelineConfig) -> None:
        """Validate config. Raises ConfigValidationError if invalid."""
        errors: List[str] = []

        self._check_window_bounds(config, errors)
        self._check_methods_non_empty(config, errors)
        self._check_feature_method_compat(config, errors)
        self._check_atr_fractions(config, errors)
        self._check_ensemble(config, errors)
        self._check_feature_ordering(config, errors)

        if errors:
            raise ConfigValidationError(errors)

    def _check_window_bounds(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        if config.window_size < config.min_window:
            errors.append(
                f"window_size ({config.window_size}) < min_window ({config.min_window})"
            )
        if config.window_size > config.max_window:
            errors.append(
                f"window_size ({config.window_size}) > max_window ({config.max_window})"
            )

    def _check_methods_non_empty(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        enabled = [name for name, cfg in config.methods if cfg.enabled]
        if not enabled:
            errors.append("No enabled regression methods in config")

    def _check_feature_method_compat(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        # Collect what features provide
        provided = set()
        for fc in config.features:
            if fc.name in self.KNOWN_FEATURES:
                provided.update(self.KNOWN_FEATURES[fc.name])

        # Check what enabled methods require
        for name, mc in config.methods:
            if not mc.enabled:
                continue
            if name in self.KNOWN_METHOD_REQUIRES:
                for req in self.KNOWN_METHOD_REQUIRES[name]:
                    if req not in provided:
                        errors.append(
                            f"Method '{name}' requires '{req}' but no feature provides it. "
                            f"Available: {sorted(provided)}"
                        )

    def _check_atr_fractions(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        for name, val in [
            ("trend_atr_fraction", config.trend_atr_fraction),
            ("spread_atr_fraction", config.spread_atr_fraction),
            ("momentum_atr_fraction", config.momentum_atr_fraction),
            ("neutral_slope_atr_fraction", config.neutral_slope_atr_fraction),
        ]:
            if not (0.0 < val < 1.0):
                errors.append(f"{name} ({val}) must be in (0.0, 1.0)")

    def _check_ensemble(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        if not config.ensemble.name:
            errors.append("Ensemble plugin name is empty")

    def _check_feature_ordering(self, config: ResolvedPipelineConfig, errors: List[str]) -> None:
        feature_names = [fc.name for fc in config.features]
        if "volume_weighted" in feature_names and "log_price" in feature_names:
            v_idx = feature_names.index("volume_weighted")
            l_idx = feature_names.index("log_price")
            if v_idx < l_idx:
                errors.append("'log_price' must appear before 'volume_weighted' in features stack")
