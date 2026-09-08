"""Focused synthetic tests for the F1C role-validation contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines_v4.engine.types import TrendlineBar
from research.trendlines_v4 import pivot_consensus_role_validation as f1c


def _bars(
    count: int = 491,
    *,
    start: datetime = datetime(2025, 11, 1, tzinfo=UTC),
    spacing: timedelta = timedelta(hours=4),
) -> tuple[TrendlineBar, ...]:
    result: list[TrendlineBar] = []
    for index in range(count):
        close = 100.0 + 0.03 * index + 0.8 * ((index % 11) - 5)
        opening = close - 0.2
        high = close + 1.0
        low = opening - 1.0
        result.append(
            TrendlineBar(
                closed_at=start + index * spacing,
                open=opening,
                high=high,
                low=low,
                close=close,
            )
        )
    return tuple(result)


def _stream(
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    *,
    count: int = 491,
) -> f1c.FrozenStream:
    spacing = timedelta(hours=1 if timeframe == "1h" else 4)
    bars = _bars(count, spacing=spacing)
    return f1c.FrozenStream(
        asset=asset,
        timeframe=timeframe,
        bars=bars,
        source_path=f"synthetic/{asset}-{timeframe}.csv",
        source_sha256=f"sha-{asset}-{timeframe}",
        source_row_count=len(bars),
        source_kind="synthetic",
    )


def _native_frame(asset_index: int = 0) -> pd.DataFrame:
    bars = _bars()
    return pd.DataFrame(
        {
            "open": [bar.open + asset_index for bar in bars],
            "high": [bar.high + asset_index for bar in bars],
            "low": [bar.low + asset_index for bar in bars],
            "close": [bar.close + asset_index for bar in bars],
            "close_time": [int(bar.closed_at.timestamp() * 1000) for bar in bars],
        }
    )


class _FakeNativeAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        *,
        until: int,
        limit: int,
        include_close_time: bool,
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "until": until,
                "limit": limit,
                "include_close_time": include_close_time,
            }
        )
        return _native_frame(len(self.calls))


def test_authority_chain_is_authenticated_without_network() -> None:
    observed = f1c.authenticate_frozen_inputs()

    assert observed["f1c_handoff"] == f1c.F1C_HANDOFF[1]
    assert observed["f1a_approval"] == f1c.F1A_APPROVAL[1]
    assert observed["f1b_source"] == f1c.F1B_SOURCE[1]


def test_rolling_membership_is_exactly_192_prefixes_from_a_491_bar_stream() -> None:
    stream = _stream()

    cutoffs = f1c.rolling_cutoff_indices(stream)
    histories = tuple(f1c.rolling_histories(stream))

    assert cutoffs == tuple(range(299, 491))
    assert len(histories) == 192
    assert histories[0][0] == 299
    assert histories[-1][0] == 490
    assert all(len(history) == 300 for _, history in histories)
    assert histories[0][1] == stream.bars[:300]
    assert histories[-1][1] == stream.bars[-300:]


def test_rolling_1h_membership_has_the_same_cutoff_contract() -> None:
    stream = _stream(timeframe="1h")

    assert f1c.rolling_cutoff_indices(stream) == tuple(range(299, 491))


def test_native_acquisition_is_one_call_per_asset_and_uses_close_time() -> None:
    adapter = _FakeNativeAdapter()

    streams, ledger = f1c.acquire_native_4h_once_sync(adapter=adapter)

    assert tuple(stream.asset for stream in streams) == f1c.ASSETS
    assert all(stream.timeframe == "4h" for stream in streams)
    assert all(len(stream.bars) == 491 for stream in streams)
    assert all(stream.terminal == streams[0].terminal for stream in streams)
    assert len(adapter.calls) == 4
    assert len(ledger) == 4
    assert all(call["timeframe"] == "4h" for call in adapter.calls)
    assert all(call["include_close_time"] is True for call in adapter.calls)
    assert all(call["limit"] == f1c.BINANCE_KLINE_PAGE_LIMIT for call in adapter.calls)
    assert all(stream.bars[0].closed_at == _bars()[0].closed_at for stream in streams)


def test_native_acquisition_rejects_non_native_spacing() -> None:
    frame = _native_frame()
    frame.loc[1, "close_time"] += 1

    with pytest.raises(ValueError, match="native 4h response"):
        f1c._native_frame_to_bars(frame, "BTCUSDT")


def test_native_acquisition_rejects_missing_close_time() -> None:
    frame = _native_frame().drop(columns=["close_time"])

    with pytest.raises(f1c.Native4HBlocked, match="close_time"):
        f1c._native_frame_to_bars(frame, "BTCUSDT")


def test_native_freeze_round_trips_exact_source_rows(tmp_path: Path) -> None:
    freeze_dir = tmp_path / "freeze"
    streams = tuple(_stream(asset, "4h", count=491) for asset in f1c.ASSETS)
    authority = {"f1c_handoff": f1c.F1C_HANDOFF[1]}
    ledger = tuple(
        {"asset": asset, "timeframe": "4h", "include_close_time": True}
        for asset in f1c.ASSETS
    )

    f1c.freeze_native_4h_sources(streams, ledger, freeze_dir, authority)
    reloaded, manifest = f1c._load_native_4h_sources(freeze_dir)

    assert tuple(item.asset for item in reloaded) == f1c.ASSETS
    assert tuple(item.bars for item in reloaded) == tuple(item.bars for item in streams)
    assert manifest["source_count"] == 4
    assert manifest["provider_call_ledger"] == list(ledger)


def test_analytical_writer_consumes_existing_native_freeze(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    freeze_dir = tmp_path / "freeze"
    streams = tuple(_stream(asset, "4h") for asset in f1c.ASSETS)
    ledger = tuple({"asset": asset} for asset in f1c.ASSETS)
    f1c.freeze_native_4h_sources(streams, ledger, freeze_dir, {})

    payloads = {
        "report.json": b"report",
        "combined_cases.json": b"cases",
        "combined_review.html": b"html",
        "manifest.json": b"manifest",
    }
    monkeypatch.setattr(f1c, "build_local_payloads", lambda _: payloads)

    def fail_validation(_: Path) -> dict[str, object]:
        raise RuntimeError("injected analytical validation failure")

    monkeypatch.setattr(
        f1c,
        "validate_artifact_bundle",
        fail_validation,
    )

    native_hashes = {
        name: f1c._sha256(freeze_dir / name) for name in f1c.NATIVE_FREEZE_NAMES
    }
    with pytest.raises(RuntimeError, match="injected analytical"):
        f1c.write_analytical_artifacts(freeze_dir)

    assert {path.name for path in freeze_dir.iterdir() if path.is_file()} == set(
        f1c.NATIVE_FREEZE_NAMES
    )
    assert {
        name: f1c._sha256(freeze_dir / name) for name in f1c.NATIVE_FREEZE_NAMES
    } == native_hashes
    assert not tuple(freeze_dir.glob(".f1c-analytical-*"))
    assert not tuple(
        freeze_dir / name
        for name in f1c.ANALYTICAL_NAMES
        if (freeze_dir / name).exists()
    )


def _synthetic_1h_streams() -> tuple[f1c.FrozenStream, ...]:
    return tuple(_low_cardinality_stream(asset, "1h") for asset in f1c.ASSETS)


def _low_cardinality_stream(asset: str, timeframe: str) -> f1c.FrozenStream:
    spacing = timedelta(hours=1 if timeframe == "1h" else 4)
    start = datetime(2025, 11, 1, tzinfo=UTC)
    bars = tuple(
        TrendlineBar(
            closed_at=start + index * spacing,
            open=100.0 + index,
            high=100.5 + index,
            low=99.5 + index,
            close=100.25 + index,
        )
        for index in range(491)
    )
    return f1c.FrozenStream(
        asset=asset,
        timeframe=timeframe,
        bars=bars,
        source_path=f"synthetic/{asset}-{timeframe}.csv",
        source_sha256=f"sha-{asset}-{timeframe}",
        source_row_count=len(bars),
        source_kind="synthetic",
    )


def _freeze_synthetic_native(tmp_path: Path) -> Path:
    freeze_dir = tmp_path / "freeze"
    streams = tuple(_low_cardinality_stream(asset, "4h") for asset in f1c.ASSETS)
    ledger = tuple({"asset": asset, "timeframe": "4h"} for asset in f1c.ASSETS)
    f1c.freeze_native_4h_sources(streams, ledger, freeze_dir, {})
    return freeze_dir


def test_build_local_payloads_works_from_native_only_freeze(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    freeze_dir = _freeze_synthetic_native(tmp_path)
    monkeypatch.setattr(f1c, "_full_1h_streams", _synthetic_1h_streams)

    assert not any((freeze_dir / name).exists() for name in f1c.ANALYTICAL_NAMES)
    payloads = f1c.build_local_payloads(freeze_dir)

    assert set(payloads) == set(f1c.ANALYTICAL_NAMES)
    assert not any((freeze_dir / name).exists() for name in f1c.ANALYTICAL_NAMES)
    manifest = json.loads(payloads["manifest.json"])
    inventory = manifest["artifact_inventory"]
    for name in ("report.json", "combined_cases.json", "combined_review.html"):
        assert inventory[name] == hashlib.sha256(payloads[name]).hexdigest()
    for name in f1c.NATIVE_FREEZE_NAMES:
        assert inventory[name] == f1c._sha256(freeze_dir / name)


def test_successful_analytical_publication_and_rebuild_are_byte_exact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    freeze_dir = _freeze_synthetic_native(tmp_path)
    monkeypatch.setattr(f1c, "_full_1h_streams", _synthetic_1h_streams)

    result = f1c.write_analytical_artifacts(freeze_dir)
    stored = {name: (freeze_dir / name).read_bytes() for name in f1c.ANALYTICAL_NAMES}
    rebuilt = f1c.build_local_payloads(freeze_dir)

    assert result["case_count"] == 16
    assert {path.name for path in freeze_dir.iterdir() if path.is_file()} == {
        *f1c.NATIVE_FREEZE_NAMES,
        *f1c.ANALYTICAL_NAMES,
    }
    assert rebuilt == stored
    assert f1c.validate_artifact_bundle(freeze_dir)["case_count"] == 16


def test_candidate_preflight_matches_tape_and_does_not_cap_candidates() -> None:
    history = _bars(300, spacing=timedelta(hours=1))

    tape, preflight = f1c._candidate_preflight(history)

    assert len(tape.candidates) == preflight["total_candidate_count"]
    assert preflight["total_potential_pivot_evidence_rows"] >= len(tape.candidates)


def test_role_selectors_are_the_frozen_f1b_roles() -> None:
    source = Path(f1c.__file__).read_text(encoding="utf-8")

    assert "select_span_first" in source
    assert "select_consensus_first" in source
    assert "top_k" not in source
    assert "quality_score =" not in source
    assert "ccxt" not in source.lower()
    assert "resample" not in source.lower()


def test_duplicate_v4_context_is_rendered_once_with_combined_role_label() -> None:
    line = {
        "role": "structural",
        "side": "support",
        "start_anchor_at": "2026-01-01T00:00:00.000000Z",
        "start_anchor_price": 100.0,
        "end_anchor_at": "2026-01-02T00:00:00.000000Z",
        "end_anchor_price": 101.0,
        "slope_per_bar": 1.0,
        "projected_price": 102.0,
        "projection_positive": True,
        "start_index": 0,
        "end_index": 1,
        "post_anchor_body_cross_count": 0,
    }

    result = f1c._dedupe_v4_context(
        {"structural": line, "current_valid": dict(line), "secondary": None}
    )

    assert len(result) == 1
    assert result[0]["role"] == "structural+current_valid"


def test_combined_case_builder_is_nonblind_and_exactly_sixteen_cases() -> None:
    streams = tuple(
        _stream(asset, timeframe) for asset in f1c.ASSETS for timeframe in ("1h", "4h")
    )
    terminal = {
        (stream.asset, stream.timeframe): {
            "cutoff_position": 490,
            "cutoff_at": f1c._timestamp(stream.terminal),
            "selected": {
                side: {"structural": None, "local": None} for side in f1c.SIDES
            },
            "v4_context": {
                side: {role: None for role in f1c.V4_ROLES} for side in f1c.SIDES
            },
        }
        for stream in streams
    }

    combined = f1c._build_combined_cases(streams, terminal)

    assert combined["case_count"] == 16
    assert combined["ratings_collected"] is False
    assert {case["asset"] for case in combined["cases"]} == set(f1c.ASSETS)
    assert {case["timeframe"] for case in combined["cases"]} == {"1h", "4h"}
    assert {case["side"] for case in combined["cases"]} == set(f1c.SIDES)
