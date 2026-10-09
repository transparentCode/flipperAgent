"""Canonical form and the pure CoinGlass gate."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from scraper_v2_coinglass_support import (
    COLUMNS,
    full_heatmap_text,
    heatmap_spec,
    heatmap_text,
    liqmap_spec,
    liqmap_text,
    maxpain_spec,
    maxpain_text,
    update_time,
)

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.domain.payloads import (
    canonical_hash,
    canonical_json,
    decode_payload,
    encode_payload,
    gate_payload,
    parse_payload_text,
)

NOW = update_time("1429") + timedelta(seconds=20)


def _gate(spec, text, *, now=NOW, max_bytes=5_000_000, age=900):
    return gate_payload(
        spec, text, returned_at=now, max_payload_bytes=max_bytes, max_age_seconds=age
    )


def _code(spec, text, **kw) -> str:
    with pytest.raises(ScraperError) as raised:
        _gate(spec, text, **kw)
    return raised.value.code


def test_numbers_and_key_order_give_one_hash() -> None:
    texts = ['{"a":5,"b":[1.50]}', '{"b":[1.5],"a":5.0}', '{ "a": 5e0, "b": [15e-1] }']
    hashes = {
        canonical_hash(canonical_json(parse_payload_text(t, max_bytes=1000)))
        for t in texts
    }
    assert len(hashes) == 1
    assert canonical_json({"x": Decimal("-0.0")}) == '{"x":0}'


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_literals_are_rejected(literal: str) -> None:
    with pytest.raises(ScraperError) as raised:
        parse_payload_text(f'{{"a":[{literal}]}}', max_bytes=1000)
    assert raised.value.code == errors.PAYLOAD_INVALID


def test_gzip_roundtrip_is_deterministic() -> None:
    text = _gate(heatmap_spec(), heatmap_text()).text
    assert encode_payload(text) == encode_payload(text)
    assert decode_payload(encode_payload(text)) == text


def test_three_recorded_heatmaps_and_the_full_one_pass() -> None:
    for name in ("1429", "1432", "1436"):
        accepted = _gate(heatmap_spec(), heatmap_text(name), now=update_time(name))
        assert accepted.bars_seen == COLUMNS and accepted.holes == 0
        assert accepted.covered_from < accepted.covered_to
    full = _gate(
        heatmap_spec(
            expect=heatmap_spec().expect.__class__("Binance", "BTCUSDT", 300, 288)
        ),
        full_heatmap_text(),
    )
    assert full.bars_seen == 288
    assert len(encode_payload(full.text)) < full.raw_bytes / 4
    accepted = _gate(maxpain_spec(), maxpain_text())
    assert accepted.provider_time is None
    assert accepted.covered_from == accepted.covered_to == NOW


def _mutated(fn) -> str:
    data = json.loads(heatmap_text())
    fn(data)
    return json.dumps(data)


HEATMAP_CASES = {
    "non_zero_code": (
        lambda d: d.update(code="500", success=False),
        errors.PROVIDER_REFUSED,
    ),
    "not_authorized": (
        lambda d: d.update(code="40000", success=False),
        errors.NOT_AUTHORIZED,
    ),
    "instrument": (
        lambda d: d["data"]["instrument"].update(instrumentId="ETHUSDT"),
        errors.IDENTITY_MISMATCH,
    ),
    "misaligned": (
        lambda d: d["data"]["prices"][3].__setitem__(0, d["data"]["prices"][3][0] + 7),
        errors.PAYLOAD_INVALID,
    ),
    "not_ascending": (lambda d: d["data"]["prices"].reverse(), errors.PAYLOAD_INVALID),
    "index_out_of_range": (
        lambda d: d["data"]["liq"].append([COLUMNS, 0, 1]),
        errors.PAYLOAD_INVALID,
    ),
    "negative": (
        lambda d: d["data"]["liq"].append([0, 0, -1]),
        errors.DOMAIN_VIOLATION,
    ),
    "y_not_ascending": (lambda d: d["data"]["y"].reverse(), errors.PAYLOAD_INVALID),
    "too_many_columns": (
        lambda d: d["data"]["prices"].append(d["data"]["prices"][-1]),
        errors.PAYLOAD_INVALID,
    ),
}


@pytest.mark.parametrize("name", sorted(HEATMAP_CASES))
def test_heatmap_gate_matrix(name: str) -> None:
    mutate, code = HEATMAP_CASES[name]
    assert _code(heatmap_spec(), _mutated(mutate)) == code


def test_non_finite_value_in_a_payload_is_rejected() -> None:
    text = heatmap_text().replace('"liq":[[', '"liq":[[0,0,NaN],[', 1)
    assert _code(heatmap_spec(), text) == errors.PAYLOAD_INVALID


def test_stale_and_future_update_time() -> None:
    assert (
        _code(heatmap_spec(), heatmap_text(), now=NOW + timedelta(hours=1))
        == errors.STALE_PAYLOAD
    )
    assert (
        _code(heatmap_spec(), heatmap_text(), now=NOW - timedelta(hours=1))
        == errors.PAYLOAD_INVALID
    )


def test_holes_are_counted() -> None:
    def drop(d):
        del d["data"]["prices"][5]
        d["data"]["liq"] = [c for c in d["data"]["liq"] if c[0] < 5]

    assert _gate(heatmap_spec(), _mutated(drop)).holes == 1


def test_max_pain_matrix() -> None:
    def data(fn) -> str:
        d = json.loads(maxpain_text())
        fn(d)
        return json.dumps(d)

    assert (
        _code(maxpain_spec(), data(lambda d: d["data"].pop(1))) == errors.COIN_MISSING
    )
    assert (
        _code(
            maxpain_spec(),
            data(lambda d: d["data"].append(copy.deepcopy(d["data"][0]))),
        )
        == errors.PAYLOAD_INVALID
    )
    assert (
        _code(maxpain_spec(), data(lambda d: d["data"][0].update(price=0)))
        == errors.DOMAIN_VIOLATION
    )
    assert (
        _code(maxpain_spec(), data(lambda d: d["data"][0].update(price=-5)))
        == errors.DOMAIN_VIOLATION
    )
    assert (
        _code(maxpain_spec(), data(lambda d: d.update(code="40000", success=False)))
        == errors.NOT_AUTHORIZED
    )


def test_oversize_is_rejected_before_parsing() -> None:
    assert (
        _code(heatmap_spec(), heatmap_text(), max_bytes=1000)
        == errors.PAYLOAD_TOO_LARGE
    )
    assert _code(heatmap_spec(), "{not json") == errors.PAYLOAD_INVALID


def _liqmap(fn) -> str:
    data = json.loads(liqmap_text())
    fn(data)
    return json.dumps(data)


def _first_rows(d):
    return next(iter(d["data"]["liqMapV2"].values()))


def test_recorded_liq_maps_pass_with_instant_bounds() -> None:
    accepted = _gate(liqmap_spec(), liqmap_text())
    assert accepted.provider_time is None
    assert accepted.covered_from == accepted.covered_to == NOW
    assert accepted.bars_seen == 174
    eth = liqmap_spec(expect=liqmap_spec().expect.__class__("Binance", "ETHUSDT"))
    assert _gate(eth, liqmap_text("eth")).bars_seen == 167


LIQMAP_CASES = {
    "non_zero_code": (
        lambda d: d.update(code="500", success=False),
        errors.PROVIDER_REFUSED,
    ),
    "not_authorized": (
        lambda d: d.update(code="40000", success=False),
        errors.NOT_AUTHORIZED,
    ),
    "instrument": (
        lambda d: d["data"]["instrument"].update(instrumentId="ETHUSDT"),
        errors.IDENTITY_MISMATCH,
    ),
    "empty_map": (lambda d: d["data"].update(liqMapV2={}), errors.PAYLOAD_INVALID),
    "bad_key": (
        lambda d: d["data"]["liqMapV2"].update({"abc": [[1, 1, 10, "h1"]]}),
        errors.PAYLOAD_INVALID,
    ),
    "three_fields": (
        lambda d: _first_rows(d).append([1, 1, 10]),
        errors.PAYLOAD_INVALID,
    ),
    "negative_value": (
        lambda d: _first_rows(d).append([1, -1, 10, "h1"]),
        errors.DOMAIN_VIOLATION,
    ),
    "fractional_leverage": (
        lambda d: _first_rows(d).append([1, 1, 10.5, "h1"]),
        errors.PAYLOAD_INVALID,
    ),
    "empty_tier": (
        lambda d: _first_rows(d).append([1, 1, 10, ""]),
        errors.PAYLOAD_INVALID,
    ),
    "last_price_zero": (
        lambda d: d["data"].update(lastPrice=0),
        errors.DOMAIN_VIOLATION,
    ),
}


@pytest.mark.parametrize("name", sorted(LIQMAP_CASES))
def test_liq_map_gate_matrix(name: str) -> None:
    mutate, code = LIQMAP_CASES[name]
    assert _code(liqmap_spec(), _liqmap(mutate)) == code
