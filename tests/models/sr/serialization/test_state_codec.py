from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from libs.models.sr.domain import (
    ClosedBar,
    ContractValidationError,
    SR_SCHEMA_VERSION,
    SREventType,
    SRState,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
    deterministic_hash,
)
from libs.models.sr.serialization import decode_state, encode_state


_T0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
_HASH = "a" * 64


def _key() -> SRStateKey:
    return SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")


def _bar(
    *,
    bar_id: str = "bar-1",
    closed_at: datetime = _T0,
    atr_at_close: float = 1.25,
) -> ClosedBar:
    return ClosedBar(
        state_key=_key(),
        bar_id=bar_id,
        closed_at=closed_at,
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        atr_at_close=atr_at_close,
    )


def _state(
    *,
    status: ZoneStatus = ZoneStatus.ACTIVE,
    half_width: float = 0.0,
) -> SRState:
    definition = ZoneDefinition(
        state_key=_key(),
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.0, half_width=half_width),
        source="codec-test",
        created_at=_T0,
        available_at=_T0,
        atr_at_creation=1.5,
        config_hash=_HASH,
    )
    pending_breach_count = 1 if status is ZoneStatus.BREACH_PENDING else 0
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=status,
        touch_count=3,
        fakeout_count=2,
        pending_breach_count=pending_breach_count,
        age_bars=4,
        last_interaction_at=_T0 if status is ZoneStatus.BREACH_PENDING else None,
        updated_at=_T0,
    )
    return SRState(
        schema_version=SR_SCHEMA_VERSION,
        state_key=_key(),
        config_hash=_HASH,
        last_processed_bar="bar-1",
        zones=(ZoneRecord(definition=definition, runtime=runtime),),
        recent_bars=(_bar(),),
    )


def _initial_state() -> SRState:
    return SRState(
        schema_version=SR_SCHEMA_VERSION,
        state_key=_key(),
        config_hash=_HASH,
        last_processed_bar=None,
        zones=(),
        recent_bars=(),
    )


def _object(payload: str) -> dict:
    return json.loads(payload)


def _dump(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_empty_initial_state_round_trip() -> None:
    state = _initial_state()

    payload = encode_state(state)

    assert decode_state(payload) == state
    assert "events" not in payload
    assert "snapshots" not in payload


@pytest.mark.parametrize(
    "status",
    [
        ZoneStatus.ACTIVE,
        ZoneStatus.BREACH_PENDING,
        ZoneStatus.BROKEN,
        ZoneStatus.EXPIRED,
    ],
)
@pytest.mark.parametrize("half_width", [0.0, 5.0])
def test_zone_status_and_geometry_round_trip(
    status: ZoneStatus,
    half_width: float,
) -> None:
    state = _state(status=status, half_width=half_width)

    decoded = decode_state(encode_state(state))

    assert decoded == state
    assert decoded.zones[0].definition.zone_id == state.zones[0].definition.zone_id
    assert decoded.zones[0].runtime.zone_id == state.zones[0].runtime.zone_id
    assert decoded.recent_bars[0].atr_at_close == 1.25


def test_encoding_is_deterministic_and_reencode_is_byte_identical() -> None:
    state = _state(status=ZoneStatus.BREACH_PENDING, half_width=5.0)

    first = encode_state(state)
    second = encode_state(state)
    reencoded = encode_state(decode_state(first))

    assert first == second == reencoded


def test_state_input_remains_unchanged_and_identity_fields_survive() -> None:
    state = _state()
    before = encode_state(state)
    zone_id = state.zones[0].definition.zone_id

    decoded = decode_state(before)

    assert encode_state(state) == before
    assert decoded.zones[0].definition.zone_id == zone_id
    assert decoded.zones[0].runtime.zone_id == zone_id


@pytest.mark.parametrize("field", ["codec_name", "codec_version"])
def test_unknown_codec_identity_or_version_rejected(field: str) -> None:
    data = _object(encode_state(_initial_state()))
    data[field] = "other" if field == "codec_name" else 2

    with pytest.raises(ContractValidationError):
        decode_state(_dump(data))


def test_payload_hash_mismatch_rejected() -> None:
    data = _object(encode_state(_state()))
    data["state"]["recent_bars"][0]["close"] = 103.0

    with pytest.raises(ContractValidationError, match="payload_hash"):
        decode_state(_dump(data))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["state"].pop("config_hash"),
        lambda data: data["state"]["state_key"].update({"unknown": 1}),
        lambda data: data["state"]["zones"][0]["runtime"].pop("status"),
    ],
)
def test_missing_or_unknown_nested_keys_rejected(mutate) -> None:
    data = _object(encode_state(_state()))
    mutate(data)

    with pytest.raises(ContractValidationError, match="keys"):
        decode_state(_dump(data))


def test_duplicate_keys_rejected_recursively() -> None:
    payload = encode_state(_state())
    duplicate = payload.replace(
        '"schema_version":"1.0"',
        '"schema_version":"1.0","schema_version":"1.0"',
        1,
    )

    with pytest.raises(ContractValidationError, match="duplicate JSON key"):
        decode_state(duplicate)


@pytest.mark.parametrize("payload", ["{", "[]", "null", "1", "true"])
def test_malformed_or_wrong_top_level_payload_rejected(payload: str) -> None:
    with pytest.raises(ContractValidationError):
        decode_state(payload)


def test_noncanonical_json_rejected() -> None:
    payload = encode_state(_initial_state())

    with pytest.raises(ContractValidationError, match="canonical"):
        decode_state(" " + payload)


def test_non_utc_timestamp_rejected() -> None:
    data = _object(encode_state(_state()))
    data["state"]["recent_bars"][0]["closed_at"] = (
        "2026-07-15T12:00:00+00:00"
    )

    with pytest.raises(ContractValidationError, match="canonical UTC"):
        decode_state(_dump(data))


def test_invalid_enum_and_boolean_numeric_rejected() -> None:
    invalid_enum = _object(encode_state(_state()))
    invalid_enum["state"]["zones"][0]["runtime"]["status"] = "UNKNOWN"
    with pytest.raises(ContractValidationError):
        decode_state(_dump(invalid_enum))

    invalid_number = _object(encode_state(_state()))
    invalid_number["state"]["recent_bars"][0]["open"] = True
    with pytest.raises(ContractValidationError):
        decode_state(_dump(invalid_number))


def test_nan_and_infinity_rejected() -> None:
    payload = encode_state(_state())
    nan_payload = payload.replace('"open":100.0', '"open":NaN', 1)
    inf_payload = payload.replace('"open":100.0', '"open":Infinity', 1)

    with pytest.raises(ContractValidationError, match="non-finite"):
        decode_state(nan_payload)
    with pytest.raises(ContractValidationError, match="non-finite"):
        decode_state(inf_payload)


def test_forged_stored_zone_id_rejected_even_with_recomputed_payload_hash() -> None:
    data = _object(encode_state(_state()))
    data["state"]["zones"][0]["definition"]["zone_id"] = "b" * 64
    data["payload_hash"] = deterministic_hash(data["state"])

    with pytest.raises(ContractValidationError, match="zone_id"):
        decode_state(_dump(data))


def test_forged_runtime_zone_id_rejected() -> None:
    data = _object(encode_state(_state()))
    data["state"]["zones"][0]["runtime"]["zone_id"] = "b" * 64
    data["payload_hash"] = deterministic_hash(data["state"])

    with pytest.raises(ContractValidationError):
        decode_state(_dump(data))


def test_invalid_timestamp_and_state_key_are_checked_by_domain_boundary() -> None:
    data = _object(encode_state(_state()))
    data["state"]["zones"][0]["definition"]["created_at"] = "bad"
    with pytest.raises(ContractValidationError):
        decode_state(_dump(data))

    data = _object(encode_state(_state()))
    data["state"]["recent_bars"][0]["state_key"]["symbol"] = "ETHUSDT"
    with pytest.raises(ContractValidationError):
        decode_state(_dump(data))


def test_codec_does_not_encode_snapshot_or_event_history() -> None:
    state = _state()
    payload = _object(encode_state(state))

    assert set(payload) == {"codec_name", "codec_version", "payload_hash", "state"}
    assert set(payload["state"]) == {
        "schema_version",
        "state_key",
        "config_hash",
        "last_processed_bar",
        "zones",
        "recent_bars",
    }
    assert SREventType.CREATED.value not in encode_state(state)


def test_timestamp_microseconds_are_preserved() -> None:
    state = _state()
    precise_bar = _bar(
        closed_at=_T0 + timedelta(microseconds=123456),
    )
    precise_state = SRState(
        schema_version=state.schema_version,
        state_key=state.state_key,
        config_hash=state.config_hash,
        last_processed_bar=precise_bar.bar_id,
        zones=state.zones,
        recent_bars=(precise_bar,),
    )

    decoded = decode_state(encode_state(precise_state))

    assert decoded.recent_bars[0].closed_at == precise_bar.closed_at
