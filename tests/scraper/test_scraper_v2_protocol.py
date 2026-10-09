"""Frame codec and message parsing against the recorded exchanges."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from scraper_v2_support import FIXTURE_DIR, SESSION, load_fixture

from apps.scraper_app.adapters.tradingview import protocol
from apps.scraper_app.adapters.tradingview.protocol import SeriesAccumulator
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError

FIXTURE_NAMES = sorted(
    p.stem for p in FIXTURE_DIR.glob("*.json") if p.stem != "canonical_names"
)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_recorded_frame_decodes(name: str) -> None:
    fixture = load_fixture(name)
    for raw in fixture["received"]:
        for message in protocol.decode_message(raw):
            assert message.heartbeat or message.body is not None
    for raw in fixture["sent"]:
        decoded = protocol.decode_message(raw)
        assert len(decoded) == 1
        assert decoded[0].method in {
            "set_auth_token",
            "chart_create_session",
            "resolve_symbol",
            "create_series",
        }


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_built_requests_reproduce_the_recorded_sent_frames(name: str) -> None:
    fixture = load_fixture(name)
    resolution = fixture["sent"][3]
    create = protocol.decode_message(resolution)[0].params
    built = protocol.build_requests(
        SESSION, fixture["requested_symbol"], create[4], fixture["n_bars"]
    )
    assert built == fixture["sent"]


def test_a_message_can_carry_several_frames() -> None:
    raw = protocol.encode_frame('{"m":"a","p":[]}') + protocol.encode_frame("~h~7")
    assert protocol.split_frames(raw) == ['{"m":"a","p":[]}', "~h~7"]
    fixture = load_fixture("index_total3_1h")
    methods = [m.method for m in protocol.decode_message(fixture["received"][1])]
    assert methods == [
        "series_loading",
        "symbol_resolved",
        "timescale_update",
        "series_completed",
    ]


def test_heartbeat_is_echoed_unchanged() -> None:
    (message,) = protocol.decode_message(protocol.encode_frame("~h~42"))
    assert message.heartbeat
    assert protocol.heartbeat_reply(message) == "~m~5~m~~h~42"


@pytest.mark.parametrize(
    "raw",
    ["garbage", "~m~5~m~ab", "~m~x~m~{}", "~m~2~m~{}trailing", "~m~3~m~{no"],
)
def test_malformed_frames_are_protocol_errors(raw: str) -> None:
    with pytest.raises(ScraperError) as excinfo:
        protocol.decode_message(raw)
    assert excinfo.value.code == errors.PROTOCOL_ERROR


def test_accumulator_returns_exact_decimals_and_provider_time() -> None:
    acc = SeriesAccumulator()
    fixture = load_fixture("funding_btc_1h")
    for raw in fixture["received"]:
        for message in protocol.decode_message(raw):
            acc.feed(message)
    result = acc.result()
    assert result.pro_name == "BINANCE:BTCUSDT.P_FR"
    assert result.provider_time == 1791526666
    assert result.bars[0].time == 1791507600
    assert result.bars[0].fields[0] == Decimal("0.00002947")
    assert [b.time for b in result.bars] == sorted(b.time for b in result.bars)


def test_index_bars_carry_six_values_and_derivative_bars_five() -> None:
    def value_counts(name: str) -> set[int]:
        acc = SeriesAccumulator()
        for raw in load_fixture(name)["received"]:
            for message in protocol.decode_message(raw):
                acc.feed(message)
        return {len(b.fields) + 1 for b in acc.result().bars}

    assert value_counts("index_total3_1h") == {6}
    assert value_counts("oi_btc_alias_1h") == {5}
    assert value_counts("funding_btc_1h") == {5}


def test_error_frames_raise_the_first_error() -> None:
    acc = SeriesAccumulator()
    fixture = load_fixture("invalid_symbol")
    with pytest.raises(ScraperError) as excinfo:
        for raw in fixture["received"]:
            for message in protocol.decode_message(raw):
                acc.feed(message)
    assert excinfo.value.code == errors.SYMBOL_ERROR


@pytest.mark.parametrize(
    ("method", "code"),
    [
        ("series_error", errors.SERIES_ERROR),
        ("critical_error", errors.PROTOCOL_ERROR),
        ("protocol_error", errors.PROTOCOL_ERROR),
    ],
)
def test_each_error_method_maps_to_its_code(method: str, code: str) -> None:
    acc = SeriesAccumulator()
    (message,) = protocol.decode_message(
        protocol.encode_frame(json.dumps({"m": method, "p": [SESSION, "x", "boom"]}))
    )
    with pytest.raises(ScraperError) as excinfo:
        acc.feed(message)
    assert excinfo.value.code == code


def test_result_requires_resolution_completion_bars_and_provider_time() -> None:
    def feed(*payloads: dict) -> SeriesAccumulator:
        acc = SeriesAccumulator()
        for payload in payloads:
            (message,) = protocol.decode_message(
                protocol.encode_frame(json.dumps(payload))
            )
            acc.feed(message)
        return acc

    hello = {"timestamp": 1000}
    resolved = {
        "m": "symbol_resolved",
        "p": [SESSION, "sds_sym_1", {"pro_name": "A:B"}],
    }
    bars = {
        "m": "timescale_update",
        "p": [SESSION, {"sds_1": {"s": [{"i": 0, "v": [3600, 1, 2, 0, 1]}]}}],
    }
    done = {"m": "series_completed", "p": [SESSION, "sds_1", "streaming", "s1"]}

    assert feed(hello, resolved, bars, done).result().pro_name == "A:B"
    with pytest.raises(ScraperError) as no_done:
        feed(hello, resolved, bars).result()
    assert no_done.value.code == errors.INCOMPLETE
    with pytest.raises(ScraperError) as no_resolved:
        feed(hello, bars, done).result()
    assert no_resolved.value.code == errors.INCOMPLETE
    with pytest.raises(ScraperError) as no_bars:
        feed(hello, resolved, done).result()
    assert no_bars.value.code == errors.EMPTY
    with pytest.raises(ScraperError) as no_time:
        feed(resolved, bars, done).result()
    assert no_time.value.code == errors.PROTOCOL_ERROR


def test_other_series_ids_are_ignored_and_same_time_last_wins() -> None:
    acc = SeriesAccumulator()
    payloads = [
        {
            "m": "timescale_update",
            "p": [SESSION, {"sds_2": {"s": [{"i": 0, "v": [7200, 9, 9, 9, 9]}]}}],
        },
        {
            "m": "timescale_update",
            "p": [SESSION, {"sds_1": {"s": [{"i": 0, "v": [3600, 1, 2, 0, 1]}]}}],
        },
        {
            "m": "timescale_update",
            "p": [SESSION, {"sds_1": {"s": [{"i": 0, "v": [3600, 5, 6, 4, 5]}]}}],
        },
    ]
    for payload in payloads:
        (message,) = protocol.decode_message(protocol.encode_frame(json.dumps(payload)))
        acc.feed(message)
    assert [(b.time, b.fields[0]) for b in acc._bars.values()] == [(3600, Decimal(5))]


@pytest.mark.parametrize("bad", ['"x"', "true", "null", "[]"])
def test_non_numeric_or_missing_bar_values_are_protocol_errors(bad: str) -> None:
    acc = SeriesAccumulator()
    raw = protocol.encode_frame(
        f'{{"m":"timescale_update","p":["{SESSION}",{{"sds_1":{{"s":[{{"i":0,"v":[3600,{bad},2,0,1]}}]}}}}]}}'
    )
    (message,) = protocol.decode_message(raw)
    with pytest.raises(ScraperError) as excinfo:
        acc.feed(message)
    assert excinfo.value.code == errors.PROTOCOL_ERROR
