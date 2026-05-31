"""
Regime Config Validator
=======================
Validates per-asset per-timeframe config coverage in regime.yaml.

Checks that all 5 optimizable params are present for each asset/timeframe
pair. Reports gaps so you know which pairs still use default values.

Usage
-----
    from app.regime.config_validator import RegimeConfigValidator

    validator = RegimeConfigValidator()

    # Check a single asset+timeframe
    status = validator.validate("BTCUSDT", "1h")
    print(status.summary())

    # Full coverage report across all configured pairs
    validator.print_report()

Note: Applying optimization results is handled by
      OptimizationResult.apply_to_config() in the optimization module.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger("app.regime")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "app", "regime", "config", "regime.yaml")

REQUIRED_PARAMS = [
    "bcpd_hazard_lambda",
    "bcpd_signal_threshold",
    "vol_high_percentile",
    "vol_lookback",
    "hmm_retrain_window",
    "hurst_lookback",
    "min_dwell_bars",
]


@dataclass
class ConfigStatus:
    """Coverage status for one asset+timeframe pair."""
    asset: str
    timeframe: str
    present: Dict[str, Any] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    using_defaults: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when all 5 params have explicit per-asset values (not defaults)."""
        return len(self.missing) == 0 and len(self.using_defaults) == 0

    @property
    def coverage_pct(self) -> float:
        n_present = len(REQUIRED_PARAMS) - len(self.using_defaults) - len(self.missing)
        return (n_present / len(REQUIRED_PARAMS)) * 100

    def summary(self) -> str:
        icon = "✅" if self.is_complete else ("⚠️" if not self.missing else "❌")
        lines = [
            f"\n{'=' * 60}",
            f"  {icon}  {self.asset} / {self.timeframe}  —  {self.coverage_pct:.0f}% explicit",
            f"{'=' * 60}",
        ]
        if self.present:
            lines.append("  Explicit values:")
            for k, v in self.present.items():
                lines.append(f"    {k}: {v}")
        if self.using_defaults:
            lines.append(f"  Using defaults: {', '.join(self.using_defaults)}")
        if self.missing:
            lines.append(f"  Missing (not in yaml at all): {', '.join(self.missing)}")
        return "\n".join(lines)


class RegimeConfigValidator:
    """
    Reads regime.yaml and reports per-asset per-timeframe param coverage.

    regime.yaml structure:
        defaults:
          hmm_retrain_window: 1000
          vol_lookback: 168
          ...
        assets:
          BTCUSDT:
            1h:
              bcpd_hazard_lambda: 121.76
              ...
    """

    def __init__(self, config_path: Optional[str] = None):
        self._path = config_path or _CONFIG_PATH
        self._config: dict = {}
        self._defaults: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path) as f:
                self._config = yaml.safe_load(f) or {}
            self._defaults = self._config.get("defaults", {})
        except (FileNotFoundError, OSError) as e:
            logger.warning("regime.yaml not found at %s: %s", self._path, e)
            self._config = {}
            self._defaults = {}

    def _get_asset_tf_params(self, asset: str, timeframe: str) -> dict:
        return (
            self._config
            .get("assets", {})
            .get(asset, {})
            .get(timeframe, {})
        ) or {}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, asset: str, timeframe: str) -> ConfigStatus:
        """Validate config coverage for one asset+timeframe pair."""
        explicit = self._get_asset_tf_params(asset, timeframe)
        present = {}
        using_defaults = []
        missing = []

        for param in REQUIRED_PARAMS:
            if param in explicit:
                present[param] = explicit[param]
            elif param in self._defaults:
                using_defaults.append(param)
            else:
                missing.append(param)

        return ConfigStatus(
            asset=asset,
            timeframe=timeframe,
            present=present,
            missing=missing,
            using_defaults=using_defaults,
        )

    def get_all_configured_pairs(self) -> Set[Tuple[str, str]]:
        """All (asset, timeframe) pairs with an entry in the assets section."""
        pairs: Set[Tuple[str, str]] = set()
        for asset, tf_dict in self._config.get("assets", {}).items():
            if isinstance(tf_dict, dict):
                for tf in tf_dict:
                    pairs.add((asset, tf))
        return pairs

    def validate_all(self) -> List[ConfigStatus]:
        """Validate every configured asset+timeframe pair."""
        return [
            self.validate(asset, tf)
            for asset, tf in sorted(self.get_all_configured_pairs())
        ]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def print_report(self, results: Optional[List[ConfigStatus]] = None) -> None:
        """Print a formatted coverage report to stdout."""
        if results is None:
            results = self.validate_all()

        print("\n" + "=" * 60)
        print("  REGIME CONFIG COVERAGE REPORT")
        print(f"  Config: {self._path}")
        print("=" * 60)
        print(f"  Required params: {', '.join(REQUIRED_PARAMS)}")

        if not results:
            print("\n  No asset+timeframe pairs configured.")
            print("=" * 60)
            return

        complete = sum(1 for r in results if r.is_complete)
        partial  = sum(1 for r in results if not r.is_complete and not r.missing)
        gap      = sum(1 for r in results if r.missing)

        print(f"  Pairs: {len(results)}  |  ✅ Full: {complete}  |"
              f"  ⚠️ Defaults: {partial}  |  ❌ Gaps: {gap}")

        for status in results:
            print(status.summary())

        print("\n" + "=" * 60)
