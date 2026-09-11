"""Small composition helpers for the cleared-output SR v2 notebook.

The helper owns source-bound derivation and cache/provider orchestration.  It
does not implement pagination, feature math, lifecycle processing, or viewer
rendering; those remain in their package boundaries.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config.resolver import ResolvedSRV2Config
from ..features.time import grid_for
from ..research_viewer.bundle import iframe_urls, write_viewer_bundle
from ..research_viewer.server import (
    SRV2ResearchViewerSession,
    create_owned_viewer_workspace,
)
from .config import ResearchSourceMode, ResolvedSRV2ResearchNotebookConfig
from .data import (
    BinanceUSDMResearchLoader,
    HistoricalAdapter,
    ResearchDataResult,
    ResearchSourceSetManifest,
    build_research_source_set_manifest,
)
from .replay import SRV2ResearchReplay
from .trace import SRV2ResearchTrace


def source_bounds(
    model_config: ResolvedSRV2Config,
    research_config: ResolvedSRV2ResearchNotebookConfig,
) -> Mapping[str, tuple[datetime, datetime]]:
    """Derive exact per-timeframe cache bounds from one trigger-grid preflight."""

    replay = SRV2ResearchReplay(model_config, research_config)
    replay.preflight_replay_steps()
    reconstruction_start = research_config.analysis_start - model_config.expiry
    requirements = dict(model_config.history_requirements())
    return {
        timeframe: (
            grid_for(timeframe).expected_closed_cutoff(reconstruction_start)
            - grid_for(timeframe).duration * requirements[timeframe],
            grid_for(timeframe).expected_closed_cutoff(research_config.knowledge_cutoff),
        )
        for timeframe in model_config.ladder
    }


async def load_configured_sources(
    model_config: ResolvedSRV2Config,
    research_config: ResolvedSRV2ResearchNotebookConfig,
    *,
    adapter: HistoricalAdapter | None = None,
    allow_provider_fetch: bool = False,
    bounds: Mapping[str, tuple[datetime, datetime]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Mapping[str, ResearchDataResult]:
    """Load every configured timeframe, defaulting to zero-call cache-only mode."""

    resolved_bounds = source_bounds(model_config, research_config) if bounds is None else bounds
    provider_enabled = allow_provider_fetch is True
    if research_config.source_mode == ResearchSourceMode.BINANCE_USDM and not provider_enabled:
        raise PermissionError(
            "research.source_mode=BINANCE_USDM requires explicit provider authorization"
        )
    if provider_enabled and research_config.source_mode != ResearchSourceMode.BINANCE_USDM:
        raise ValueError("provider fetch requires research.source_mode=BINANCE_USDM")
    if provider_enabled and adapter is None:
        raise ValueError("provider fetch requires an injected historical adapter")
    mode = research_config.source_mode
    loader = BinanceUSDMResearchLoader(
        adapter,
        cache_root=research_config.cache_root,
        venue=research_config.venue,
        clock=clock,
    )
    acquisition_cutoff = (
        loader.capture_acquisition_cutoff()
        if provider_enabled
        else None
    )
    results: dict[str, ResearchDataResult] = {}
    for timeframe in model_config.ladder:
        start, end = resolved_bounds[timeframe]
        results[timeframe] = await loader.load(
            instrument_id=research_config.instrument_id,
            asset=research_config.asset,
            timeframe=timeframe,
            start=start,
            end=end,
            source_mode=mode,
            provider_calls_authorized=provider_enabled,
            acquisition_cutoff=acquisition_cutoff,
        )
    return results


@dataclass(slots=True)
class ResearchComposition:
    """Notebook-owned trace, verified bundle, and one loopback session."""

    model_config: ResolvedSRV2Config
    research_config: ResolvedSRV2ResearchNotebookConfig
    source_results: Mapping[str, ResearchDataResult]
    source_manifest: ResearchSourceSetManifest
    trace: SRV2ResearchTrace
    workspace: Path
    bundle_path: Path
    viewer_session: SRV2ResearchViewerSession

    @property
    def urls(self) -> tuple[tuple[str, str], ...]:
        return iframe_urls(self.viewer_session.url, {
            "configured_timeframes": self.trace.configured_timeframes,
        })

    def close(self) -> None:
        """Close the server and remove only this composition's owned workspace."""

        self.viewer_session.close()


async def compose_research(
    model_config: ResolvedSRV2Config,
    research_config: ResolvedSRV2ResearchNotebookConfig,
    *,
    adapter: HistoricalAdapter | None = None,
    allow_provider_fetch: bool = False,
    initial_state: Any = None,
    clock: Callable[[], datetime] | None = None,
) -> ResearchComposition:
    """Load verified caches, replay causally, and start one owned viewer server."""

    bounds = source_bounds(model_config, research_config)
    source_results = await load_configured_sources(
        model_config,
        research_config,
        adapter=adapter,
        allow_provider_fetch=allow_provider_fetch,
        bounds=bounds,
        clock=clock,
    )
    source_manifest = build_research_source_set_manifest(
        source_results,
        ladder=model_config.ladder,
        venue=research_config.venue,
        instrument_id=research_config.instrument_id,
        asset=research_config.asset,
        bounds=bounds,
    )
    replay = SRV2ResearchReplay(model_config, research_config)
    trace = replay.run(
        {timeframe: result.records for timeframe, result in source_results.items()},
        source_manifest=source_manifest,
        initial_state=initial_state,
    )
    workspace, bundle_path = create_owned_viewer_workspace()
    try:
        write_viewer_bundle(
            trace,
            bundle_path,
            display=research_config.display,
            market_identity={
                "venue": research_config.venue,
                "instrument_id": research_config.instrument_id,
                "asset": research_config.asset,
            },
        )
        session = SRV2ResearchViewerSession(
            bundle_path,
            cleanup_directory=workspace,
        )
    except BaseException:
        if workspace.exists():
            shutil.rmtree(workspace)
        raise
    return ResearchComposition(
        model_config=model_config,
        research_config=research_config,
        source_results=source_results,
        source_manifest=source_manifest,
        trace=trace,
        workspace=workspace,
        bundle_path=bundle_path,
        viewer_session=session,
    )


def compose_research_sync(
    model_config: ResolvedSRV2Config,
    research_config: ResolvedSRV2ResearchNotebookConfig,
    *,
    adapter: HistoricalAdapter | None = None,
    allow_provider_fetch: bool = False,
    initial_state: Any = None,
    clock: Callable[[], datetime] | None = None,
) -> ResearchComposition:
    """Synchronous convenience for deterministic tests and scripts."""

    return asyncio.run(
        compose_research(
            model_config,
            research_config,
            adapter=adapter,
            allow_provider_fetch=allow_provider_fetch,
            initial_state=initial_state,
            clock=clock,
        )
    )


__all__ = [
    "ResearchComposition",
    "compose_research",
    "compose_research_sync",
    "load_configured_sources",
    "source_bounds",
]
