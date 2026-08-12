from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from scripts import certify_ingestion_retention_recovery_n2c as certification


class _Pool:
    def __init__(self, db: int | None = None) -> None:
        self.connection_kwargs = {} if db is None else {"db": db}


class _Client:
    def __init__(self, db: int | None) -> None:
        self.connection_pool = _Pool(db)
        self.flushdb_calls = 0
        self.closed = False

    async def flushdb(self) -> None:
        self.flushdb_calls += 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("uri", "expected_db"),
    [
        ("redis://localhost:6380/15", 15),
    ],
)
def test_db15_uri_resolves_to_logical_db15(
    monkeypatch: pytest.MonkeyPatch,
    uri: str,
    expected_db: int,
) -> None:
    monkeypatch.setattr(certification, "DB15_URI", uri)

    assert certification._validate_db15_uri() == expected_db


@pytest.mark.parametrize(
    "uri",
    [
        "redis://localhost:6380/0",
        "redis://localhost:6380",
    ],
)
def test_non_db15_uri_is_rejected_before_connection(
    monkeypatch: pytest.MonkeyPatch,
    uri: str,
) -> None:
    monkeypatch.setattr(certification, "DB15_URI", uri)

    with pytest.raises(certification.N2CError) as exc_info:
        certification._validate_db15_uri()
    assert exc_info.value.status == "BLOCKED_N2C_VALKEY_ISOLATION"


@pytest.mark.asyncio
async def test_invalid_client_never_calls_flushdb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(db=0)

    async def fake_db15_client() -> _Client:
        return client

    monkeypatch.setattr(certification, "_db15_client", fake_db15_client)

    with pytest.raises(certification.N2CError) as exc_info:
        await certification._db15_recovery(object(), object())

    assert exc_info.value.status == "BLOCKED_N2C_VALKEY_ISOLATION"
    assert client.flushdb_calls == 0
    assert client.closed is True


def test_fixture_publication_ages_are_exact() -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

    old_published_at, recent_published_at = certification._fixture_publication_times(
        now
    )

    assert now - old_published_at == timedelta(days=8)
    assert now - recent_published_at == timedelta(days=6)


@pytest.mark.asyncio
async def test_history_evidence_uses_canonical_signal_pair_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = certification._fresh_manager()

    class _FakeHistoryFetcher:
        def __init__(self, binding: object, *, pool: object) -> None:
            self.binding = binding
            self.pool = pool

        async def __call__(
            self,
            asset: str,
            timeframe: str,
            lookback: int,
        ) -> tuple[object, ...]:
            return tuple(object() for _ in range(lookback))

    monkeypatch.setattr(certification, "IngestionHistoryFetcher", _FakeHistoryFetcher)
    try:
        expected_keys = {
            pair.key
            for pair in certification.SignalPairCatalog(
                config_manager=manager
            ).list_pairs()
            if pair.enabled
        }
        evidence = await certification._history_evidence(object(), manager)

        assert set(evidence) == expected_keys
        assert all(item["returned"] == item["required"] for item in evidence.values())
    finally:
        manager.shutdown()
        certification.ConfigManager.reset_singleton()


@pytest.mark.asyncio
async def test_runtime_quiescence_drains_before_ingestion_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    pending = {"value": 1}

    def fake_compose(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        command = args[0]
        events.append(command)
        if command == "stop":
            assert pending["value"] == 0
        stdout = "ingestion retention cleanup completed" if command == "logs" else ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    async def fake_wait_live(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        events.append("live")
        return {"runtime": {"state": "LIVE"}}

    def fake_post(path: str) -> tuple[int, dict[str, object]]:
        assert path == "/runtime/pause"
        events.append("pause_request")
        return 200, {"desired_state": "paused", "state": "live"}

    def fake_http(path: str) -> tuple[int, dict[str, object]]:
        assert path == "/runtime"
        events.append("paused_poll")
        return 200, {"desired_state": "paused", "state": "stopped"}

    async def fake_wait_pending(pool: object, timeout: float = 180.0) -> dict[str, int]:
        del pool, timeout
        assert events[-1] == "paused_poll"
        events.append("publisher_drain")
        pending["value"] = 0
        return {"total": 1, "pending": 0, "published": 1}

    monkeypatch.setattr(certification, "_compose", fake_compose)
    monkeypatch.setattr(certification, "_wait_ingestion_live", fake_wait_live)
    monkeypatch.setattr(certification, "_http_post", fake_post)
    monkeypatch.setattr(certification, "_http", fake_http)
    monkeypatch.setattr(certification, "_wait_pending_zero", fake_wait_pending)

    async def fake_services() -> dict[str, dict[str, object]]:
        return {
            "broker": {"running": True, "healthy": True},
            "ingestion": {"running": True, "healthy": True},
        }

    monkeypatch.setattr(certification, "_require_runtime_services_alive", fake_services)

    result = await certification._startup_janitor_and_runtime(
        object(), {"broker": {"running": True}}
    )

    assert events == [
        "up",
        "live",
        "pause_request",
        "paused_poll",
        "publisher_drain",
        "logs",
        "stop",
    ]
    assert result["pause"]["paused_runtime"]["runtime"]["state"] == "stopped"
    assert result["pre_stop_outbox"]["pending"] == 0


@pytest.mark.asyncio
async def test_post_stop_pending_check_is_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def pending_state(pool: object) -> dict[str, int]:
        del pool
        return {"total": 1, "pending": 1, "published": 0}

    monkeypatch.setattr(certification, "_pending_state", pending_state)

    with pytest.raises(certification.N2CError, match="not quiescent") as exc_info:
        await certification._assert_pending_zero(object(), phase="runtime_stop")

    assert exc_info.value.evidence["phase"] == "runtime_stop"
