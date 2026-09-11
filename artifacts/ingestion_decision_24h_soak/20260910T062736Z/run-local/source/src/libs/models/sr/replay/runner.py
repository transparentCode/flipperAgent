"""Deterministic replay through the authoritative SR engine path."""

from __future__ import annotations

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.state import SRState
from libs.models.sr.lifecycle.engine import SREngine


def _validate_inputs(
    initial_state: SRState,
    bars: tuple[ClosedBar, ...],
    resolved_config: ResolvedSRConfig,
) -> None:
    if type(initial_state) is not SRState:
        raise ContractValidationError("initial_state must be exactly SRState")
    if type(bars) is not tuple:
        raise ContractValidationError("bars must be exactly tuple[ClosedBar, ...]")
    if type(resolved_config) is not ResolvedSRConfig:
        raise ContractValidationError(
            "resolved_config must be exactly ResolvedSRConfig"
        )
    if (
        initial_state.state_key.symbol != resolved_config.asset
        or initial_state.state_key.timeframe != resolved_config.timeframe
    ):
        raise ContractValidationError(
            "state symbol/timeframe must match resolved configuration"
        )
    if initial_state.config_hash != resolved_config.resolved_config_hash:
        raise ContractValidationError(
            "state.config_hash must match resolved configuration hash"
        )

    retained_ids = {bar.bar_id for bar in initial_state.recent_bars}
    supplied_ids: set[str] = set()
    previous_timestamp = None
    for index, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(
                f"bars[{index}] must be exactly ClosedBar"
            )
        if bar.state_key != initial_state.state_key:
            raise ContractValidationError(
                f"bars[{index}].state_key must match initial_state.state_key"
            )
        if bar.bar_id in retained_ids:
            raise ContractValidationError(
                f"bars[{index}].bar_id duplicates a retained recent bar"
            )
        if bar.bar_id in supplied_ids:
            raise ContractValidationError(
                f"duplicate bar_id in replay batch: {bar.bar_id}"
            )
        supplied_ids.add(bar.bar_id)
        if previous_timestamp is not None and bar.closed_at <= previous_timestamp:
            raise ContractValidationError(
                "replay bars.closed_at values must be strictly increasing"
            )
        previous_timestamp = bar.closed_at

    if not bars:
        return
    first_bar = bars[0]
    if (
        initial_state.last_processed_bar is not None
        and first_bar.bar_id == initial_state.last_processed_bar
    ):
        raise ContractValidationError(
            "first replay bar duplicates initial_state.last_processed_bar"
        )
    if initial_state.recent_bars:
        if first_bar.closed_at <= initial_state.recent_bars[-1].closed_at:
            raise ContractValidationError(
                "first replay bar must be later than retained recent bars"
            )


def replay_bars(
    initial_state: SRState,
    bars: tuple[ClosedBar, ...],
    resolved_config: ResolvedSRConfig,
) -> tuple[SRState, tuple[SRSnapshot, ...]]:
    """Replay caller-ordered bars through ``SREngine.step`` exactly once each."""
    _validate_inputs(initial_state, bars, resolved_config)
    if not bars:
        return initial_state, ()

    engine = SREngine()
    state = initial_state
    snapshots: list[SRSnapshot] = []
    for bar in bars:
        state, snapshot, _ = engine.step(state, bar, resolved_config)
        snapshots.append(snapshot)
    return state, tuple(snapshots)


__all__ = ["replay_bars"]
