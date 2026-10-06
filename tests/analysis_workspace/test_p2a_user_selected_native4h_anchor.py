from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor
from research.analysis_workspace.p2a_user_selected_native4h_anchor import (
    OUTPUT_FILES,
    P1_ROOT,
    SOURCE_COLUMNS,
    SOURCE_INTERVAL_SECONDS,
    SOURCE_LIMIT,
    SOURCE_SYMBOL,
    SOURCE_TIMEFRAME,
    SOURCE_UNTIL,
    SOURCE_UNTIL_MS,
    SWING_SPAN,
    P2AError,
    _read_frozen_source,
    _source_csv_bytes,
    _validate_source_rows,
    acquire_native_source,
    anchor_available_at_cutoff,
    assert_byte_identical_trees,
    build_anchor_context,
    build_once,
    canonical_anchor_id,
    promote_derived_files,
)

P2A_ROOT = Path("artifacts/analysis_workspace/p2a_user_selected_native4h_anchor_v1")


def _records(*, count: int = SOURCE_LIMIT) -> list[dict[str, object]]:
    interval_ms = SOURCE_INTERVAL_SECONDS * 1000
    last_open_ms = SOURCE_UNTIL_MS - interval_ms + 1
    first_open_ms = last_open_ms - (count - 1) * interval_ms
    records: list[dict[str, object]] = []
    for index in range(count):
        timestamp = first_open_ms + index * interval_ms
        close_time = timestamp + SOURCE_INTERVAL_SECONDS * 1000 - 1
        center = 100.0 + (index % 5) * 2.0
        records.append(
            {
                "timestamp": timestamp,
                "open": str(center),
                "high": str(center + 2.0),
                "low": str(center - 2.0),
                "close": str(center + 0.5),
                "volume": "10.0",
                "taker_buy_base": "5.0",
                "close_time": close_time,
            }
        )
    return records


def _frame(records: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(records, columns=SOURCE_COLUMNS)


class _FakeAdapter:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def get_historical_ohlcv(
        self, *args: object, **kwargs: object
    ) -> pd.DataFrame:
        self.calls.append((args, kwargs))
        return self.frame


def test_fake_adapter_acquisition_is_one_call_and_exactly_native_4h(
    tmp_path: Path,
) -> None:
    fake = _FakeAdapter(_frame(_records()))
    frozen = asyncio.run(
        acquire_native_source(
            tmp_path / "frozen",
            adapter_factory=lambda: fake,
        )
    )

    assert len(fake.calls) == 1
    args, kwargs = fake.calls[0]
    assert args == (SOURCE_SYMBOL, SOURCE_TIMEFRAME)
    assert kwargs == {
        "until": SOURCE_UNTIL_MS,
        "limit": SOURCE_LIMIT,
        "include_close_time": True,
    }
    assert len(frozen.rows) == SOURCE_LIMIT
    receipt = json.loads((tmp_path / "frozen" / "source_receipt.json").read_bytes())
    assert receipt["call"]["until"] == SOURCE_UNTIL
    assert receipt["call"]["until_ms"] == SOURCE_UNTIL_MS
    assert receipt["fallback_used"] is False
    assert receipt["retry_count"] == 0


@pytest.mark.parametrize(
    "mutator",
    [
        lambda records: records.pop(),
        lambda records: records.__setitem__(
            -1, {**records[-1], "close_time": records[-1]["close_time"] - 1}
        ),
        lambda records: records.__setitem__(
            25, {**records[25], "timestamp": records[24]["timestamp"]}
        ),
    ],
)
def test_source_gate_rejects_wrong_count_terminal_close_or_spacing(
    tmp_path: Path, mutator
) -> None:
    records = _records()
    mutator(records)
    fake = _FakeAdapter(_frame(records))
    with pytest.raises(P2AError):
        asyncio.run(
            acquire_native_source(tmp_path / "rejected", adapter_factory=lambda: fake)
        )
    assert len(fake.calls) == 1


def test_frozen_source_reauthenticates_canonical_csv_and_receipt() -> None:
    frozen = _read_frozen_source(P2A_ROOT)
    assert len(frozen.rows) == SOURCE_LIMIT
    assert frozen.rows[-1].close_time_ms == SOURCE_UNTIL_MS
    assert _source_csv_bytes(frozen.rows) == frozen.csv_bytes
    _validate_source_rows(frozen.rows)


def test_swing_kernel_is_reused_with_span_two_and_causal_availability(
    monkeypatch,
) -> None:
    import research.analysis_workspace.p2a_user_selected_native4h_anchor as module

    calls = []
    original = module.compute_swing_anchors

    def spy(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(module, "compute_swing_anchors", spy)
    context = build_anchor_context(_read_frozen_source(P2A_ROOT).rows)

    assert [request.span for request in calls] == [SWING_SPAN, SWING_SPAN]
    assert all(
        anchor["available_at"] <= cutoff["market_as_of"]
        for cutoff in context["cutoffs"]
        for anchor in cutoff["anchors"]
    )
    assert context["cutoffs"][0]["anchors"] == context["cutoffs"][1]["anchors"]


def test_anchor_id_is_deterministic_and_binds_exact_factual_fields() -> None:
    formed = datetime(2026, 9, 14, 3, 59, 59, 999000, tzinfo=UTC)
    available = formed + timedelta(hours=8)
    anchor = SwingAnchor("swing_high", formed, available, 79000.5)
    same = SwingAnchor("swing_high", formed, available, 79000.5)
    changed_price = SwingAnchor("swing_high", formed, available, 79000.6)
    changed_kind = SwingAnchor("swing_low", formed, available, 79000.5)

    assert canonical_anchor_id(anchor) == canonical_anchor_id(same)
    assert canonical_anchor_id(anchor) != canonical_anchor_id(changed_price)
    assert canonical_anchor_id(anchor) != canonical_anchor_id(changed_kind)


def test_context_is_newest_first_without_a_score_or_rank() -> None:
    context = build_anchor_context(_read_frozen_source(P2A_ROOT).rows)
    anchors = context["anchor_catalog"]
    keys = [(row["available_at"], row["formed_at"], row["kind"]) for row in anchors]
    assert keys == sorted(keys, reverse=True)
    assert all("score" not in row and "rank" not in row for row in anchors)
    assert context["anchor_id_fields"] == [
        "venue",
        "instrument_id",
        "timeframe",
        "kind",
        "formed_at",
        "available_at",
        "price",
    ]


def test_unavailable_before_confirmation_has_no_substitution() -> None:
    anchor = {
        "anchor_id": "anchor-later",
        "available_at": "2026-09-15T03:00:00Z",
    }
    catalog = [anchor]
    assert [
        row
        for row in catalog
        if anchor_available_at_cutoff(row, "2026-09-15T02:00:00Z")
    ] == []
    assert [
        row
        for row in catalog
        if anchor_available_at_cutoff(row, "2026-09-15T03:00:00Z")
    ] == [anchor]


def test_offline_two_builds_preserve_p1_payload_and_promote_only_derived_files(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_once(first, source_root=P2A_ROOT)
    build_once(second, source_root=P2A_ROOT)
    assert_byte_identical_trees(first, second)
    assert (first / "viewer_payloads.json").read_bytes() == (
        P1_ROOT / "viewer_payloads.json"
    ).read_bytes()
    assert len(list(first.iterdir())) == len(OUTPUT_FILES)
    assert (
        "source timeframe: 4h provider-native (binance_native)"
        in (first / "viewer.html").read_text()
    )
    assert (
        "flipperAgent.analysisWorkspace.p1.v1:" in (first / "viewer.html").read_text()
    )
    assert (
        "flipperAgent.analysisWorkspace.p2a.v1:" in (first / "viewer.html").read_text()
    )

    destination = tmp_path / "published"
    destination.mkdir()
    shutil.copyfile(
        P2A_ROOT / "native_4h_BTCUSDT.csv", destination / "native_4h_BTCUSDT.csv"
    )
    shutil.copyfile(
        P2A_ROOT / "source_receipt.json", destination / "source_receipt.json"
    )
    promote_derived_files(first, destination)
    assert tuple(sorted(path.name for path in destination.iterdir())) == tuple(
        sorted(OUTPUT_FILES)
    )
