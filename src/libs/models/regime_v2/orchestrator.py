"""RegimeV2 orchestrator.

The orchestrator coordinates deterministic feature kernels, rule fusion, and
playbook policy derivation.  It is intentionally independent from the legacy
``libs.regime`` package so old and new regimes can be compared side-by-side.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.models.regime_v2.config import RegimeV2Config, timeframe_scaled_config
from libs.models.regime_v2.contracts import DataQualityReport, RegimeEvidence, RegimePolicy, RegimeV2Output
from libs.models.regime_v2.data_quality import build_row_quality_flags, prepare_ohlcv, validate_ohlcv
from libs.models.regime_v2.features import (
    compute_break_features,
    compute_market_context_features,
    compute_mean_reversion_features,
    compute_trend_features,
    compute_volatility_features,
)
from libs.models.regime_v2.fusion import build_evidence_frame, row_to_evidence
from libs.models.regime_v2.policy import build_policy_frame, evidence_to_policy


class RegimeV2Orchestrator:
    """Main entry point for RegimeV2 phase 1."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config: RegimeV2Config | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.config = config or timeframe_scaled_config(timeframe)

    @classmethod
    def create(
        cls,
        asset: str,
        timeframe: str,
        **overrides: Any,
    ) -> "RegimeV2Orchestrator":
        """Construct with timeframe-scaled defaults and dotted-key overrides."""
        return cls(asset, timeframe, config=timeframe_scaled_config(timeframe, overrides))

    def analyze_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """Analyze a historical OHLCV frame.

        Returns a dataframe with evidence columns plus ``policy_*`` columns.  The
        final row is designed to be equivalent to ``analyze(df)``.
        """
        quality = validate_ohlcv(df, self.config.data_quality)
        if quality.rows == 0 or quality.missing_required_fields:
            return self._neutral_series(df.index if len(df) else pd.RangeIndex(1), quality)

        prepared = prepare_ohlcv(df, self.config.data_quality.required_fields)
        row_quality = build_row_quality_flags(prepared, self.config.data_quality)
        feature_frame = self._compute_feature_frame(prepared)
        evidence_df = build_evidence_frame(
            feature_frame,
            asset=self.asset,
            timeframe=self.timeframe,
            config=self.config.fusion,
            warmup_complete=True,
        )
        evidence_df = self._apply_row_quality(evidence_df, row_quality=row_quality)

        policy_df = build_policy_frame(evidence_df, self.config.policy).add_prefix("policy_")
        return evidence_df.join(policy_df)

    def analyze(self, df: pd.DataFrame) -> RegimeV2Output:
        """Analyze the latest available bar and return rich contracts."""
        quality = validate_ohlcv(df, self.config.data_quality)
        if quality.rows == 0 or quality.missing_required_fields:
            return self._neutral_output(_last_timestamp(df), quality)

        series = self.analyze_series(df)
        if series.empty:
            return self._neutral_output(_last_timestamp(df), quality)
        last = series.iloc[-1]
        evidence = row_to_evidence(last, asset=self.asset, timeframe=self.timeframe)
        policy = evidence_to_policy(evidence, self.config.policy)
        diagnostics = self._diagnostics(last, quality)
        return RegimeV2Output(
            evidence=evidence,
            policy=policy,
            data_quality=quality,
            diagnostics=diagnostics,
        )

    def _compute_feature_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        parts = [
            compute_trend_features(df, self.config.trend),
            compute_volatility_features(df, self.config.volatility),
            compute_mean_reversion_features(df, self.config.mean_reversion),
            compute_break_features(df, self.config.breaks),
            compute_market_context_features(df, self.config.market_context),
        ]
        return pd.concat(parts, axis=1)

    def _degrade_evidence(self, evidence_df: pd.DataFrame, quality: DataQualityReport) -> pd.DataFrame:
        out = evidence_df.copy()
        out["confidence"] = (out["confidence"] * 0.25).clip(0.0, 1.0)
        out["uncertainty"] = 1.0
        out["summary_label"] = "data_quality_degraded"
        if not quality.warmup_complete:
            out["summary_label"] = "warming_up"
        return out

    def _apply_row_quality(self, evidence_df: pd.DataFrame, *, row_quality: pd.DataFrame) -> pd.DataFrame:
        out = evidence_df.copy()
        if out.empty or row_quality.empty:
            return out

        warmup_complete = row_quality["warmup_complete"].reindex(out.index).fillna(False).astype(bool)
        usable = row_quality["usable"].reindex(out.index).fillna(False).astype(bool)

        degraded = ~usable
        if degraded.any():
            out.loc[degraded, "confidence"] = (
                out.loc[degraded, "confidence"].astype(float) * 0.25
            ).clip(0.0, 1.0)
            out.loc[degraded, "uncertainty"] = 1.0
            out.loc[degraded, "summary_label"] = "data_quality_degraded"

        warming = ~warmup_complete
        if warming.any():
            out.loc[warming, "confidence"] = (
                out.loc[warming, "confidence"].astype(float) * 0.25
            ).clip(0.0, 1.0)
            out.loc[warming, "uncertainty"] = 1.0
            out.loc[warming, "summary_label"] = "warming_up"

        return out

    def _neutral_series(self, index: pd.Index, quality: DataQualityReport) -> pd.DataFrame:
        if len(index) == 0:
            index = pd.RangeIndex(1)
        rows = []
        for ts in index:
            evidence = self._neutral_evidence(ts, quality)
            policy = evidence_to_policy(evidence, self.config.policy)
            rows.append({**evidence.to_dict(), **{f"policy_{k}": v for k, v in policy.to_dict().items()}})
        return pd.DataFrame(rows, index=index)

    def _neutral_output(self, timestamp: Any, quality: DataQualityReport) -> RegimeV2Output:
        evidence = self._neutral_evidence(timestamp, quality)
        policy = evidence_to_policy(evidence, self.config.policy)
        return RegimeV2Output(
            evidence=evidence,
            policy=policy,
            data_quality=quality,
            diagnostics={"reason": "neutral_output", "quality_reasons": list(quality.reasons)},
        )

    def _neutral_evidence(self, timestamp: Any, quality: DataQualityReport) -> RegimeEvidence:
        label = "warming_up" if not quality.warmup_complete else "unusable_data"
        return RegimeEvidence(
            timestamp=timestamp,
            asset=self.asset,
            timeframe=self.timeframe,
            trend_direction="neutral",
            trend_strength=0.0,
            trend_persistence=0.0,
            trend_confidence=0.0,
            volatility_percentile=50.0,
            volatility_state="normal",
            compression_score=0.0,
            shock_risk=0.0,
            mean_reversion_score=0.0,
            range_quality=0.0,
            chop_risk=0.0,
            structural_break_risk=0.0,
            breakout_quality=0.0,
            false_breakout_risk=0.0,
            market_context_score=0.0,
            breadth_confirmation=0.0,
            liquidity_stress=0.0,
            confidence=0.0,
            uncertainty=1.0,
            summary_label=label,
        )

    @staticmethod
    def _diagnostics(row: pd.Series, quality: DataQualityReport) -> dict[str, Any]:
        return {
            "data_quality_usable": quality.usable,
            "data_quality_reasons": list(quality.reasons),
            "trend_direction_score": float(row.get("trend_direction_score", 0.0)),
            "volatility_state": str(row.get("volatility_state", "normal")),
            "policy_no_trade_reason": row.get("policy_no_trade_reason"),
        }


def _last_timestamp(df: pd.DataFrame) -> Any:
    if len(df.index):
        return df.index[-1]
    return None


__all__ = ["RegimeV2Orchestrator"]
