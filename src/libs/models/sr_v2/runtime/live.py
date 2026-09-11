"""One state-only live facade for closed SR v2 bars."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from ..config.resolver import ResolvedSRV2Config
from ..contracts import require_utc
from ..domain.bars import SRBar
from ..domain.state import create_initial_state
from ..features.time import grid_for
from ..persistence.contracts import (
    CheckpointCorruptionError,
    CheckpointDisposition,
    CheckpointRecord,
    CheckpointRepository,
    SRV2LaneIdentity,
)
from ..structural import SRModel, SRStepRequest, SRStepResult


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveCommitResult:
    """The commit disposition and publishable result, if this call won."""

    identity: SRV2LaneIdentity
    cutoff: datetime
    disposition: CheckpointDisposition
    result: SRStepResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SRV2LaneIdentity):
            raise TypeError("identity must be SRV2LaneIdentity")
        cutoff = require_utc(self.cutoff, field_name="live cutoff")
        if not isinstance(self.disposition, CheckpointDisposition):
            raise TypeError("disposition must be CheckpointDisposition")
        winner = self.disposition in {
            CheckpointDisposition.INSERTED,
            CheckpointDisposition.UPDATED,
        }
        if winner and self.result is None:
            raise ValueError("winning live commits must include a structural result")
        if not winner and self.result is not None:
            raise ValueError("losing live commits cannot publish a structural result")
        if self.result is not None:
            if not isinstance(self.result, SRStepResult):
                raise TypeError("result must be SRStepResult or None")
            if self.result.market_as_of != cutoff:
                raise ValueError("live result cutoff does not match commit cutoff")
            if (
                self.result.venue,
                self.result.instrument_id,
                self.result.asset,
            ) != (
                self.identity.venue,
                self.identity.instrument_id,
                self.identity.asset,
            ):
                raise ValueError("live result identity does not match commit identity")
            if self.result.config_fingerprint != self.identity.config_fingerprint:
                raise ValueError("live result config does not match commit identity")
        object.__setattr__(self, "cutoff", cutoff)


class LiveRuntime:
    """Drive one immutable lane through injected latest-state persistence.

    Genesis is intentionally opt-in.  The caller supplies sparse exact source
    windows for one closed trigger cutoff; all semantic validation remains in
    ``SRModel.step`` and one successful repository CAS decides publication.
    """

    __slots__ = ("_allow_genesis", "_config", "_identity", "_model", "_repository")

    def __init__(
        self,
        config: ResolvedSRV2Config,
        *,
        venue: str,
        instrument_id: str,
        asset: str,
        checkpoint_repository: CheckpointRepository,
        allow_genesis: bool = False,
    ) -> None:
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("config must be ResolvedSRV2Config")
        if not isinstance(allow_genesis, bool):
            raise TypeError("allow_genesis must be a bool")
        if not callable(getattr(checkpoint_repository, "load", None)) or not callable(
            getattr(checkpoint_repository, "commit", None)
        ):
            raise TypeError("checkpoint_repository must provide load() and commit()")
        self._config = config
        self._identity = SRV2LaneIdentity(
            venue=venue,
            instrument_id=instrument_id,
            asset=asset,
            config_fingerprint=config.config_fingerprint,
        )
        self._repository = checkpoint_repository
        self._model = SRModel(config)
        self._allow_genesis = allow_genesis

    @property
    def config(self) -> ResolvedSRV2Config:
        """Return the immutable resolved lane configuration."""

        return self._config

    @property
    def identity(self) -> SRV2LaneIdentity:
        """Return the immutable checkpoint lane identity."""

        return self._identity

    async def on_closed_bar(
        self,
        exact_changed_windows: Mapping[str, Sequence[SRBar]],
    ) -> LiveCommitResult:
        """Process one caller-supplied closed trigger cutoff.

        The cutoff is derived only from the final bar in the trigger window.
        A proposal is encoded before ``commit`` acquires a repository
        connection.  Structural output is returned only for an INSERTED or
        UPDATED winner; retries and CAS losers return their disposition with no
        downstream result.
        """

        windows = _normalize_windows(exact_changed_windows, self._config)
        trigger_values = windows[self._config.trigger_timeframe]
        cutoff = trigger_values[-1].bar_close_at
        current = await self._repository.load(self._identity)
        if current is None:
            if not self._allow_genesis:
                raise ValueError("live genesis requires explicit allow_genesis=True")
            state = create_initial_state(
                config_fingerprint=self._identity.config_fingerprint,
                venue=self._identity.venue,
                instrument_id=self._identity.instrument_id,
                asset=self._identity.asset,
            )
            expected_generation: int | None = None
        else:
            self._validate_loaded_checkpoint(current)
            state = current.state
            expected_generation = current.generation

        structural_result = self._model.step(
            SRStepRequest(
                venue=self._identity.venue,
                instrument_id=self._identity.instrument_id,
                asset=self._identity.asset,
                market_as_of=cutoff,
                state=state,
                windows=windows,
            )
        )
        proposal = CheckpointRecord.from_state(
            identity=self._identity,
            state=structural_result.state,
        )
        disposition = await self._repository.commit(
            proposal,
            expected_generation=expected_generation,
        )
        if not isinstance(disposition, CheckpointDisposition):
            raise TypeError("checkpoint repository returned an invalid disposition")
        if structural_result.duplicate_delivery:
            if disposition is not CheckpointDisposition.IDENTICAL:
                raise CheckpointCorruptionError(
                    "duplicate structural delivery did not classify as IDENTICAL"
                )
            published: SRStepResult | None = None
        elif disposition in {
            CheckpointDisposition.INSERTED,
            CheckpointDisposition.UPDATED,
        }:
            published = structural_result
        else:
            published = None
        return LiveCommitResult(
            identity=self._identity,
            cutoff=cutoff,
            disposition=disposition,
            result=published,
        )

    def _validate_loaded_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        if not isinstance(checkpoint, CheckpointRecord):
            raise CheckpointCorruptionError("checkpoint repository returned an invalid record")
        if checkpoint.identity != self._identity:
            raise CheckpointCorruptionError("checkpoint identity does not match live lane")
        state = checkpoint.state
        if len(state.active_lineages) > self._config.max_active_lineages:
            raise CheckpointCorruptionError("checkpoint active lineage bound exceeded")
        if len(state.terminal_tombstones) > self._config.max_terminal_tombstones:
            raise CheckpointCorruptionError("checkpoint tombstone bound exceeded")
        if set(state.source_cutoffs) != set(self._config.ladder):
            raise CheckpointCorruptionError("checkpoint source cutoffs do not cover the ladder")
        if set(state.source_fingerprints) != set(self._config.ladder):
            raise CheckpointCorruptionError("checkpoint source fingerprints do not cover the ladder")
        if set(state.source_fingerprint_sequences) != set(self._config.ladder):
            raise CheckpointCorruptionError("checkpoint source sequences do not cover the ladder")
        if state.last_trigger_at is None:
            raise CheckpointCorruptionError("checkpoint must have a committed cutoff")
        for timeframe, source_cutoff in state.source_cutoffs.items():
            expected = grid_for(timeframe).expected_closed_cutoff(state.last_trigger_at)
            if source_cutoff != expected:
                raise CheckpointCorruptionError(
                    f"checkpoint source cutoff is inconsistent: {timeframe}"
                )


def _normalize_windows(
    windows: Mapping[str, Sequence[SRBar]],
    config: ResolvedSRV2Config,
) -> Mapping[str, tuple[SRBar, ...]]:
    if not isinstance(windows, Mapping):
        raise TypeError("exact_changed_windows must be a mapping")
    normalized: dict[str, tuple[SRBar, ...]] = {}
    allowed = set(config.ladder)
    for timeframe, values in windows.items():
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise TypeError("window keys must be non-empty strings")
        if timeframe not in allowed:
            raise ValueError(f"unknown live source timeframe: {timeframe}")
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise TypeError(f"window must be a sequence: {timeframe}")
        selected = tuple(values)
        if not selected:
            raise ValueError(f"window must not be empty: {timeframe}")
        if any(not isinstance(item, SRBar) for item in selected):
            raise TypeError(f"window must contain SRBar values: {timeframe}")
        if any(item.timeframe != timeframe for item in selected):
            raise ValueError(f"window timeframe mismatch: {timeframe}")
        normalized[timeframe] = selected
    trigger = config.trigger_timeframe
    if trigger not in normalized:
        raise ValueError(f"live windows must include trigger timeframe: {trigger}")
    return MappingProxyType(normalized)


__all__ = ["LiveCommitResult", "LiveRuntime"]
