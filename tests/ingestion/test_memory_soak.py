from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_soak_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "qa"
        / "ingestion_runtime_memory_soak.py"
    )
    spec = importlib.util.spec_from_file_location("ingestion_runtime_memory_soak", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_asset_cleanup_completed_accepts_stopped_tombstone(monkeypatch):
    soak = _load_soak_module()

    async def fake_flags(symbol: str):
        assert symbol == "SOLUSDT"
        return ("STOPPED", False)

    async def always_true(*args, **kwargs):
        return True

    monkeypatch.setattr(soak, "fetch_asset_flags", fake_flags)
    monkeypatch.setattr(soak, "symbol_count_zero", always_true)
    monkeypatch.setattr(soak, "broker_key_absent", always_true)

    result = await soak.asset_cleanup_completed(
        "SOLUSDT",
        base_timeframe="1m",
        publish_timeframes=["1m", "1h"],
    )

    assert result is True


@pytest.mark.asyncio
async def test_asset_cleanup_completed_rejects_live_or_dirty_asset(monkeypatch):
    soak = _load_soak_module()

    async def live_flags(symbol: str):
        assert symbol == "SOLUSDT"
        return ("LIVE", True)

    async def always_true(*args, **kwargs):
        return True

    monkeypatch.setattr(soak, "fetch_asset_flags", live_flags)
    monkeypatch.setattr(soak, "symbol_count_zero", always_true)
    monkeypatch.setattr(soak, "broker_key_absent", always_true)

    assert await soak.asset_cleanup_completed(
        "SOLUSDT",
        base_timeframe="1m",
        publish_timeframes=["1m"],
    ) is False

    async def tombstone_flags(symbol: str):
        assert symbol == "SOLUSDT"
        return ("STOPPED", False)

    async def dirty_storage(*args, **kwargs):
        return False

    monkeypatch.setattr(soak, "fetch_asset_flags", tombstone_flags)
    monkeypatch.setattr(soak, "symbol_count_zero", dirty_storage)

    assert await soak.asset_cleanup_completed(
        "SOLUSDT",
        base_timeframe="1m",
        publish_timeframes=["1m"],
    ) is False
