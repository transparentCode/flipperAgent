from __future__ import annotations

import pytest
import valkey

from scripts import retire_legacy_ingestion_n3b as retirement


@pytest.mark.parametrize(
    ("uri", "expected"),
    (
        ("redis://localhost:6380/0", 0),
        ("redis://localhost:6380/15", 15),
        ("redis://localhost:6380", None),
    ),
)
def test_resolved_valkey_db_is_read_from_instantiated_pool(
    uri: str,
    expected: object,
) -> None:
    client = valkey.Valkey.from_url(uri, decode_responses=True)

    assert retirement._resolved_valkey_db(client) == expected


def test_db0_is_accepted_and_db15_or_host_only_is_rejected() -> None:
    db0 = valkey.Valkey.from_url("redis://localhost:6380/0")
    assert retirement._require_production_db0(db0) == 0

    for uri in ("redis://localhost:6380/15", "redis://localhost:6380"):
        client = valkey.Valkey.from_url(uri)
        with pytest.raises(retirement.N3BError, match="DB0") as exc_info:
            retirement._require_production_db0(client)
        assert exc_info.value.status == "BLOCKED_N3B_VALKEY_PROTECTION"


class _FakePool:
    def __init__(self, db: object) -> None:
        self.connection_kwargs = {"db": db}


class _FakeClient:
    def __init__(self, db: object) -> None:
        self.connection_pool = _FakePool(db)
        self.delete_calls = 0

    async def delete(self, *_keys: str) -> int:
        self.delete_calls += 1
        return 1


@pytest.mark.asyncio
async def test_invalid_client_fails_before_legacy_delete() -> None:
    client = _FakeClient(15)

    with pytest.raises(retirement.N3BError) as exc_info:
        await retirement._delete_legacy_keys(client, ["stream:control:ingestion"])

    assert exc_info.value.status == "BLOCKED_N3B_VALKEY_PROTECTION"
    assert client.delete_calls == 0


def test_empty_protected_db15_state_cannot_verify_ready() -> None:
    client = valkey.Valkey.from_url("redis://localhost:6380/15")
    with pytest.raises(retirement.N3BError) as db_error:
        retirement._require_production_db0(client)
    assert db_error.value.status == "BLOCKED_N3B_VALKEY_PROTECTION"

    empty_snapshot = {
        "protected": {
            "asset_keys": {},
            "asset_lifecycle": {"exists": False, "length": 0, "groups": []},
            "ingestion_streams": {},
            "signal_groups": {},
        }
    }
    with pytest.raises(retirement.N3BError) as state_error:
        retirement._assert_protected_ingestion_state(
            empty_snapshot,
            {
                "expected_manifest_keys": ["asset:BTCUSDT"],
                "expected_ingestion_stream_keys": [
                    "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1m"
                ],
            },
        )
    assert state_error.value.status == "BLOCKED_N3B_VALKEY_PROTECTION"


def test_execution_and_verification_artifacts_are_separate() -> None:
    assert retirement.EXECUTE_STATE_ARTIFACT != retirement.VERIFY_STATE_ARTIFACT
    assert retirement.EXECUTE_STATE_ARTIFACT.name == "retirement_execute_state.json"
    assert retirement.VERIFY_STATE_ARTIFACT.name == "retirement_verify_state.json"
