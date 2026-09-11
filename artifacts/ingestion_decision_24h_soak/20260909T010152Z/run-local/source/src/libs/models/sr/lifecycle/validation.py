"""Pure precondition checks for deterministic lifecycle processing."""

from __future__ import annotations

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.state import SRState
from libs.models.sr.domain.zones import ZoneStatus

from .transitions import TERMINAL_STATUSES


def validate_step_inputs(
    previous_state: SRState,
    closed_bar: ClosedBar,
    resolved_config: ResolvedSRConfig,
) -> tuple[int, frozenset[str]]:
    """Validate lifecycle inputs in historical exception order."""
    if type(previous_state) is not SRState:
        raise ContractValidationError("previous_state must be SRState")
    if type(closed_bar) is not ClosedBar:
        raise ContractValidationError("closed_bar must be ClosedBar")
    if type(resolved_config) is not ResolvedSRConfig:
        raise ContractValidationError(
            "resolved_config must be ResolvedSRConfig"
        )
    if closed_bar.state_key != previous_state.state_key:
        raise ContractValidationError(
            "closed_bar.state_key must match previous_state.state_key"
        )
    if (
        previous_state.state_key.symbol != resolved_config.asset
        or previous_state.state_key.timeframe != resolved_config.timeframe
    ):
        raise ContractValidationError(
            "state symbol/timeframe must match resolved configuration"
        )
    if previous_state.config_hash != resolved_config.resolved_config_hash:
        raise ContractValidationError(
            "state.config_hash must match resolved configuration hash"
        )

    max_recent_bars = 2 * resolved_config.detection.pivot_span_bars
    if len(previous_state.recent_bars) > max_recent_bars:
        raise ContractValidationError(
            "previous_state.recent_bars exceeds the configured detection buffer"
        )
    if previous_state.recent_bars:
        if (
            previous_state.recent_bars[-1].bar_id
            != previous_state.last_processed_bar
        ):
            raise ContractValidationError(
                "recent_bars final bar_id must match last_processed_bar"
            )
        if closed_bar.bar_id in {
            bar.bar_id for bar in previous_state.recent_bars
        }:
            raise ContractValidationError("closed_bar.bar_id duplicates a recent bar")
        if closed_bar.closed_at <= previous_state.recent_bars[-1].closed_at:
            raise ContractValidationError(
                "closed_bar.closed_at must be later than recent bars"
            )

    non_terminal_count = sum(
        record.runtime.status not in TERMINAL_STATUSES
        for record in previous_state.zones
    )
    if non_terminal_count > resolved_config.runtime.max_active_zones:
        raise ContractValidationError("previous state exceeds max_active_zones")

    start_association_ids = frozenset(
        record.definition.zone_id
        for record in previous_state.zones
        if record.runtime.status not in TERMINAL_STATUSES
    )
    if (
        previous_state.last_processed_bar is not None
        and closed_bar.bar_id == previous_state.last_processed_bar
    ):
        raise ContractValidationError(
            "closed_bar.bar_id duplicates previous_state.last_processed_bar"
        )
    for record in previous_state.zones:
        if closed_bar.closed_at < record.runtime.updated_at:
            raise ContractValidationError(
                "closed_bar.closed_at must not precede zone runtime.updated_at"
            )
        if record.runtime.status in TERMINAL_STATUSES:
            continue
        if record.runtime.age_bars >= resolved_config.lifecycle.max_age_bars:
            raise ContractValidationError(
                "non-terminal zone age_bars must be below max_age_bars"
            )
        if (
            record.runtime.status is ZoneStatus.BREACH_PENDING
            and record.runtime.pending_breach_count
            >= resolved_config.lifecycle.break_confirm_closes
        ):
            raise ContractValidationError(
                "pending_breach_count must be below break_confirm_closes"
            )
    return max_recent_bars, start_association_ids


__all__ = ["validate_step_inputs"]
