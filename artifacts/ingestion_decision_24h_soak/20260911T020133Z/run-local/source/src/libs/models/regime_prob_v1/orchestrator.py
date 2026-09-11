"""Runtime orchestrator for RegimeProbV1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.config import (
    RegimeProbFeatureFrameConfig,
    RegimeProbRuntimeConfig,
)
from libs.models.regime_prob_v1.context import ExternalContextConfig
from libs.models.regime_prob_v1.contracts import ProbabilisticRegimeOutput
from libs.models.regime_prob_v1.edge import EmpiricalCalibratorModel, PlaybookCalibrationResult, playbook_score_column
from libs.models.regime_prob_v1.feature_builder import RegimeProbFeatureBuilder
from libs.models.regime_prob_v1.kernels import BCPDAdapterConfig, HurstAdapterConfig
from libs.models.regime_prob_v1.moe import (
    PLAYBOOKS,
    MoERouterConfig,
    build_moe_router_frame,
    playbook_probability_column,
    playbook_weight_column,
)
from libs.models.regime_prob_v1.mtf import (
    MTFAlignConfig,
    MTFFusionConfig,
    align_mtf_probability_frames,
    build_mtf_context_frame,
    build_mtf_fused_weight_frame,
)
from libs.models.regime_prob_v1.overlays import (
    ProbabilityOverlayConfig,
    ProbabilityOverlayFrame,
    build_probability_overlay,
    build_state_proxy_frame,
)
from libs.models.regime_prob_v1.state import HMMStateModel, HMMStateModelConfig

CalibrationLike = EmpiricalCalibratorModel | PlaybookCalibrationResult
_EXTERNAL_CONTEXT_COLUMNS = (
    "external_context_available",
    "external_context_coverage_ratio",
    "external_context_staleness_bars",
    "market_alignment_score",
    "alt_market_alignment",
    "btc_d_conflict_score",
    "total3_confirmation",
    "asset_vs_total3_divergence",
    "asset_vs_btc_divergence",
)
_STATE_SOURCE = "deterministic_proxy"
_STATE_SOURCE_NOTE = (
    "Proxy state probabilities are derived from deterministic RegimeV2 evidence; "
    "they are not a true HMM posterior. RegimeProbV1 remains shadow/research only."
)
_STATE_SOURCE_HMM = "hmm_state_model"
_STATE_SOURCE_HMM_NOTE = (
    "Semantic state probabilities are produced from an HMM latent-state model "
    "mapped onto RegimeProbV1 regime labels. This remains shadow/research only."
)
_STATE_SOURCE_PROXY_FALLBACK = "deterministic_proxy_fallback"
_STATE_SOURCE_PROXY_FALLBACK_NOTE = (
    "The optional HMM state model was requested but safely fell back to the "
    "deterministic RegimeV2 proxy because the HMM path was not ready."
)
_MTF_CONTEXT_COLUMNS = (
    "mtf_trend_confirmation",
    "mtf_breakout_confirmation",
    "mtf_mr_confirmation",
    "mtf_conflict_score",
    "mtf_entropy_max",
    "mtf_transition_max",
)


@dataclass(frozen=True)
class RegimeProbOrchestratorConfig:
    """Runtime configuration for one RegimeProbV1 orchestrator.

    The default mode is `shadow` and `can_force_trade` must remain `False`
    while the default state source is `deterministic_proxy`. An optional HMM
    state model may be enabled explicitly for shadow/research use.
    """

    horizon: int = 3
    feature_config: RegimeProbFeatureFrameConfig = field(default_factory=RegimeProbFeatureFrameConfig)
    runtime: RegimeProbRuntimeConfig = field(default_factory=RegimeProbRuntimeConfig)
    state_model_config: HMMStateModelConfig | None = None
    router_config: MoERouterConfig = field(default_factory=MoERouterConfig)
    overlay_config: ProbabilityOverlayConfig = field(default_factory=ProbabilityOverlayConfig)
    external_context_config: ExternalContextConfig | None = None
    mtf_align_config: MTFAlignConfig = field(default_factory=MTFAlignConfig)
    mtf_fusion_config: MTFFusionConfig = field(default_factory=MTFFusionConfig)


class RegimeProbV1Orchestrator:
    """Compose feature building, calibrated edge heads, router, and optional MTF fusion."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config: RegimeProbOrchestratorConfig | None = None,
        regime_v2_overrides: dict[str, Any] | None = None,
        bcpd_config: BCPDAdapterConfig | None = None,
        hurst_config: HurstAdapterConfig | None = None,
        calibrators: Mapping[str, CalibrationLike] | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.config = config or RegimeProbOrchestratorConfig()
        self.regime_v2_overrides = dict(regime_v2_overrides or {})
        self.bcpd_config = bcpd_config
        self.hurst_config = hurst_config
        self.calibrators = _normalize_calibrators(calibrators)
        self.last_diagnostics: dict[str, Any] = {}

    @classmethod
    def create(
        cls,
        asset: str,
        timeframe: str,
        **kwargs: Any,
    ) -> "RegimeProbV1Orchestrator":
        """Construct a runtime orchestrator for one asset/timeframe."""
        return cls(asset, timeframe, **kwargs)

    def analyze_series(
        self,
        df: pd.DataFrame,
        *,
        external_context_frames: Mapping[str, pd.DataFrame] | None = None,
        higher_timeframe_probability_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """Return a full probability-enriched frame for one OHLCV history.

        The default state source is `deterministic_proxy`. If an HMM state
        model is configured, `diagnostics_state_source` will reflect whether the
        HMM path was active or safely fell back to the deterministic proxy.
        """
        feature_frame = self._build_feature_frame(df, external_context_frames=external_context_frames)
        if feature_frame.empty:
            self.last_diagnostics = {"status": "empty_feature_frame"}
            return feature_frame

        edge_frame = self._build_edge_probability_frame(feature_frame)
        probability_input = feature_frame.join(edge_frame, how="left")
        state_frame, state_diag, state_source, state_source_note = self._build_state_frame(feature_frame)
        overlay = build_probability_overlay(
            probability_input,
            horizon=self.config.horizon,
            config=self.config.overlay_config,
            state_frame=state_frame,
            use_state_support=True,
            use_transition_gate=True,
            use_external_context=True,
        )
        router_input = probability_input.join(state_frame, how="left")
        for playbook in PLAYBOOKS:
            router_input[playbook_probability_column(playbook, self.config.horizon)] = overlay.adjusted_probabilities[playbook]
        router_base = build_moe_router_frame(
            router_input,
            horizon=self.config.horizon,
            config=self.config.router_config,
        ).rename(columns=_router_base_columns())
        output = probability_input.join(state_frame, how="left")
        output = output.join(_overlay_projection_frame(overlay, horizon=self.config.horizon), how="left")
        output = output.join(router_base, how="left")

        mtf_context_frame = pd.DataFrame(index=output.index)
        if higher_timeframe_probability_frames:
            aligned = align_mtf_probability_frames(
                output.index,
                higher_timeframe_probability_frames,
                base_timeframe=self.timeframe,
                config=self.config.mtf_align_config,
            )
            if not aligned.empty:
                mtf_context_frame = build_mtf_context_frame(
                    aligned,
                    higher_timeframes=tuple(higher_timeframe_probability_frames.keys()),
                    horizon=self.config.horizon,
                )
                output = output.join(aligned, how="left").join(mtf_context_frame, how="left")

        final_weights = self._build_final_weight_frame(output, mtf_context_frame=mtf_context_frame)
        output = output.join(final_weights, how="left")
        output["recommended_playbook"] = output["recommended_playbook"].astype(object)
        output["diagnostics_state_source"] = state_source
        output["diagnostics_state_source_note"] = state_source_note
        self.last_diagnostics = self._build_diagnostics(
            feature_frame=feature_frame,
            overlay=overlay,
            state_diagnostics=state_diag,
            state_source=state_source,
            state_source_note=state_source_note,
            external_context_frames=external_context_frames,
            higher_timeframe_probability_frames=higher_timeframe_probability_frames,
            mtf_context_frame=mtf_context_frame,
        )
        return output

    def analyze(
        self,
        df: pd.DataFrame,
        *,
        external_context_frames: Mapping[str, pd.DataFrame] | None = None,
        higher_timeframe_probability_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> ProbabilisticRegimeOutput:
        """Analyze the latest bar and return a runtime contract."""
        frame = self.analyze_series(
            df,
            external_context_frames=external_context_frames,
            higher_timeframe_probability_frames=higher_timeframe_probability_frames,
        )
        if frame.empty:
            return self._neutral_output(timestamp=df.index[-1] if len(df.index) else None)
        row = frame.iloc[-1]
        return ProbabilisticRegimeOutput(
            timestamp=row.name,
            asset=self.asset,
            timeframe=self.timeframe,
            p_trend_state=float(row.get("p_trend_state", 0.0)),
            p_range_state=float(row.get("p_range_state", 0.0)),
            p_chop_state=float(row.get("p_chop_state", 0.0)),
            p_breakout_state=float(row.get("p_breakout_state", 0.0)),
            p_vol_shock_state=float(row.get("p_vol_shock_state", 0.0)),
            p_transition_state=float(row.get("p_transition_state", 0.0)),
            state_entropy=float(row.get("state_entropy", 1.0)),
            dominant_state=str(row.get("dominant_state", "transition")),
            dominant_state_prob=float(row.get("dominant_state_prob", 0.0)),
            p_trend_following_edge=float(row.get("p_trend_following_edge", 0.0)),
            p_breakout_edge=float(row.get("p_breakout_edge", 0.0)),
            p_mean_reversion_edge=float(row.get("p_mean_reversion_edge", 0.0)),
            p_scalping_edge=float(row.get("p_scalping_edge", 0.0)),
            p_countertrend_edge=float(row.get("p_countertrend_edge", 0.0)),
            moe_weights={
                playbook: float(row.get(playbook_weight_column(playbook), 0.0))
                for playbook in PLAYBOOKS
            },
            recommended_playbook=_as_optional_string(row.get("recommended_playbook")),
            mtf_context=_context_dict(row, _MTF_CONTEXT_COLUMNS),
            external_context=_context_dict(row, _EXTERNAL_CONTEXT_COLUMNS),
            diagnostics=dict(self.last_diagnostics),
        )

    def _build_feature_frame(
        self,
        df: pd.DataFrame,
        *,
        external_context_frames: Mapping[str, pd.DataFrame] | None,
    ) -> pd.DataFrame:
        config = self.config.feature_config
        if external_context_frames and not config.include_external_context:
            config = replace(config, include_external_context=True)
        builder = RegimeProbFeatureBuilder(
            asset=self.asset,
            timeframe=self.timeframe,
            config=config,
            regime_v2_overrides=self.regime_v2_overrides,
            bcpd_config=self.bcpd_config,
            hurst_config=self.hurst_config,
            external_context_config=self.config.external_context_config,
        )
        feature_frame = builder.build(df, external_context_frames=external_context_frames)
        self.last_diagnostics = {"feature_builder": dict(builder.last_diagnostics)}
        return feature_frame

    def _build_edge_probability_frame(self, feature_frame: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=feature_frame.index)
        usable = feature_frame.get("row_quality_usable")
        usable_mask = usable.fillna(False).astype(bool) if usable is not None else pd.Series(True, index=feature_frame.index)
        for playbook in PLAYBOOKS:
            model = self.calibrators.get(playbook)
            score_col = playbook_score_column(playbook)
            score = pd.to_numeric(feature_frame.get(score_col), errors="coerce").fillna(0.0)
            if model is None:
                probs = np.zeros(len(feature_frame), dtype=float)
            else:
                probs = np.asarray(model.predict_proba(score), dtype=float)
            series = pd.Series(np.clip(np.nan_to_num(probs, nan=0.0), 0.0, 1.0), index=feature_frame.index)
            series = series.where(usable_mask, 0.0)
            out[f"p_{playbook}_edge"] = series.astype(float)
            out[playbook_probability_column(playbook, self.config.horizon)] = series.astype(float)
        return out

    def _build_state_frame(
        self,
        feature_frame: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, Any], str, str]:
        if self.config.state_model_config is None:
            return (
                build_state_proxy_frame(feature_frame),
                {"status": "proxy_default", "ready": False},
                _STATE_SOURCE,
                _STATE_SOURCE_NOTE,
            )
        result = HMMStateModel(self.config.state_model_config).analyze(feature_frame)
        if result.state_source == _STATE_SOURCE_HMM:
            return result.frame, dict(result.diagnostics), _STATE_SOURCE_HMM, _STATE_SOURCE_HMM_NOTE
        if result.state_source == _STATE_SOURCE_PROXY_FALLBACK:
            return (
                result.frame,
                dict(result.diagnostics),
                _STATE_SOURCE_PROXY_FALLBACK,
                _STATE_SOURCE_PROXY_FALLBACK_NOTE,
            )
        return result.frame, dict(result.diagnostics), result.state_source, result.state_source_note

    def _build_final_weight_frame(
        self,
        output: pd.DataFrame,
        *,
        mtf_context_frame: pd.DataFrame,
    ) -> pd.DataFrame:
        if mtf_context_frame.empty:
            return _base_weight_projection(output)

        base_router = pd.DataFrame(index=output.index)
        for playbook in PLAYBOOKS:
            base_router[playbook_weight_column(playbook)] = pd.to_numeric(
                output.get(f"base_{playbook_weight_column(playbook)}"),
                errors="coerce",
            ).fillna(0.0)
        fused = build_mtf_fused_weight_frame(
            base_router,
            mtf_context_frame,
            config=self.config.mtf_fusion_config,
        )
        final = pd.DataFrame(index=output.index)
        for playbook in PLAYBOOKS:
            final[playbook_weight_column(playbook)] = pd.to_numeric(
                fused.get(f"mtf_{playbook_weight_column(playbook)}"),
                errors="coerce",
            ).fillna(0.0)
        final["recommended_playbook"] = fused.get("mtf_recommended_playbook")
        return final

    def _build_diagnostics(
        self,
        *,
        feature_frame: pd.DataFrame,
        overlay: ProbabilityOverlayFrame,
        state_diagnostics: dict[str, Any],
        state_source: str,
        state_source_note: str,
        external_context_frames: Mapping[str, pd.DataFrame] | None,
        higher_timeframe_probability_frames: Mapping[str, pd.DataFrame] | None,
        mtf_context_frame: pd.DataFrame,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "state_source": state_source,
            "state_source_note": state_source_note,
            "horizon": int(self.config.horizon),
            "runtime": asdict(self.config.runtime),
            "missing_calibrators": sorted(playbook for playbook in PLAYBOOKS if playbook not in self.calibrators),
            "available_calibrators": sorted(self.calibrators.keys()),
            "feature_builder": dict(self.last_diagnostics.get("feature_builder") or {}),
            "state_model": dict(state_diagnostics),
            "router_config": asdict(self.config.router_config),
            "overlay_config": asdict(self.config.overlay_config),
            "overlay_gate_active_rate": float(overlay.gate_active.mean()) if len(overlay.gate_active) else 0.0,
            "overlay_transition_risk_mean": float(overlay.transition_risk.mean()) if len(overlay.transition_risk) else 0.0,
            "external_context_enabled": bool(external_context_frames),
            "external_context_sources": sorted((external_context_frames or {}).keys()),
            "higher_timeframes": sorted((higher_timeframe_probability_frames or {}).keys()),
            "mtf_enabled": not mtf_context_frame.empty,
            "rows": int(len(feature_frame)),
            "research_only": True,
        }

    def _neutral_output(self, *, timestamp: Any) -> ProbabilisticRegimeOutput:
        state_source = _STATE_SOURCE if self.config.state_model_config is None else _STATE_SOURCE_PROXY_FALLBACK
        state_source_note = _STATE_SOURCE_NOTE if self.config.state_model_config is None else _STATE_SOURCE_PROXY_FALLBACK_NOTE
        diagnostics = {
            "status": "neutral_output",
            "state_source": state_source,
            "state_source_note": state_source_note,
            "runtime": asdict(self.config.runtime),
            "missing_calibrators": sorted(PLAYBOOKS),
            "research_only": True,
        }
        return ProbabilisticRegimeOutput(
            timestamp=timestamp,
            asset=self.asset,
            timeframe=self.timeframe,
            p_trend_state=1.0 / 6.0,
            p_range_state=1.0 / 6.0,
            p_chop_state=1.0 / 6.0,
            p_breakout_state=1.0 / 6.0,
            p_vol_shock_state=1.0 / 6.0,
            p_transition_state=1.0 / 6.0,
            state_entropy=1.0,
            dominant_state="transition",
            dominant_state_prob=1.0 / 6.0,
            p_trend_following_edge=0.0,
            p_breakout_edge=0.0,
            p_mean_reversion_edge=0.0,
            p_scalping_edge=0.0,
            p_countertrend_edge=0.0,
            moe_weights={playbook: 0.0 for playbook in PLAYBOOKS},
            recommended_playbook=None,
            mtf_context={},
            external_context={},
            diagnostics=diagnostics,
        )


def _normalize_calibrators(
    calibrators: Mapping[str, CalibrationLike] | None,
) -> dict[str, EmpiricalCalibratorModel]:
    out: dict[str, EmpiricalCalibratorModel] = {}
    for key, value in (calibrators or {}).items():
        playbook = str(key).strip().lower()
        if playbook not in PLAYBOOKS:
            continue
        if isinstance(value, PlaybookCalibrationResult):
            out[playbook] = value.model
        elif isinstance(value, EmpiricalCalibratorModel):
            out[playbook] = value
    return out


def _router_base_columns() -> dict[str, str]:
    columns = {"recommended_playbook": "base_recommended_playbook"}
    for playbook in PLAYBOOKS:
        columns[playbook_weight_column(playbook)] = f"base_{playbook_weight_column(playbook)}"
    return columns


def _base_weight_projection(output: pd.DataFrame) -> pd.DataFrame:
    projected = pd.DataFrame(index=output.index)
    for playbook in PLAYBOOKS:
        projected[playbook_weight_column(playbook)] = pd.to_numeric(
            output.get(f"base_{playbook_weight_column(playbook)}"),
            errors="coerce",
        ).fillna(0.0)
    projected["recommended_playbook"] = output.get("base_recommended_playbook")
    return projected


def _overlay_projection_frame(overlay: ProbabilityOverlayFrame, *, horizon: int) -> pd.DataFrame:
    projected = pd.DataFrame(index=overlay.adjusted_probabilities.index)
    for playbook in PLAYBOOKS:
        projected[f"overlay_{playbook_probability_column(playbook, horizon)}"] = overlay.adjusted_probabilities[playbook]
    projected["overlay_transition_risk"] = pd.to_numeric(overlay.transition_risk, errors="coerce").fillna(0.0)
    projected["overlay_gate_active"] = overlay.gate_active.astype(bool)
    return projected


def _context_dict(row: pd.Series, columns: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in columns:
        value = row.get(column)
        if pd.isna(value):
            out[column] = None
        elif isinstance(value, (np.bool_, bool)):
            out[column] = bool(value)
        elif isinstance(value, (np.floating, float)):
            out[column] = float(value)
        else:
            out[column] = value
    return out


def _as_optional_string(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "RegimeProbOrchestratorConfig",
    "RegimeProbV1Orchestrator",
]
