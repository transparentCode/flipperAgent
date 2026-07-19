import asyncio
from dataclasses import dataclass

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    IntervalBar,
    IntervalCapsule,
)
from libs.models.sr.research.studies.adaptive_context_calibration.source import (
    BlockedSourceError,
    canonicalize_12h_response,
    fetch_12h_asset,
)


@dataclass
class _CountingAdapter:
    response: object
    calls: list[tuple]

    async def get_historical_ohlcv(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_frozen_daily_members_are_shared_source_bars_and_12h_is_local(config) -> None:
    from libs.models.sr.research.source.contracts import SourceBar
    from libs.models.sr.research.studies.adaptive_context_calibration.source import _frozen_members

    members = _frozen_members(config, repo_root=".")
    assert all(type(member.bars[0]) is SourceBar for member in members)
    assert all(member.bars[0].closed_at - member.bars[0].open_time == __import__("datetime").timedelta(days=1) for member in members)
    assert IntervalBar is not SourceBar


def test_provider_boundary_accepts_exact_rows_without_repair(config, synthetic_frame) -> None:
    member = canonicalize_12h_response(
        synthetic_frame,
        asset="TAOUSDT",
        config=config,
        implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
    )
    assert member.provider_calls == 1
    assert member.source_kind == "provider"
    assert type(member.bars[0]) is IntervalBar
    assert member.row_count == 1000
    assert member.bars[0].open_time == config.provider_12h.start
    assert member.bars[-1].closed_at == config.provider_12h.end


def test_provider_boundary_rejects_order_duplicates_and_nonfinite(config, synthetic_frame) -> None:
    rows = list(synthetic_frame._rows)
    rows[1], rows[2] = rows[2], rows[1]
    with pytest.raises(BlockedSourceError, match="BLOCKED_SOURCE"):
        canonicalize_12h_response(
            type(synthetic_frame)(rows),
            asset="TAOUSDT",
            config=config,
            implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
        )
    rows = list(synthetic_frame._rows)
    rows[2] = rows[1]
    with pytest.raises(BlockedSourceError):
        canonicalize_12h_response(
            type(synthetic_frame)(rows),
            asset="TAOUSDT",
            config=config,
            implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
        )
    rows = list(synthetic_frame._rows)
    rows[4] = (*rows[4][:2], float("nan"), *rows[4][3:])
    with pytest.raises(BlockedSourceError):
        canonicalize_12h_response(
            type(synthetic_frame)(rows),
            asset="TAOUSDT",
            config=config,
            implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
        )


def test_provider_call_is_one_and_failure_is_not_retried(config, synthetic_frame) -> None:
    adapter = _CountingAdapter(synthetic_frame, [])
    result = asyncio.run(
        fetch_12h_asset(
            "TAOUSDT",
            config=config,
            implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
            adapter_factory=lambda: adapter,
        )
    )
    assert result.provider_calls == 1
    assert len(adapter.calls) == 1
    assert adapter.calls[0][0] == ("TAOUSDT", "12h")
    assert adapter.calls[0][1]["since"] == 1724025600000
    assert adapter.calls[0][1]["until"] == 1767225599999
    assert adapter.calls[0][1]["limit"] == 1000


def test_interval_capsule_rejects_daily_or_inconsistent_contract() -> None:
    with pytest.raises(ContractValidationError, match="timeframe"):
        IntervalCapsule(
            asset="TAOUSDT",
            venue="binance_usdm",
            timeframe="1d",
            source_id="a" * 64,
            source_bundle_id="b" * 64,
            source_bars_sha256="c" * 64,
            source_grid_sha256="d" * 64,
            requested_since=__import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            requested_until=__import__("datetime").datetime(2025, 1, 2, tzinfo=__import__("datetime").timezone.utc),
            provider_calls=0,
            provider_request_since_ms=None,
            provider_request_until_ms=None,
            adapter_limit=1000,
            source_kind="synthetic",
            implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
            bars=(),
        )
