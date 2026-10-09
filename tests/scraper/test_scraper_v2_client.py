"""TradingViewClient over replayed exchanges. No network."""

from __future__ import annotations

import pytest
from scraper_v2_support import (
    SESSION,
    ReplayTransport,
    connector_for,
    load_fixture,
    raw_bars,
    synth_exchange,
    tv_settings,
    utc,
)

from apps.scraper_app.adapters.tradingview import protocol
from apps.scraper_app.adapters.tradingview.client import TradingViewClient
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError


def _client(transport: ReplayTransport, **settings: object) -> TradingViewClient:
    return TradingViewClient(
        tv_settings(**settings),
        connector=connector_for(transport),
        session_factory=lambda: SESSION,
    )


def _transport(name: str) -> tuple[ReplayTransport, dict]:
    fixture = load_fixture(name)
    return ReplayTransport(fixture["received"]), fixture


@pytest.mark.asyncio
async def test_index_exchange_returns_a_complete_typed_result() -> None:
    transport, fixture = _transport("index_total3_1h")
    result = await _client(transport).fetch_series("CRYPTOCAP:TOTAL3", "60", 6)

    assert result.pro_name == "CRYPTOCAP:TOTAL3"
    assert result.provider_time == 1791526659
    assert len(result.bars) == 6
    assert all(len(b.fields) == 5 for b in result.bars)
    assert transport.sent == fixture["sent"]
    assert transport.closed


@pytest.mark.asyncio
async def test_alias_request_resolves_to_the_canonical_name() -> None:
    transport, _ = _transport("oi_btc_alias_1h")
    result = await _client(transport).fetch_series("BINANCE:BTCUSDTPERP_OI", "60", 6)
    assert result.pro_name == "BINANCE:BTCUSDT.P_OI"
    assert all(len(b.fields) == 4 for b in result.bars)


@pytest.mark.asyncio
async def test_invalid_symbol_is_a_symbol_error_and_stores_no_data() -> None:
    transport, _ = _transport("invalid_symbol")
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport).fetch_series("CRYPTOCAP:NOPE_NOT_A_SYMBOL", "60", 6)
    assert excinfo.value.code == errors.SYMBOL_ERROR
    assert transport.closed


@pytest.mark.asyncio
async def test_missing_series_completed_is_incomplete() -> None:
    bars = raw_bars(utc(2026, 10, 9, 1), 3)
    messages = synth_exchange(
        pro_name="CRYPTOCAP:TOTAL3",
        provider_time=1791526659,
        bars=bars,
        completed=False,
    )
    transport = ReplayTransport(messages)
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport).fetch_series("CRYPTOCAP:TOTAL3", "60", 3)
    assert excinfo.value.code == errors.INCOMPLETE
    assert transport.closed


@pytest.mark.asyncio
async def test_deadline_is_a_timeout_and_returns_no_data() -> None:
    bars = raw_bars(utc(2026, 10, 9, 1), 3)
    messages = synth_exchange(
        pro_name="CRYPTOCAP:TOTAL3",
        provider_time=1791526659,
        bars=bars,
        completed=False,
    )
    transport = ReplayTransport(messages, hang_after=True)
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport, read_deadline_seconds=0.05).fetch_series(
            "CRYPTOCAP:TOTAL3", "60", 3
        )
    assert excinfo.value.code == errors.TIMEOUT
    assert transport.closed


@pytest.mark.asyncio
async def test_response_larger_than_the_cap_is_oversize() -> None:
    transport, _ = _transport("index_total3_1h")
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport, max_response_bytes=500).fetch_series(
            "CRYPTOCAP:TOTAL3", "60", 6
        )
    assert excinfo.value.code == errors.OVERSIZE
    assert transport.closed


@pytest.mark.asyncio
async def test_peer_reported_oversize_is_oversize() -> None:
    transport = ReplayTransport([], close_after_oversize=True)
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport).fetch_series("CRYPTOCAP:TOTAL3", "60", 6)
    assert excinfo.value.code == errors.OVERSIZE


@pytest.mark.asyncio
async def test_duplicate_bar_time_keeps_the_last_value() -> None:
    first = raw_bars(utc(2026, 10, 9, 1), 2)
    revised = [first[1].__class__(time=first[1].time, fields=first[0].fields)]
    messages = synth_exchange(
        pro_name="CRYPTOCAP:TOTAL3",
        provider_time=1791526659,
        bars=[*first, *revised],
    )
    result = await _client(ReplayTransport(messages)).fetch_series(
        "CRYPTOCAP:TOTAL3", "60", 3
    )
    assert [b.time for b in result.bars] == [first[0].time, first[1].time]
    assert result.bars[1].fields == first[0].fields


@pytest.mark.asyncio
async def test_heartbeats_are_echoed_back_during_the_exchange() -> None:
    bars = raw_bars(utc(2026, 10, 9, 1), 3)
    messages = synth_exchange(
        pro_name="CRYPTOCAP:TOTAL3", provider_time=1791526659, bars=bars
    )
    messages.insert(1, protocol.encode_frame("~h~1"))
    transport = ReplayTransport(messages)
    await _client(transport).fetch_series("CRYPTOCAP:TOTAL3", "60", 3)
    assert protocol.encode_frame("~h~1") in transport.sent[4:]


@pytest.mark.asyncio
async def test_connect_failure_is_connect_failed() -> None:
    async def refuse() -> ReplayTransport:
        raise OSError("connection refused")

    client = TradingViewClient(tv_settings(), connector=refuse)
    with pytest.raises(ScraperError) as excinfo:
        await client.fetch_series("CRYPTOCAP:TOTAL3", "60", 6)
    assert excinfo.value.code == errors.CONNECT_FAILED


@pytest.mark.asyncio
async def test_malformed_frame_mid_exchange_is_a_protocol_error_and_closes() -> None:
    transport = ReplayTransport(["not a frame"])
    with pytest.raises(ScraperError) as excinfo:
        await _client(transport).fetch_series("CRYPTOCAP:TOTAL3", "60", 6)
    assert excinfo.value.code == errors.PROTOCOL_ERROR
    assert transport.closed
