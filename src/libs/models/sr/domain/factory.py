"""Explicit constructors for valid SR aggregate roots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import SR_SCHEMA_VERSION, SRState, SRStateKey
from .identity import ContractValidationError

if TYPE_CHECKING:
    from libs.models.sr.config.models import ResolvedSRConfig


def create_initial_state(
    state_key: SRStateKey,
    resolved_config: ResolvedSRConfig,
) -> SRState:
    """Create the only valid empty SR aggregate state."""
    from libs.models.sr.config.models import ResolvedSRConfig

    if type(state_key) is not SRStateKey:
        raise ContractValidationError("state_key must be exactly SRStateKey")
    if type(resolved_config) is not ResolvedSRConfig:
        raise ContractValidationError(
            "resolved_config must be exactly ResolvedSRConfig"
        )
    if state_key.symbol != resolved_config.asset:
        raise ContractValidationError(
            "state_key.symbol must match resolved_config.asset"
        )
    if state_key.timeframe != resolved_config.timeframe:
        raise ContractValidationError(
            "state_key.timeframe must match resolved_config.timeframe"
        )
    return SRState(
        schema_version=SR_SCHEMA_VERSION,
        state_key=state_key,
        config_hash=resolved_config.resolved_config_hash,
        last_processed_bar=None,
        zones=(),
        recent_bars=(),
    )


__all__ = ["create_initial_state"]
