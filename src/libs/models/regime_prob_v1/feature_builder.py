"""Point-in-time feature frame builder for RegimeProbV1."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.config import RegimeProbFeatureFrameConfig
from libs.models.regime_prob_v1.context import (
    ExternalContextConfig,
    build_external_context_features,
)
from libs.models.regime_prob_v1.kernels import (
    BCPDAdapterConfig,
    HurstAdapterConfig,
    compute_bcpd_features,
    compute_hurst_features,
)
from libs.models.regime_v2 import RegimeV2Orchestrator
from libs.models.regime_v2.data_quality import (
    build_row_quality_flags,
    prepare_ohlcv,
    validate_ohlcv,
)
from libs.models.regime_v2.features import compute_break_features

_CORE_EVIDENCE_COLUMNS = ("asset", "timeframe")
_RAW_BREAK_COLUMNS = ("breakout_direction", "range_expansion_z", "volume_confirmation")
_DEFAULT_ROW_QUALITY_COLUMNS = ("row_quality_warmup_complete", "row_quality_usable")
_RESERVED_FEATURE_FLAGS = (
    "include_hilbert",
    "include_regime_classification",
    "include_trendlines",
    "include_mtf",
)


class RegimeProbFeatureBuilder:
    """Build a point-in-time feature frame from deterministic RegimeV2 outputs.

    This builder is intentionally PIT-only. It must not create forward returns,
    labels, or any column that depends on unseen future bars.
    """

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config: RegimeProbFeatureFrameConfig | None = None,
        regime_v2_overrides: dict[str, Any] | None = None,
        bcpd_config: BCPDAdapterConfig | None = None,
        hurst_config: HurstAdapterConfig | None = None,
        external_context_config: ExternalContextConfig | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.config = config or RegimeProbFeatureFrameConfig()
        self.regime_v2_overrides = dict(regime_v2_overrides or {})
        self.bcpd_config = bcpd_config
        self.hurst_config = hurst_config
        self.external_context_config = external_context_config
        self.last_diagnostics: dict[str, dict[str, Any]] = {}
        self.regime_v2 = RegimeV2Orchestrator.create(
            self.asset,
            self.timeframe,
            **self.regime_v2_overrides,
        )

    @classmethod
    def create(
        cls,
        asset: str,
        timeframe: str,
        **kwargs: Any,
    ) -> "RegimeProbFeatureBuilder":
        """Construct a feature builder with optional config overrides."""
        return cls(asset, timeframe, **kwargs)

    def build(
        self,
        df: pd.DataFrame,
        *,
        external_context_frames: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """Return a point-in-time feature frame aligned to the usable history."""
        if df.empty:
            self.last_diagnostics = {}
            return pd.DataFrame(index=df.index.copy())

        base = self.regime_v2.analyze_series(df)
        if base.empty:
            self.last_diagnostics = {}
            return base

        quality, prepared = self._prepared_ohlcv(df)
        self.last_diagnostics = {}
        reserved_flags = [name for name in _RESERVED_FEATURE_FLAGS if bool(getattr(self.config, name, False))]
        if reserved_flags:
            self.last_diagnostics["reserved_feature_flags"] = {
                "status": "reserved_noop",
                "requested": tuple(sorted(reserved_flags)),
            }
        feature_frame = self._select_base_columns(base)
        feature_frame = feature_frame.join(
            self._row_quality_frame(quality, prepared, feature_frame.index),
            how="left",
        )
        if self.config.include_raw_break_features:
            feature_frame = feature_frame.join(
                self._raw_break_frame(quality, prepared, feature_frame.index),
                how="left",
            )
        if self.config.include_bcpd:
            bcpd = compute_bcpd_features(
                prepared if prepared is not None else df,
                timeframe=self.timeframe,
                config=self.bcpd_config,
            )
            self.last_diagnostics["bcpd"] = dict(bcpd.diagnostics)
            feature_frame = feature_frame.join(bcpd.frame.reindex(feature_frame.index), how="left")
        if self.config.include_hurst:
            hurst = compute_hurst_features(
                prepared if prepared is not None else df,
                timeframe=self.timeframe,
                config=self.hurst_config,
            )
            self.last_diagnostics["hurst"] = dict(hurst.diagnostics)
            feature_frame = feature_frame.join(hurst.frame.reindex(feature_frame.index), how="left")
        if self.config.include_external_context:
            context = build_external_context_features(
                prepared if prepared is not None else df,
                asset=self.asset,
                timeframe=self.timeframe,
                external_context_frames=external_context_frames,
                config=self.external_context_config,
                breakout_direction=feature_frame.get("breakout_direction"),
            )
            self.last_diagnostics["external_context"] = dict(context.diagnostics)
            feature_frame = feature_frame.join(context.frame.reindex(feature_frame.index), how="left")
        return feature_frame

    def _prepared_ohlcv(self, df: pd.DataFrame) -> tuple[Any, pd.DataFrame | None]:
        quality = validate_ohlcv(df, self.regime_v2.config.data_quality)
        if quality.rows == 0 or quality.missing_required_fields:
            return quality, None
        prepared = prepare_ohlcv(df, self.regime_v2.config.data_quality.required_fields)
        return quality, prepared

    def _select_base_columns(self, base: pd.DataFrame) -> pd.DataFrame:
        columns: list[str] = [column for column in _CORE_EVIDENCE_COLUMNS if column in base.columns]
        evidence_columns = [
            column
            for column in base.columns
            if not column.startswith("policy_") and column not in _CORE_EVIDENCE_COLUMNS
        ]
        policy_columns = [column for column in base.columns if column.startswith("policy_")]
        if self.config.include_regime_v2_evidence:
            columns.extend(evidence_columns)
        if self.config.include_policy_scores:
            columns.extend(policy_columns)
        return base.loc[:, columns].copy()

    def _row_quality_frame(
        self,
        quality: Any,
        prepared: pd.DataFrame | None,
        target_index: pd.Index,
    ) -> pd.DataFrame:
        defaults = pd.DataFrame(
            {column: False for column in _DEFAULT_ROW_QUALITY_COLUMNS},
            index=target_index,
        )
        if quality.rows == 0 or quality.missing_required_fields or prepared is None:
            return defaults

        flags = build_row_quality_flags(prepared, self.regime_v2.config.data_quality).rename(
            columns={
                "warmup_complete": "row_quality_warmup_complete",
                "usable": "row_quality_usable",
            }
        )
        return flags.reindex(target_index).fillna(False).astype(bool)

    def _raw_break_frame(
        self,
        quality: Any,
        prepared: pd.DataFrame | None,
        target_index: pd.Index,
    ) -> pd.DataFrame:
        defaults = pd.DataFrame(
            {
                "breakout_direction": "none",
                "range_expansion_z": np.nan,
                "volume_confirmation": np.nan,
            },
            index=target_index,
        )
        if quality.rows == 0 or quality.missing_required_fields or prepared is None:
            return defaults

        # RegimeV2 intentionally drops raw breakout direction from the stable
        # evidence contract. RegimeProbV1 needs that PIT field for later labels.
        raw_break = compute_break_features(prepared, self.regime_v2.config.breaks)
        return raw_break.loc[:, list(_RAW_BREAK_COLUMNS)].reindex(target_index)


def build_regime_prob_feature_frame(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: RegimeProbFeatureFrameConfig | None = None,
    regime_v2_overrides: dict[str, Any] | None = None,
    bcpd_config: BCPDAdapterConfig | None = None,
    hurst_config: HurstAdapterConfig | None = None,
    external_context_frames: dict[str, pd.DataFrame] | None = None,
    external_context_config: ExternalContextConfig | None = None,
) -> pd.DataFrame:
    """Convenience wrapper around :class:`RegimeProbFeatureBuilder`."""
    builder = RegimeProbFeatureBuilder(
        asset=asset,
        timeframe=timeframe,
        config=config,
        regime_v2_overrides=regime_v2_overrides,
        bcpd_config=bcpd_config,
        hurst_config=hurst_config,
        external_context_config=external_context_config,
    )
    return builder.build(df, external_context_frames=external_context_frames)


__all__ = [
    "RegimeProbFeatureBuilder",
    "build_regime_prob_feature_frame",
]
