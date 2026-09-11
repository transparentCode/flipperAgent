"""One bounded, caller-supplied offline execution loop for SR v2."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from ..config.resolver import ResolvedSRV2Config
from ..contracts import require_utc
from ..domain.bars import SRBar
from ..domain.state import SRState, create_initial_state
from ..features.time import grid_for
from ..structural import SRModel, SRStepRequest, SRStepResult


class OfflineMode(str, Enum):
    """Execution starting point for one exact offline run."""

    GENESIS_EXACT = "GENESIS_EXACT"
    CHECKPOINT_EXACT = "CHECKPOINT_EXACT"


@dataclass(frozen=True, slots=True, kw_only=True)
class OfflineRunResult:
    """Bounded result of an offline run; no step trace is retained."""

    mode: OfflineMode
    cutoff: datetime
    final_result: SRStepResult
    steps: int
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OfflineMode):
            raise TypeError("mode must be OfflineMode")
        require_utc(self.cutoff, field_name="offline cutoff")
        if not isinstance(self.final_result, SRStepResult):
            raise TypeError("final_result must be SRStepResult")
        if self.final_result.market_as_of != self.cutoff:
            raise ValueError("offline result cutoff does not match final result")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int) or self.steps <= 0:
            raise ValueError("offline steps must be positive")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    @property
    def state(self) -> SRState:
        """Return the final semantic state without retaining another copy."""

        return self.final_result.state

    @property
    def result(self) -> SRStepResult:
        """Short access to the final step result."""

        return self.final_result


class OfflineCompute:
    """Run the core over an explicit in-memory closed-bar dataset."""

    def __init__(
        self,
        config: ResolvedSRV2Config,
        *,
        venue: str | None = None,
        instrument_id: str | None = None,
        asset: str | None = None,
    ) -> None:
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("config must be ResolvedSRV2Config")
        self.config = config
        self._model = SRModel(config)
        self._identity = self._normalize_identity(venue, instrument_id, asset)

    def run(
        self,
        dataset: Mapping[str, Sequence[SRBar]],
        checkpoint: SRState | None = None,
        cutoff: datetime | None = None,
        *,
        mode: OfflineMode | str = OfflineMode.GENESIS_EXACT,
        start_cutoff: datetime | None = None,
        on_step: Callable[[SRStepResult], None] | None = None,
    ) -> OfflineRunResult:
        """Run exact closed-bar steps through ``cutoff``.

        The dataset is already loaded by the caller.  This method performs no
        database, network, cache, or filesystem access and retains only the
        final result/state plus compact provenance.
        """

        resolved_mode = self._resolve_mode(mode)
        if cutoff is None:
            raise TypeError("offline cutoff is required")
        require_utc(cutoff, field_name="offline cutoff")
        if grid_for(self.config.trigger_timeframe).expected_closed_cutoff(cutoff) != cutoff:
            raise ValueError("offline cutoff must align to the closed trigger grid")
        if start_cutoff is not None:
            require_utc(start_cutoff, field_name="offline start cutoff")
            if grid_for(self.config.trigger_timeframe).expected_closed_cutoff(start_cutoff) != start_cutoff:
                raise ValueError("offline start cutoff must align to the closed trigger grid")
            if start_cutoff > cutoff:
                raise ValueError("offline start cutoff must not follow cutoff")
        if resolved_mode is OfflineMode.GENESIS_EXACT:
            if checkpoint is not None:
                raise ValueError("GENESIS_EXACT does not accept a checkpoint")
        else:
            self._validate_checkpoint(checkpoint)
            if start_cutoff is not None and start_cutoff <= checkpoint.last_trigger_at:
                raise ValueError("checkpoint start cutoff must follow the checkpoint cutoff")

        identity = self._resolve_identity(checkpoint)
        normalized = self._normalize_dataset(dataset)
        indexes = self._build_close_indexes(normalized)
        trigger_closes = self._select_trigger_closes(
            normalized,
            indexes,
            cutoff=cutoff,
            start_cutoff=start_cutoff,
            checkpoint=checkpoint,
            mode=resolved_mode,
        )
        state = checkpoint or create_initial_state(
            config_fingerprint=self.config.config_fingerprint,
            venue=identity[0],
            instrument_id=identity[1],
            asset=identity[2],
        )
        last_result: SRStepResult | None = None
        for current_cutoff in trigger_closes:
            full_windows = self.windows_for(normalized, current_cutoff, close_indexes=indexes)
            windows = self._sparse_windows(state, full_windows, current_cutoff)
            result = self._model.step(
                SRStepRequest(
                    venue=state.venue,
                    instrument_id=state.instrument_id,
                    asset=state.asset,
                    market_as_of=current_cutoff,
                    state=state,
                    windows=windows,
                )
            )
            state = result.state
            last_result = result
            if on_step is not None:
                on_step(result)
        if last_result is None:
            raise ValueError("offline run produced no structural result")
        provenance = {
            "mode": resolved_mode.value,
            "cutoff": cutoff,
            "steps": len(trigger_closes),
            "config_fingerprint": self.config.config_fingerprint,
            "source_cutoffs": last_result.source_cutoffs,
            "source_fingerprints": last_result.source_fingerprints,
        }
        return OfflineRunResult(
            mode=resolved_mode,
            cutoff=cutoff,
            final_result=last_result,
            steps=len(trigger_closes),
            provenance=provenance,
        )

    def windows_for(
        self,
        dataset: Mapping[str, tuple[SRBar, ...]],
        cutoff: datetime,
        *,
        close_indexes: Mapping[str, tuple[datetime, ...]] | None = None,
    ) -> Mapping[str, tuple[SRBar, ...]]:
        """Return exact bounded windows at one closed trigger cutoff."""

        require_utc(cutoff, field_name="offline window cutoff")
        indexes = close_indexes or self._build_close_indexes(dataset)
        requirements = dict(self.config.history_requirements())
        result: dict[str, tuple[SRBar, ...]] = {}
        for timeframe in self.config.ladder:
            expected_end = grid_for(timeframe).expected_closed_cutoff(cutoff)
            values = dataset[timeframe]
            end_index = bisect_right(indexes[timeframe], expected_end)
            required = requirements[timeframe]
            if end_index < required:
                raise ValueError(f"insufficient exact trailing history for {timeframe}")
            selected = tuple(values[end_index - required : end_index])
            if selected[-1].bar_close_at != expected_end:
                raise ValueError(f"causal trailing window for {timeframe} ends at the wrong closed cutoff")
            result[timeframe] = selected
        return result

    def _select_trigger_closes(
        self,
        dataset: Mapping[str, tuple[SRBar, ...]],
        indexes: Mapping[str, tuple[datetime, ...]],
        *,
        cutoff: datetime,
        start_cutoff: datetime | None,
        checkpoint: SRState | None,
        mode: OfflineMode,
    ) -> tuple[datetime, ...]:
        trigger_closes = tuple(
            value for value in indexes[self.config.trigger_timeframe] if value <= cutoff
        )
        if not trigger_closes or trigger_closes[-1] != cutoff:
            raise ValueError("offline dataset must contain the declared closed cutoff")
        if mode is OfflineMode.CHECKPOINT_EXACT:
            assert checkpoint is not None
            first_expected = checkpoint.last_trigger_at + self.config.trigger_duration
            values = tuple(value for value in trigger_closes if value > checkpoint.last_trigger_at)
            if not values or values[0] != first_expected:
                raise ValueError("checkpoint continuation has a missing or overlapping trigger cutoff")
            if start_cutoff is not None and values[0] != start_cutoff:
                raise ValueError("checkpoint continuation does not start at the requested cutoff")
            return values

        if start_cutoff is not None:
            values = tuple(value for value in trigger_closes if value >= start_cutoff)
            if not values or values[0] != start_cutoff:
                raise ValueError("GENESIS_EXACT requires the requested start cutoff")
            self.windows_for(dataset, values[0], close_indexes=indexes)
            return values
        for value in trigger_closes:
            try:
                self.windows_for(dataset, value, close_indexes=indexes)
            except ValueError:
                continue
            return tuple(item for item in trigger_closes if item >= value)
        raise ValueError("dataset has no cutoff with sufficient exact genesis history")

    def _normalize_dataset(self, dataset: Mapping[str, Sequence[SRBar]]) -> Mapping[str, tuple[SRBar, ...]]:
        if not isinstance(dataset, Mapping) or set(dataset) != set(self.config.ladder):
            raise ValueError("offline dataset must cover the exact configured ladder")
        normalized: dict[str, tuple[SRBar, ...]] = {}
        for timeframe in self.config.ladder:
            values = tuple(dataset[timeframe])
            if not values:
                raise ValueError(f"offline dataset has no bars for {timeframe}")
            if any(not isinstance(item, SRBar) for item in values):
                raise TypeError("offline dataset must contain SRBar values only")
            if any(item.timeframe != timeframe for item in values):
                raise ValueError(f"offline dataset timeframe mismatch: {timeframe}")
            grid_for(timeframe).validate_contiguous(
                tuple(item.bar_open_at for item in values),
                tuple(item.bar_close_at for item in values),
            )
            normalized[timeframe] = values
        return MappingProxyType(normalized)

    @staticmethod
    def _build_close_indexes(dataset: Mapping[str, Sequence[SRBar]]) -> Mapping[str, tuple[datetime, ...]]:
        return MappingProxyType(
            {
                timeframe: tuple(item.bar_close_at for item in values)
                for timeframe, values in dataset.items()
            }
        )

    def _sparse_windows(
        self,
        state: SRState,
        full_windows: Mapping[str, tuple[SRBar, ...]],
        cutoff: datetime,
    ) -> Mapping[str, tuple[SRBar, ...]]:
        if state.last_trigger_at is None:
            return full_windows
        trigger = self.config.trigger_timeframe
        selected = {trigger: full_windows[trigger]}
        for timeframe in self.config.ladder:
            expected = grid_for(timeframe).expected_closed_cutoff(cutoff)
            if expected > state.source_cutoffs[timeframe]:
                selected[timeframe] = full_windows[timeframe]
        return selected

    def _validate_checkpoint(self, checkpoint: SRState | None) -> None:
        if not isinstance(checkpoint, SRState):
            raise TypeError("CHECKPOINT_EXACT requires an SRState checkpoint")
        if checkpoint.config_fingerprint != self.config.config_fingerprint:
            raise ValueError("offline checkpoint config fingerprint mismatch")
        if (
            set(checkpoint.source_cutoffs) != set(self.config.ladder)
            or set(checkpoint.source_fingerprints) != set(self.config.ladder)
            or set(checkpoint.source_fingerprint_sequences) != set(self.config.ladder)
        ):
            raise ValueError("offline checkpoint source identities must cover the exact ladder")
        if checkpoint.last_trigger_at is None:
            raise ValueError("offline checkpoint must have a committed cutoff")
        for timeframe, source_cutoff in checkpoint.source_cutoffs.items():
            expected = grid_for(timeframe).expected_closed_cutoff(checkpoint.last_trigger_at)
            if source_cutoff != expected:
                raise ValueError(f"offline checkpoint source cutoff is inconsistent for {timeframe}")

    @staticmethod
    def _resolve_mode(mode: OfflineMode | str) -> OfflineMode:
        try:
            return mode if isinstance(mode, OfflineMode) else OfflineMode(str(mode).upper())
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported offline mode") from exc

    @staticmethod
    def _normalize_identity(
        venue: str | None,
        instrument_id: str | None,
        asset: str | None,
    ) -> tuple[str, str, str] | None:
        values = (venue, instrument_id, asset)
        if all(value is None for value in values):
            return None
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("offline runtime identity requires non-empty venue, instrument_id, and asset")
        return values[0], values[1], values[2]

    def _resolve_identity(
        self,
        checkpoint: SRState | None,
    ) -> tuple[str, str, str]:
        identity = self._identity
        if identity is None and checkpoint is not None:
            identity = (checkpoint.venue, checkpoint.instrument_id, checkpoint.asset)
        if identity is None:
            raise ValueError("GENESIS_EXACT requires explicit runtime identity")
        if checkpoint is not None and identity != (
            checkpoint.venue,
            checkpoint.instrument_id,
            checkpoint.asset,
        ):
            raise ValueError("offline checkpoint runtime identity mismatch")
        return identity


__all__ = ["OfflineCompute", "OfflineMode", "OfflineRunResult"]
