"""Strategy observability router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.strategy_app.control import (
    StrategyControlRecord,
    StrategyControlStore,
    StrategyDesiredState,
)
from apps.strategy_app.observability.status import StrategyObservabilityService
from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
from apps.strategy_app.state import StrategyPair, StrategyPairState, StrategyRuntimeStatus
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs

router = APIRouter(prefix="/strategy", tags=["strategy"])

config_manager = ConfigManager()


class StrategyActionRequest(BaseModel):
    reason: str | None = None


@router.get("/latest", summary="Latest trade signal per asset/timeframe")
async def strategy_latest() -> dict[str, Any]:
    """Return the latest published trade signal for every configured pair."""
    service, valkey_client = await _open_observability_service()
    try:
        return await service.latest_signals()
    finally:
        await valkey_client.aclose()


@router.get("/status", response_model=dict[str, StrategyRuntimeStatus], summary="Per-pair strategy runtime status")
async def strategy_status() -> dict[str, StrategyRuntimeStatus]:
    service, valkey_client = await _open_observability_service()
    try:
        return await service.status()
    finally:
        await valkey_client.aclose()


@router.post(
    "/{symbol}/{timeframe}/pause",
    response_model=StrategyControlRecord,
    summary="Pause strategy signal generation for one pair",
)
async def pause_strategy_pair(
    symbol: str,
    timeframe: str,
    body: StrategyActionRequest,
) -> StrategyControlRecord:
    pair = _require_strategy_pair(symbol, timeframe)
    store, state_store, valkey_client = await _open_control_store()
    try:
        record = await store.set_desired_state(
            pair,
            StrategyDesiredState.PAUSED,
            reason=body.reason,
        )
        await state_store.update(
            pair,
            state=StrategyPairState.PAUSED,
            detail={
                "phase": "operator_control",
                "desired_state": StrategyDesiredState.PAUSED.value,
                "reason": body.reason,
            },
        )
        return record
    finally:
        await valkey_client.aclose()


@router.post(
    "/{symbol}/{timeframe}/resume",
    response_model=StrategyControlRecord,
    summary="Resume strategy signal generation for one pair",
)
async def resume_strategy_pair(
    symbol: str,
    timeframe: str,
    body: StrategyActionRequest,
) -> StrategyControlRecord:
    pair = _require_strategy_pair(symbol, timeframe)
    store, state_store, valkey_client = await _open_control_store()
    try:
        record = await store.set_desired_state(
            pair,
            StrategyDesiredState.LIVE,
            reason=body.reason,
        )
        await state_store.update(
            pair,
            state=StrategyPairState.WARMING,
            last_error=None,
            replace_last_error=True,
            detail={
                "phase": "operator_control",
                "desired_state": StrategyDesiredState.LIVE.value,
                "reason": body.reason,
            },
        )
        return record
    finally:
        await valkey_client.aclose()


async def _open_observability_service() -> tuple[StrategyObservabilityService, Any]:
    pairs = _discover_strategy_pairs()
    valkey_client = await create_valkey_client(config_manager)
    return StrategyObservabilityService(valkey_client, pairs), valkey_client


async def _open_control_store() -> tuple[StrategyControlStore, StrategyRuntimeStateStore, Any]:
    valkey_client = await create_valkey_client(config_manager)
    return (
        StrategyControlStore(valkey_client),
        StrategyRuntimeStateStore(valkey_client),
        valkey_client,
    )


def _discover_strategy_pairs() -> list[StrategyPair]:
    return [
        StrategyPair(asset=asset, timeframe=timeframe)
        for asset, timeframe in discover_pairs(config_manager)
    ]


def _require_strategy_pair(symbol: str, timeframe: str) -> StrategyPair:
    normalized_symbol = symbol.upper().strip()
    normalized_timeframe = timeframe.strip()
    for pair in _discover_strategy_pairs():
        if pair.asset == normalized_symbol and pair.timeframe == normalized_timeframe:
            return pair
    raise HTTPException(
        status_code=404,
        detail=f"Strategy pair '{normalized_symbol}:{normalized_timeframe}' not found.",
    )
