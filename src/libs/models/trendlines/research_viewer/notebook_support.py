"""Thin notebook composition layer for prepared replay and viewer contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Any

from libs.models.trendlines.config.loader import load_trendlines_config
from libs.models.trendlines.workflows.research import (
    PreparedTrendlineResearchReplay,
    PreparedTrendlineResearchRun,
    TrendlineEvidenceSelection,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchEvidenceBundle,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    TrendlineReplayWindow,
    build_research_evidence_bundle,
    prepare_trendline_research,
    run_causal_replay,
    write_research_evidence_bundle,
)
from libs.models.trendlines.data.contracts import TrendlineArtifactRef

from .bundle import write_viewer_bundle
from .contracts import TrendlineViewerContractError, TrendlineViewerSpec
from .payload import build_trendlines_viewer_payload
from .server import TrendlinesResearchViewerSession


DEFAULT_SMOKE_ASSET = "BTCUSDT"
DEFAULT_SMOKE_TIMEFRAMES = ("1h", "4h")
DEFAULT_SMOKE_BAR_COUNT = 48


def default_synthetic_research_spec() -> TrendlineResearchSpec:
    """Return bounded notebook smoke scope with no provider access."""

    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=7,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={timeframe: DEFAULT_SMOKE_BAR_COUNT for timeframe in DEFAULT_SMOKE_TIMEFRAMES},
        ),
        asset=DEFAULT_SMOKE_ASSET,
        timeframes=DEFAULT_SMOKE_TIMEFRAMES,
        primary_timeframe="1h",
    )


def default_replay_spec(prepared: PreparedTrendlineResearchRun) -> TrendlineResearchReplaySpec:
    """Build explicit bounded replay controls from prepared row counts."""

    windows: dict[str, TrendlineReplayWindow] = {}
    for timeframe in prepared.spec.timeframes:
        end = min(DEFAULT_SMOKE_BAR_COUNT - 1, len(prepared.dataset.frames[timeframe]) - 1)
        warmup = min(19, end)
        record_start = min(20, end)
        record_start = max(record_start, warmup)
        windows[timeframe] = TrendlineReplayWindow(
            warmup_start_position=warmup,
            record_start_position=record_start,
            end_position=end,
            record_every=1,
        )
    return TrendlineResearchReplaySpec(windows=windows, include_signals=True)


@dataclass
class TrendlineResearchNotebookSession:
    """Prepared notebook artifacts and owned viewer resources."""

    prepared: PreparedTrendlineResearchRun
    replay: PreparedTrendlineResearchReplay
    evidence_bundle: TrendlineResearchEvidenceBundle
    payload: dict[str, Any]
    viewer_bundle_path: Path
    viewer_session: TrendlinesResearchViewerSession | None
    _owned_directory: Path | None = None

    @property
    def viewer_url(self) -> str | None:
        return self.viewer_session.url if self.viewer_session is not None else None

    def close(self) -> None:
        if self.viewer_session is not None:
            self.viewer_session.close()
            self.viewer_session = None
        if self._owned_directory is not None:
            shutil.rmtree(self._owned_directory, ignore_errors=False)
            self._owned_directory = None

    def __enter__(self) -> "TrendlineResearchNotebookSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


async def run_research_notebook_session(
    spec: TrendlineResearchSpec | None = None,
    *,
    trendlines_config: Any | None = None,
    loader: Any | None = None,
    replay_spec: TrendlineResearchReplaySpec | None = None,
    viewer_spec: TrendlineViewerSpec | None = None,
    provider_calls_authorized: bool = False,
    export_directory: str | Path | None = None,
    evidence_artifact: TrendlineArtifactRef | None = None,
    permanent_export: bool = False,
    start_viewer: bool = True,
) -> TrendlineResearchNotebookSession:
    """Compose L2-A1/L2-A2 APIs and package-local viewer APIs only."""

    if not isinstance(provider_calls_authorized, bool):
        raise TrendlineViewerContractError("provider_calls_authorized must be bool")
    if not isinstance(permanent_export, bool) or not isinstance(start_viewer, bool):
        raise TrendlineViewerContractError("notebook session flags must be bool")
    if export_directory is not None and not permanent_export:
        raise TrendlineViewerContractError(
            "explicit export_directory requires permanent_export=True"
        )
    if spec is None:
        spec = default_synthetic_research_spec()
    if not isinstance(spec, TrendlineResearchSpec):
        raise TypeError("spec must be a TrendlineResearchSpec")
    if spec.data.mode is TrendlineResearchDataMode.BINANCE:
        if spec.purpose is not TrendlineResearchPurpose.RESEARCH:
            raise TrendlineViewerContractError("BINANCE viewer data requires RESEARCH purpose")
        if not provider_calls_authorized:
            raise TrendlineViewerContractError(
                "BINANCE viewer data requires provider_calls_authorized=True"
            )
        if loader is None:
            raise TrendlineViewerContractError(
                "BINANCE viewer data requires an explicit loader"
            )
    elif provider_calls_authorized:
        raise TrendlineViewerContractError(
            "provider authorization is only valid for BINANCE mode"
        )

    resolved_config = trendlines_config or load_trendlines_config()
    prepared = await prepare_trendline_research(
        spec,
        trendlines_config=resolved_config,
        loader=loader,
    )
    resolved_replay_spec = replay_spec or default_replay_spec(prepared)
    replay = run_causal_replay(prepared, resolved_replay_spec)
    resolved_viewer_spec = viewer_spec
    if resolved_viewer_spec is None:
        timeframe = prepared.spec.primary_timeframe
        point = replay.latest(timeframe)
        resolved_viewer_spec = TrendlineViewerSpec(
            timeframe=timeframe,
            position=point.position,
            display_lookback_bars=min(32, point.position + 1),
        )
    selection = TrendlineEvidenceSelection(
        timeframe=resolved_viewer_spec.timeframe,
        position=resolved_viewer_spec.position,
    )
    evidence = build_research_evidence_bundle(
        prepared,
        replay,
        selection=selection,
    )
    if evidence_artifact is not None:
        write_research_evidence_bundle(evidence, evidence_artifact)
    payload = build_trendlines_viewer_payload(
        prepared,
        replay,
        evidence,
        resolved_viewer_spec,
    )

    owned_directory: Path | None = None
    if export_directory is None:
        owned_directory = Path(tempfile.mkdtemp(prefix="trendlines-research-viewer-"))
        bundle_path = owned_directory / "bundle"
    else:
        bundle_path = Path(export_directory)
    write_viewer_bundle(payload, bundle_path)
    session = None
    try:
        if start_viewer:
            session = TrendlinesResearchViewerSession(
                bundle_path,
                cleanup_directory=owned_directory,
            )
            owned_directory = None
    except Exception:
        if owned_directory is not None:
            shutil.rmtree(owned_directory, ignore_errors=True)
        raise
    return TrendlineResearchNotebookSession(
        prepared=prepared,
        replay=replay,
        evidence_bundle=evidence,
        payload=payload,
        viewer_bundle_path=bundle_path,
        viewer_session=session,
        _owned_directory=owned_directory,
    )


__all__ = [
    "DEFAULT_SMOKE_ASSET",
    "DEFAULT_SMOKE_BAR_COUNT",
    "DEFAULT_SMOKE_TIMEFRAMES",
    "TrendlineResearchNotebookSession",
    "default_replay_spec",
    "default_synthetic_research_spec",
    "run_research_notebook_session",
]
