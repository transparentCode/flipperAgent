from __future__ import annotations

import json

import pytest

from libs.models.sr_v2.domain.state import create_initial_state
from libs.models.sr_v2.serialization.state_codec import decode_state, encode_state


def test_state_codec_roundtrip_is_byte_identical():
    state = create_initial_state(
        config_fingerprint="config",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    payload = encode_state(state)
    restored = decode_state(payload, expected_config_fingerprint="config")
    assert encode_state(restored) == payload
    assert json.loads(payload) == {
        "active_lineages": [],
        "asset": "BTCUSDT",
        "config_fingerprint": "config",
        "generation": 0,
        "instrument_id": "BTCUSDT",
        "last_trigger_at": None,
                "schema_version": 4,
            "source_cutoffs": {},
            "source_fingerprints": {},
            "source_fingerprint_sequences": {},
        "terminal_tombstones": [],
        "venue": "binance_usdm",
    }


def test_state_codec_rechecks_runtime_identity_and_duplicate_keys():
    state = create_initial_state(
        config_fingerprint="config",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    payload = encode_state(state)
    with pytest.raises(ValueError, match="identity mismatch"):
        decode_state(payload, expected_asset="ETHUSDT")
    duplicate = payload[:-1] + b',"asset":"BTCUSDT"}'
    with pytest.raises(ValueError, match="invalid|duplicate"):
        decode_state(duplicate)


def test_state_codec_rejects_legacy_mapping_event_fields():
    state = create_initial_state(
        config_fingerprint="config",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    raw = json.loads(encode_state(state))
    raw["lifecycle_events"] = []
    with pytest.raises(ValueError, match="schema keys"):
        decode_state(json.dumps(raw, sort_keys=True, separators=(",", ":")))
