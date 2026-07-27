"""Composition-only execution session for the mature trendlines research lab."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
from pathlib import Path
import shutil
import tempfile
from time import perf_counter
from typing import Any

from libs.models.trendlines.config.loader import load_trendlines_config
from libs.models.trendlines.data.contracts import TrendlineArtifactRef
from libs.models.trendlines.research_viewer import (
    TrendlinesResearchViewerSession,
    write_viewer_bundle,
)
from libs.models.trendlines.workflows.research import (
    PreparedTrendlineResearchReplay,
    PreparedTrendlineResearchRun,
    TrendlineResearchDataMode,
    TrendlineResearchEvidenceBundle,
    TrendlineResearchLoader,
    prepare_trendline_research,
    run_causal_replay,
    write_research_evidence_bundle,
)

from .contracts import (
    TrendlineResearchLabContractError,
    TrendlineResearchLabControls,
    TrendlineResearchLabSelection,
    TrendlineResearchLabTimings,
    default_study_registry,
)
from .performance import elapsed_ms, timed_call


_MISSING = object()


def _validated_provider_count(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrendlineResearchLabContractError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def resolve_provider_call_count(
    loader: Any,
    data_mode: TrendlineResearchDataMode,
) -> int:
    """Resolve truthful provider-call accounting after data preparation."""

    if loader is None or isinstance(loader, Mapping):
        if data_mode is TrendlineResearchDataMode.BINANCE:
            raise TrendlineResearchLabContractError(
                "BINANCE loader does not expose provider-call accounting"
            )
        return 0

    try:
        provider_calls = getattr(loader, "provider_calls", _MISSING)
    except Exception as exc:  # pragma: no cover - defensive property boundary
        raise TrendlineResearchLabContractError(
            "cannot read loader.provider_calls"
        ) from exc
    if provider_calls is not _MISSING:
        return _validated_provider_count(provider_calls, "loader.provider_calls")

    try:
        compatibility_calls = getattr(loader, "calls", _MISSING)
    except Exception as exc:  # pragma: no cover - defensive property boundary
        raise TrendlineResearchLabContractError(
            "cannot read loader.calls"
        ) from exc
    if compatibility_calls is not _MISSING:
        return _validated_provider_count(compatibility_calls, "loader.calls")

    if data_mode is TrendlineResearchDataMode.BINANCE:
        raise TrendlineResearchLabContractError(
            "BINANCE loader does not expose provider-call accounting"
        )
    return 0


@dataclass
class TrendlineResearchLabSession:
    """Prepared replay, selected evidence, timings, and owned viewer sessions."""

    controls: TrendlineResearchLabControls
    prepared: PreparedTrendlineResearchRun
    replay: PreparedTrendlineResearchReplay
    selections: dict[str, TrendlineResearchLabSelection]
    timings: TrendlineResearchLabTimings
    viewer_sessions: dict[str, TrendlinesResearchViewerSession]
    evidence_bundles: dict[str, TrendlineResearchEvidenceBundle]
    viewer_payloads: dict[str, dict[str, Any]]
    viewer_bundle_paths: dict[str, Path]
    export_paths: dict[str, Path]
    study_registry: Any
    provider_calls_made: int = 0
    _diagnostic_cache: dict[str, tuple[Any, ...]] | None = None
    _closed: bool = False

    @property
    def preparation_id(self) -> str:
        return self.prepared.preparation_id

    @property
    def dataset_id(self) -> str:
        return self.prepared.dataset.dataset_id

    @property
    def research_configuration_id(self) -> str:
        return self.prepared.configuration.research_configuration_id

    @property
    def replay_id(self) -> str:
        return self.replay.replay_id

    @property
    def viewer_urls(self) -> dict[str, str]:
        return {
            timeframe: viewer.url
            for timeframe, viewer in self.viewer_sessions.items()
        }

    def _replace_timings(self, **updates: Any) -> None:
        self.timings = replace(self.timings, **updates)

    def _ensure_open(self) -> None:
        if self._closed:
            raise TrendlineResearchLabContractError(
                "research-lab session is closed"
            )

    def time_table(self, builder: Any, *args: Any, **kwargs: Any) -> Any:
        """Build one presentation table and accumulate its construction time."""

        self._ensure_open()
        result, duration_ms = timed_call(builder, *args, **kwargs)
        self._replace_timings(
            table_ms=self.timings.table_ms + duration_ms,
        )
        return result

    def _diagnostics(self) -> dict[str, tuple[Any, ...]]:
        if self._diagnostic_cache is None:
            from libs.models.trendlines.workflows.research import (
                replay_line_rows,
                replay_pivot_count_rows,
                replay_ray_rows,
                replay_signal_rows,
                replay_snapshot_rows,
            )

            self._diagnostic_cache = {
                "snapshot": replay_snapshot_rows(self.replay),
                "pivot_count": replay_pivot_count_rows(self.replay),
                "line": replay_line_rows(self.replay),
                "ray": replay_ray_rows(self.replay),
                "signal": replay_signal_rows(self.replay),
            }
        return self._diagnostic_cache

    def select(
        self,
        timeframe: str,
        position: int,
        *,
        viewer_lookback_bars: int | None = None,
    ) -> TrendlineResearchLabSelection:
        """Select recorded evidence without running replay again."""

        self._ensure_open()
        from .navigation import select_replay_position

        selection = select_replay_position(
            self,
            timeframe=timeframe,
            position=position,
            viewer_lookback_bars=viewer_lookback_bars,
        )
        self.selections[timeframe] = selection
        self.evidence_bundles[timeframe] = selection.evidence_bundle
        self.viewer_payloads[timeframe] = dict(selection.viewer_payload)
        return selection

    def latest_selection(self, timeframe: str) -> TrendlineResearchLabSelection:
        """Return existing selection or select latest recorded point."""

        self._ensure_open()
        if timeframe in self.selections:
            return self.selections[timeframe]
        replay = self.replay.timeframes.get(timeframe)
        if replay is None or not replay.recorded_positions:
            raise TrendlineResearchLabContractError(
                f"no recorded replay positions for timeframe {timeframe}"
            )
        return self.select(timeframe, replay.recorded_positions[-1])

    def open_viewer(
        self,
        timeframe: str,
        position: int,
        *,
        lookback: int | None = None,
    ) -> str:
        """Open one new package-local viewer for one selected timeframe."""

        self._ensure_open()
        prior_selection = self.selections.get(timeframe)
        selection = self.select(
            timeframe,
            position,
            viewer_lookback_bars=lookback,
        )
        if prior_selection is not None and prior_selection.position == position:
            selection = replace(
                selection,
                selection_reason=prior_selection.selection_reason,
            )
            self.selections[timeframe] = selection
        self.close_viewer(timeframe)
        temporary_root = Path(tempfile.mkdtemp(prefix="trendlines-research-lab-"))
        bundle_path = temporary_root / "viewer_bundle"
        started = perf_counter()
        write_viewer_bundle(selection.viewer_payload, bundle_path)
        bundle_ms = elapsed_ms(started)
        started = perf_counter()
        try:
            viewer = TrendlinesResearchViewerSession(
                bundle_path,
                cleanup_directory=temporary_root,
            )
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise
        startup_ms = elapsed_ms(started)
        self.viewer_sessions[timeframe] = viewer
        self.viewer_bundle_paths[timeframe] = bundle_path
        bundle_times = dict(self.timings.viewer_bundle_ms_by_timeframe)
        bundle_times[timeframe] = bundle_ms
        startup_times = dict(self.timings.viewer_startup_ms_by_timeframe)
        startup_times[timeframe] = startup_ms
        self._replace_timings(
            viewer_bundle_ms_by_timeframe=bundle_times,
            viewer_startup_ms_by_timeframe=startup_times,
        )
        return viewer.url

    def close_viewer(self, timeframe: str) -> None:
        viewer = self.viewer_sessions.get(timeframe)
        if viewer is not None:
            viewer.close()
            self.viewer_sessions.pop(timeframe, None)
        self.viewer_bundle_paths.pop(timeframe, None)

    def close(self) -> None:
        """Close every viewer and make repeated cleanup safe."""

        if self._closed:
            return
        errors: list[BaseException] = []
        for timeframe in tuple(self.viewer_sessions):
            try:
                self.close_viewer(timeframe)
            except BaseException as exc:  # pragma: no cover - defensive cleanup boundary
                errors.append(exc)
        if errors:
            raise errors[0]
        self._closed = True


def _write_permanent_exports(
    session: TrendlineResearchLabSession,
    export_root: Path,
) -> None:
    export_root.mkdir(parents=True, exist_ok=True)
    for timeframe in session.controls.timeframes:
        selection = session.selections[timeframe]
        timeframe_root = export_root / timeframe
        timeframe_root.mkdir(parents=True, exist_ok=True)
        evidence_path = write_research_evidence_bundle(
            selection.evidence_bundle,
            TrendlineArtifactRef(
                artifact_root=str(export_root),
                relative_path=f"{timeframe}/evidence_bundle.json",
                label=f"{timeframe}-evidence",
                content_type="application/json",
            ),
        )
        viewer_path = timeframe_root / "viewer_bundle"
        write_viewer_bundle(selection.viewer_payload, viewer_path)
        session.export_paths[f"{timeframe}.evidence_bundle"] = evidence_path
        session.export_paths[f"{timeframe}.viewer_bundle"] = viewer_path

    manifest = {
        "controls": session.controls.to_dict(),
        "preparation_id": session.preparation_id,
        "dataset_id": session.dataset_id,
        "research_configuration_id": session.research_configuration_id,
        "replay_id": session.replay_id,
        "selections": {
            timeframe: {
                "position": selection.position,
                "reason": selection.selection_reason,
                "evidence_bundle_id": selection.evidence_bundle.bundle_id,
                "viewer_payload_id": selection.viewer_payload["payload_id"],
            }
            for timeframe, selection in session.selections.items()
        },
        "exports": {key: str(value) for key, value in session.export_paths.items()},
    }
    manifest_path = export_root / "lab_session_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    session.export_paths["lab_session_manifest"] = manifest_path


async def run_research_lab(
    controls: TrendlineResearchLabControls,
    *,
    trendlines_config: Any | None = None,
    loader: TrendlineResearchLoader | Any | None = None,
    injected_frames: Any | None = None,
    export_root: str | Path | None = None,
) -> TrendlineResearchLabSession:
    """Prepare, replay, diagnose, and optionally open viewers for one lab run."""

    if not isinstance(controls, TrendlineResearchLabControls):
        raise TypeError("controls must be TrendlineResearchLabControls")
    if controls.permanent_export and export_root is None:
        raise TrendlineResearchLabContractError(
            "permanent_export=True requires export_root"
        )
    if not controls.permanent_export and export_root is not None:
        raise TrendlineResearchLabContractError(
            "export_root requires permanent_export=True"
        )
    if injected_frames is not None and loader is not None:
        raise TrendlineResearchLabContractError(
            "provide injected_frames or loader, not both"
        )
    if controls.data_mode is TrendlineResearchDataMode.BINANCE:
        if not controls.provider_calls_authorized:
            raise TrendlineResearchLabContractError(
                "BINANCE execution requires provider authorization"
            )
        if loader is None:
            raise TrendlineResearchLabContractError(
                "BINANCE execution requires an explicit loader"
            )
    elif controls.provider_calls_authorized:
        raise TrendlineResearchLabContractError(
            "provider authorization is valid only for BINANCE mode"
        )
    if controls.data_mode is TrendlineResearchDataMode.INJECTED:
        loader = injected_frames if injected_frames is not None else loader

    resolved_config = trendlines_config or load_trendlines_config()
    started = perf_counter()
    prepared = await prepare_trendline_research(
        controls.to_spec(),
        trendlines_config=resolved_config,
        loader=loader,
    )
    preparation_ms = elapsed_ms(started)
    started = perf_counter()
    replay = run_causal_replay(prepared, controls.replay_spec)
    replay_ms = elapsed_ms(started)
    session = TrendlineResearchLabSession(
        controls=controls,
        prepared=prepared,
        replay=replay,
        selections={},
        timings=TrendlineResearchLabTimings(
            preparation_ms=preparation_ms,
            replay_ms=replay_ms,
            evidence_ms_by_timeframe={},
            viewer_payload_ms_by_timeframe={},
            viewer_bundle_ms_by_timeframe={},
            viewer_startup_ms_by_timeframe={},
            total_ms=0.0,
        ),
        viewer_sessions={},
        evidence_bundles={},
        viewer_payloads={},
        viewer_bundle_paths={},
        export_paths={},
        study_registry=default_study_registry(),
        provider_calls_made=resolve_provider_call_count(loader, controls.data_mode),
    )
    total_started = perf_counter()
    try:
        for timeframe in controls.timeframes:
            explicit = controls.selected_positions.get(timeframe)
            if explicit is None:
                from .navigation import default_selection_position

                position, reason = default_selection_position(session, timeframe)
                selection = session.select(timeframe, position)
                selection = replace(selection, selection_reason=reason)
                session.selections[timeframe] = selection
            else:
                session.select(timeframe, explicit)
        if controls.permanent_export:
            _write_permanent_exports(session, Path(export_root))
        if controls.start_inline_viewers:
            for timeframe in controls.timeframes:
                selection = session.selections[timeframe]
                session.open_viewer(
                    timeframe,
                    selection.position,
                    lookback=controls.viewer_lookback_bars,
                )
    except BaseException:
        session.close()
        raise
    session._replace_timings(total_ms=preparation_ms + replay_ms + elapsed_ms(total_started))
    return session


__all__ = [
    "TrendlineResearchLabSession",
    "resolve_provider_call_count",
    "run_research_lab",
]
