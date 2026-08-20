from __future__ import annotations

import os

import pytest

from apps.decision_app.settings import load_decision_config
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
    LaneEffectProgressSaveResult,
)
from apps.strategy_app.settings import StrategyWorkerSettings
from libs.common.config import ConfigManager
from libs.common.signal_authority import (
    TARGET_SIGNAL_ROUTES,
    SignalAuthorityConflict,
    SignalAuthorityStore,
    SignalRouteAuthority,
    normalize_signal_route,
    signal_authority_key,
    signal_route_from_stream,
)
from libs.contracts.serialization import valkey_encode
from libs.contracts.signal import FeatureVector
from scripts.decision_d11b_authority_cutover import (
    D11BAuthorityController,
    cutback_fast_forward_boundary,
    cutback_fast_forward_group,
    feature_close_cutoff_ms,
    market_bar_identity_fingerprint,
    signal_head_preflight,
    timeframe_duration_ms,
    validate_group_quiescence,
)
from tests.decision.test_d9b_live_runtime import (
    SIGNAL_SERIES,
    _LiveInputClient,
    _signal_bar,
    _signal_coordinator,
    _signal_fields,
)


class _AuthorityReadClient:
    def __init__(self, *, route: str, boundary_ms: int) -> None:
        self.route = route
        self.boundary_ms = boundary_ms

    async def eval(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("startup authority validation must not write")

    async def hgetall(self, key: str) -> dict[str, str]:
        route = key.removeprefix("signal:authority:")
        if route != self.route:
            return {}
        return {
            "schema_version": "1",
            "route": route,
            "owner": "decision",
            "epoch": "1",
            "boundary_ms": str(self.boundary_ms),
        }


def _with_authoritative_handoff(
    coordinator,
    *,
    boundary_ms: int,
):
    coordinator._authority_store = SignalAuthorityStore(  # type: ignore[attr-defined]
        _AuthorityReadClient(route="BTCUSDT:1h", boundary_ms=boundary_ms)
    )
    return coordinator


def test_authority_contract_is_canonical_and_route_scoped() -> None:
    assert TARGET_SIGNAL_ROUTES == (
        "BTCUSDT:1h",
        "BTCUSDT:4h",
        "ETHUSDT:4h",
    )
    with pytest.raises(ValueError):
        normalize_signal_route("btcusdt:1h")
    assert signal_authority_key("BTCUSDT:1h") == "signal:authority:BTCUSDT:1h"
    assert signal_route_from_stream("signals:ETHUSDT:4h") == "ETHUSDT:4h"
    with pytest.raises(ValueError):
        SignalRouteAuthority(
            schema_version=1,
            route="BTCUSDT:1h",
            owner="strategy",
            epoch=0,
            boundary_ms=-1,
        )


def test_legacy_boundary_and_signal_head_preflight_use_close_time() -> None:
    assert timeframe_duration_ms("1h") == 3_600_000
    assert feature_close_cutoff_ms(1_700_000_000_000, "4h") == 1_700_014_400_000
    assert signal_head_preflight(
        "1_700_000_000_000-0",
        boundary_ms=1_700_000_000_000,
        trigger_timeframe="1h",
    )
    assert not signal_head_preflight(
        "1_700_004_000_000-0",
        boundary_ms=1_700_000_000_000,
        trigger_timeframe="1h",
    )


def test_cutback_fast_forward_preserves_only_newer_legacy_cutoffs() -> None:
    result = cutback_fast_forward_boundary(
        [
            {"id": "1-0", "timestamp_ms": 1_700_000_000_000},
            {"id": "2-0", "timestamp_ms": 1_700_003_600_000},
            {"id": "3-0", "timestamp_ms": 1_700_007_200_000},
        ],
        progress_cutoff_ms=1_700_003_600_000,
        timeframe="1h",
    )
    assert result["last_id_through_progress"] == "1-0"
    assert result["next_unread_id"] == "2-0"
    assert result["no_legacy_cutoff_skipped"] is True
    assert result["expected_next_cutoff_ms"] == 1_700_007_200_000
    assert result["first_actual_unread_cutoff_ms"] == 1_700_007_200_000


def test_cutback_fast_forward_rejects_a_trimmed_interval() -> None:
    result = cutback_fast_forward_boundary(
        [
            {"id": "1-0", "timestamp_ms": 1_700_000_000_000},
            {"id": "3-0", "timestamp_ms": 1_700_007_200_000},
        ],
        progress_cutoff_ms=1_700_003_600_000,
        timeframe="1h",
    )
    assert result["no_legacy_cutoff_skipped"] is False


def _cutback_entry(
    entry_id: str,
    cutoff_ms: int,
    *,
    bar_close: float = 100.0,
    features: dict[str, object] | None = None,
) -> dict[str, object]:
    entry = {
        "id": entry_id,
        "timestamp_ms": cutoff_ms - 3_600_000,
        "asset": "BTCUSDT",
        "timeframe": "1h",
        "bar_data": {
            "open": bar_close,
            "high": bar_close + 1.0,
            "low": bar_close - 1.0,
            "close": bar_close,
            "volume": 10.0,
        },
        "features": features or {},
    }
    entry["bar_identity_fingerprint"] = market_bar_identity_fingerprint(entry)
    return entry


@pytest.mark.parametrize(
    ("cutoffs", "progress", "expected", "expected_setid"),
    [
        ([0, 0, 3_600_000], 0, True, "2-0"),
        ([0, 0, 0, 3_600_000], 0, True, "3-0"),
        ([0, 0, 3_600_000, 7_200_000], 3_600_000, True, "3-0"),
        ([0, 0, 7_200_000], 0, False, "2-0"),
        ([0, 3_600_000, 0], 0, False, "3-0"),
        ([0, 3_600_000, 3_600_000], 0, False, "1-0"),
    ],
)
def test_cutback_logical_runs_validate_duplicates_and_continuity(
    cutoffs: list[int],
    progress: int,
    expected: bool,
    expected_setid: str,
) -> None:
    result = cutback_fast_forward_boundary(
        [
            _cutback_entry(f"{index}-0", 1_700_000_000_000 + cutoff)
            for index, cutoff in enumerate(cutoffs, 1)
        ],
        progress_cutoff_ms=1_700_000_000_000 + progress,
        timeframe="1h",
    )
    assert result["no_legacy_cutoff_skipped"] is expected
    assert result["last_id_through_progress"] == expected_setid


def test_cutback_requires_exact_progress_cutoff() -> None:
    result = cutback_fast_forward_boundary(
        [_cutback_entry("1-0", 1_700_000_000_000)],
        progress_cutoff_ms=1_700_003_600_000,
        timeframe="1h",
    )
    assert result["progress_cutoff_present"] is False
    assert result["no_legacy_cutoff_skipped"] is False


def test_cutback_rejects_conflicting_same_cutoff_market_bars() -> None:
    result = cutback_fast_forward_boundary(
        [
            _cutback_entry("1-0", 1_700_000_000_000),
            _cutback_entry("2-0", 1_700_000_000_000, bar_close=101.0),
            _cutback_entry("3-0", 1_700_003_600_000),
        ],
        progress_cutoff_ms=1_700_000_000_000,
        timeframe="1h",
    )
    assert result["market_bar_duplicate_identity_consistent"] is False
    assert result["no_legacy_cutoff_skipped"] is False


def test_cutback_ignores_feature_recomputation_inside_decision_owned_run() -> None:
    first = _cutback_entry("1-0", 1_700_000_000_000, features={"rsi": 40.0})
    second = _cutback_entry("2-0", 1_700_000_000_000, features={"rsi": 60.0})
    result = cutback_fast_forward_boundary(
        [first, second, _cutback_entry("3-0", 1_700_003_600_000)],
        progress_cutoff_ms=1_700_000_000_000,
        timeframe="1h",
    )
    assert result["market_bar_duplicate_identity_consistent"] is True
    assert result["no_legacy_cutoff_skipped"] is True


class _CutbackGroupClient:
    def __init__(self, entries: list[tuple[str, dict[str, str]]], anchor: str):
        self.entries = entries
        self.group = {
            "name": "strategy_app_group",
            "pending": 0,
            "lag": 0,
            "last-delivered-id": anchor,
        }
        self.setid: str | None = None

    async def xinfo_groups(self, _stream_key: str):
        return [self.group]

    async def xrange(self, _stream_key: str, _start: str, _end: str):
        return self.entries

    async def xgroup_setid(self, _stream_key: str, _group_name: str, value: str):
        self.setid = value
        self.group["last-delivered-id"] = value


@pytest.mark.asyncio
async def test_real_cutback_selects_last_duplicate_id_and_preserves_anchor() -> None:
    base = 1_700_000_000_000
    vectors = [
        FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=base - 3_600_000,
            bar_data={
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10.0,
            },
        )
        for _ in range(3)
    ]
    client = _CutbackGroupClient(
        [
            (f"{index}-0", valkey_encode(vector))
            for index, vector in enumerate(vectors, 1)
        ],
        "1-0",
    )
    result = await cutback_fast_forward_group(
        client,
        stream_key="features:BTCUSDT:1h",
        group_name="strategy_app_group",
        progress_cutoff_ms=base,
        timeframe="1h",
    )
    assert client.setid == "3-0"
    assert result["setid"] == "3-0"
    assert result["anchor_retained"] is True


@pytest.mark.asyncio
async def test_real_cutback_blocks_when_group_anchor_was_trimmed() -> None:
    vector = FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000_000,
        bar_data={"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
    )
    client = _CutbackGroupClient(
        [("2-0", valkey_encode(vector))],
        "1-0",
    )
    with pytest.raises(RuntimeError, match="cannot prove the group anchor"):
        await cutback_fast_forward_group(
            client,
            stream_key="features:BTCUSDT:1h",
            group_name="strategy_app_group",
            progress_cutoff_ms=1_700_003_600_000,
            timeframe="1h",
        )


def test_group_quiescence_is_fail_closed() -> None:
    assert validate_group_quiescence(pel_count=0, lag=0)
    assert not validate_group_quiescence(pel_count=1, lag=0)
    assert not validate_group_quiescence(pel_count=0, lag=1)


def test_production_decision_assets_match_m4_route_identity() -> None:
    ConfigManager.reset_singleton()
    manager = ConfigManager()
    try:
        config = load_decision_config(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()
    lanes = {lane.lane_id: lane for lane in config.lane_specs()}
    assert set(lanes) == {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    }
    assert all(lane.authority == "authoritative" for lane in lanes.values())
    assert {lane.risk_profile_key for lane in lanes.values()} == {
        "m4-btc-1h",
        "m4-btc-4h",
        "m4-eth-4h",
    }


@pytest.mark.asyncio
async def test_authoritative_startup_blocks_when_handoff_progress_is_missing() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))}
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    coordinator = _with_authoritative_handoff(
        _signal_coordinator(
            history,
            stream,
            authority="authoritative",
            shadow_progress_repository=InMemoryLaneEffectProgressRepository(),
        ),
        boundary_ms=int(_signal_bar(2).market_as_of.timestamp() * 1000),
    )

    startup = await coordinator.start()

    assert startup.snapshot.status == "STARTUP_BLOCKED"
    assert startup.runtimes == {}
    assert startup.snapshot.lane_watermarks == {}
    assert startup.snapshot.lane_evidence["BTCUSDT:main"].status == "BLOCKED"


@pytest.mark.asyncio
async def test_authoritative_startup_blocks_when_handoff_progress_is_behind() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))}
    )
    baseline_stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    baseline = await _signal_coordinator(
        history,
        baseline_stream,
        authority="authoritative",
        shadow_progress_repository=InMemoryLaneEffectProgressRepository(),
    ).start()
    identity = next(iter(baseline.runtimes.values())).identity
    progress = InMemoryLaneEffectProgressRepository()
    assert (
        await progress.save(
            LaneEffectProgress.create(
                identity=identity,
                market_as_of=_signal_bar(1).market_as_of,
                last_disposition=None,
            )
        )
        == LaneEffectProgressSaveResult.INSERTED
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    coordinator = _with_authoritative_handoff(
        _signal_coordinator(
            history,
            stream,
            authority="authoritative",
            shadow_progress_repository=progress,
        ),
        boundary_ms=int(_signal_bar(2).market_as_of.timestamp() * 1000),
    )

    startup = await coordinator.start()

    assert startup.snapshot.status == "STARTUP_BLOCKED"
    assert startup.runtimes == {}
    assert startup.snapshot.lane_watermarks == {}
    assert startup.snapshot.lane_evidence["BTCUSDT:main"].status == "BLOCKED"


@pytest.mark.asyncio
async def test_real_authority_cas_and_guarded_xadd() -> None:
    uri = os.environ.get("D11B_VALKEY_URI")
    if not uri:
        pytest.skip("set D11B_VALKEY_URI for the disposable real Valkey proof")
    import valkey.asyncio as valkey

    from libs.common.signal_authority import SignalAuthorityStore

    client = valkey.Valkey.from_url(uri, decode_responses=True)
    try:
        await client.flushdb()
        store = SignalAuthorityStore(client)
        seeded = await store.seed_strategy()
        assert [record.owner for record in seeded] == ["strategy"] * 3
        with pytest.raises(SignalAuthorityConflict):
            await store.handoff_many(
                routes=TARGET_SIGNAL_ROUTES,
                expected_owner="strategy",
                new_owner="decision",
                expected_epochs={route: 99 for route in TARGET_SIGNAL_ROUTES},
                boundary_ms_by_route={route: 1 for route in TARGET_SIGNAL_ROUTES},
            )
        assert [(await store.read(route)).owner for route in TARGET_SIGNAL_ROUTES] == [
            "strategy"
        ] * 3
        write = await store.guarded_xadd(
            route="BTCUSDT:1h",
            expected_owner="strategy",
            expected_epoch=0,
            expected_boundary_ms=0,
            effect_cutoff_ms=1_700_000_000_001,
            stream_key="signals:BTCUSDT:1h",
            fields={"idempotency_key": "authority-test"},
            stream_id="*",
            maxlen=100,
            approximate=True,
        )
        assert write.allowed and write.managed and write.stream_id
        records = await store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs={route: 0 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route={
                route: 1_700_000_000_000 for route in TARGET_SIGNAL_ROUTES
            },
        )
        assert [record.owner for record in records] == ["decision"] * 3
        denied = await store.guarded_xadd(
            route="BTCUSDT:1h",
            expected_owner="strategy",
            expected_epoch=0,
            expected_boundary_ms=0,
            effect_cutoff_ms=1_700_000_000_001,
            stream_key="signals:BTCUSDT:1h",
            fields={"idempotency_key": "stale"},
            stream_id="*",
            maxlen=100,
            approximate=True,
        )
        assert not denied.allowed
        exact_id = "1700000001000-0"
        exact_fields = {"idempotency_key": "authority-exact-test"}
        exact = await store.guarded_exact_xadd(
            route="BTCUSDT:1h",
            expected_owner="decision",
            expected_epoch=1,
            expected_boundary_ms=1_700_000_000_000,
            effect_cutoff_ms=1_700_000_001_000,
            stream_key="signals:BTCUSDT:1h",
            stream_id=exact_id,
            fields=exact_fields,
            maxlen=100,
            approximate=False,
        )
        assert exact.allowed and exact.outcome == "PUBLISHED"
        await store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="decision",
            new_owner="strategy",
            expected_epochs={route: 1 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route={
                route: 1_700_000_002_000 for route in TARGET_SIGNAL_ROUTES
            },
        )
        stale_exact = await store.guarded_exact_xadd(
            route="BTCUSDT:1h",
            expected_owner="decision",
            expected_epoch=1,
            expected_boundary_ms=1_700_000_000_000,
            effect_cutoff_ms=1_700_000_001_000,
            stream_key="signals:BTCUSDT:1h",
            stream_id=exact_id,
            fields=exact_fields,
            maxlen=100,
            approximate=False,
        )
        assert not stale_exact.allowed and stale_exact.outcome == "DENIED"
        boundary_equal = await store.guarded_xadd(
            route="BTCUSDT:1h",
            expected_owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=1_700_000_002_000,
            effect_cutoff_ms=1_700_000_002_000,
            stream_key="signals:BTCUSDT:1h",
            fields={"idempotency_key": "boundary-equal"},
            stream_id="*",
            maxlen=100,
            approximate=False,
        )
        assert not boundary_equal.allowed
        current_strategy = await store.guarded_xadd(
            route="BTCUSDT:1h",
            expected_owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=1_700_000_002_000,
            effect_cutoff_ms=1_700_000_002_001,
            stream_key="signals:BTCUSDT:1h",
            fields={"idempotency_key": "strategy-epoch-2"},
            stream_id="*",
            maxlen=100,
            approximate=False,
        )
        assert current_strategy.allowed and current_strategy.stream_id
        await client.xdel("signals:BTCUSDT:1h", current_strategy.stream_id)
        await store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs={route: 2 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route={
                route: 1_700_000_003_000 for route in TARGET_SIGNAL_ROUTES
            },
        )
        stale_strategy_after_recutover = await store.guarded_xadd(
            route="BTCUSDT:1h",
            expected_owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=1_700_000_002_000,
            effect_cutoff_ms=1_700_000_003_001,
            stream_key="signals:BTCUSDT:1h",
            fields={"idempotency_key": "stale-strategy"},
            stream_id="*",
            maxlen=100,
            approximate=False,
        )
        assert not stale_strategy_after_recutover.allowed
    finally:
        await client.flushdb()
        await client.aclose()


def test_boundary_helpers_reject_non_utc_cutoff_shape() -> None:
    from scripts.decision_d11b_authority_cutover import _parse_cutoffs

    with pytest.raises(ValueError):
        _parse_cutoffs({route: "2026-01-01T00:00:00" for route in TARGET_SIGNAL_ROUTES})


def test_strategy_authority_enforcement_is_explicit_and_default_off() -> None:
    assert StrategyWorkerSettings().signal_authority_enforced is False

    class _Config:
        def register_file(self, _path: object) -> None:
            return None

        def get(self, key: str, default: object = None) -> object:
            return (
                True if key == "strategy.runtime.signal_authority_enforced" else default
            )

    assert (
        StrategyWorkerSettings.from_config(_Config()).signal_authority_enforced is True
    )


@pytest.mark.asyncio
async def test_authority_controller_requires_observed_progress_not_boolean_annotations() -> (
    None
):
    controller = D11BAuthorityController(
        SignalAuthorityStore(
            _AuthorityReadClient(route="BTCUSDT:1h", boundary_ms=1_700_000_000_000)
        )
    )
    with pytest.raises(SignalAuthorityConflict, match="live effect-progress"):
        await controller.cutover_to_decision()
