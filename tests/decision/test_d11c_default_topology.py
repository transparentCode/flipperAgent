from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml
from valkey.exceptions import ConnectionError as ValkeyConnectionError
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.strategy_app.runtime.runner import StrategyRuntimeRunner
from apps.strategy_app.settings import StrategyWorkerSettings
from apps.strategy_app.state import StrategyPair
from libs.common.signal_authority import (
    TARGET_SIGNAL_ROUTES,
    SignalAuthorityError,
    SignalRouteAuthority,
)
from scripts.certify_decision_d11c_default_topology import exit_code_for_status
from tests.combined.d11c_harness import (
    ARTIFACT_PATH,
    BLOCKED_STATUS,
    SUCCESS_STATUS,
    evaluate_artifact,
)

ROOT = Path(__file__).resolve().parents[2]
_UNSET = object()


class _Config:
    def __init__(self, value: object = _UNSET) -> None:
        self.value = value

    def register_file(self, _path: object) -> None:
        return None

    def get(self, key: str, default: object = None) -> object:
        if key == "strategy.runtime.signal_authority_enforced":
            return default if self.value is _UNSET else self.value
        return default


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_signal_authority_enforced_rejects_non_yaml_bools(value: object) -> None:
    with pytest.raises(TypeError, match="YAML bool"):
        StrategyWorkerSettings.from_config(_Config(value))


@pytest.mark.parametrize("value", [True, False])
def test_signal_authority_enforced_accepts_yaml_bools(value: bool) -> None:
    settings = StrategyWorkerSettings.from_config(_Config(value))
    assert settings.signal_authority_enforced is value


def test_signal_authority_enforced_absent_defaults_off() -> None:
    settings = StrategyWorkerSettings.from_config(_Config())
    assert settings.signal_authority_enforced is False


class _FakeRedis:
    async def hgetall(self, _key: str) -> dict[str, str]:
        return {}

    async def hset(self, *_args: object, **_kwargs: object) -> int:
        return 1

    async def delete(self, *_keys: str) -> int:
        return 1


class _StubWorker:
    created: ClassVar[list[_StubWorker]] = []

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        settings: StrategyWorkerSettings,
        authority_store: object | None = None,
        **_kwargs: object,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.settings = settings
        self.authority_store = authority_store
        self.stopped = asyncio.Event()
        type(self).created.append(self)

    async def connect(self, _redis: object) -> None:
        return None

    async def start(self) -> None:
        await self.stopped.wait()


class _AuthorityAdmission:
    def __init__(self, records: dict[str, object]) -> None:
        self.records = records

    def manages(self, route: str) -> bool:
        return route in TARGET_SIGNAL_ROUTES

    async def read(self, route: str) -> SignalRouteAuthority | None:
        value = self.records.get(route)
        if isinstance(value, BaseException):
            raise value
        return value  # type: ignore[return-value]


class _BindFailWorker(_StubWorker):
    fail_route: ClassVar[str | None] = None

    async def connect(self, redis_client: object) -> None:
        route = f"{self.asset}:{self.timeframe}"
        if route == self.fail_route:
            raise ValkeyTimeoutError("authority changed during bind")
        await super().connect(redis_client)


class _StartAuthorityFailWorker(_StubWorker):
    fail_route: ClassVar[str | None] = None

    async def start(self) -> None:
        route = f"{self.asset}:{self.timeframe}"
        if route == self.fail_route:
            raise SignalAuthorityError("owner changed after admission")
        await super().start()


class _ConnectValueErrorWorker(_StubWorker):
    error_text: ClassVar[str] = "worker connect defect"

    async def connect(self, _redis: object) -> None:
        raise ValueError(self.error_text)


def _authority(route: str, owner: str) -> SignalRouteAuthority:
    return SignalRouteAuthority(
        schema_version=1,
        route=route,
        owner=owner,  # type: ignore[arg-type]
        epoch=0,
        boundary_ms=0,
    )


def _pair(route: str) -> StrategyPair:
    asset, timeframe = route.split(":")
    return StrategyPair(asset=asset, timeframe=timeframe)


@pytest.mark.asyncio
async def test_authority_admission_keeps_unrelated_and_strategy_owned_routes() -> None:
    _StubWorker.created = []
    records = {
        "BTCUSDT:1h": _authority("BTCUSDT:1h", "strategy"),
        "BTCUSDT:4h": _authority("BTCUSDT:4h", "decision"),
        "ETHUSDT:4h": None,
    }
    runner = StrategyRuntimeRunner(
        [_pair(route) for route in (*TARGET_SIGNAL_ROUTES, "XRPUSDT:1h")],
        worker_factory=_StubWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=_AuthorityAdmission(records),  # type: ignore[arg-type]
    )

    workers = await runner.connect(_FakeRedis())

    assert {f"{worker.asset}:{worker.timeframe}" for worker in workers} == {
        "BTCUSDT:1h",
        "XRPUSDT:1h",
    }
    assert all(worker.authority_store is not None for worker in workers)
    await runner.stop()


@pytest.mark.asyncio
async def test_authority_admission_stops_existing_worker_after_owner_change() -> None:
    _StubWorker.created = []
    route = "BTCUSDT:1h"
    authority = _AuthorityAdmission({route: _authority(route, "strategy")})
    pair = _pair(route)
    runner = StrategyRuntimeRunner(
        [pair],
        worker_factory=_StubWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=authority,  # type: ignore[arg-type]
    )
    await runner.connect(_FakeRedis())
    assert pair.key in runner._worker_tasks

    authority.records[route] = _authority(route, "decision")
    assert await runner._ensure_pair_started(pair) is None
    assert pair.key not in runner._worker_tasks
    await runner.stop()


@pytest.mark.asyncio
async def test_corrupt_authority_blocks_only_managed_route() -> None:
    _StubWorker.created = []
    route = "ETHUSDT:4h"
    authority = _AuthorityAdmission(
        {route: SignalAuthorityError("malformed authority record")}
    )
    runner = StrategyRuntimeRunner(
        [_pair(route), _pair("BNBUSDT:30m")],
        worker_factory=_StubWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=authority,  # type: ignore[arg-type]
    )

    workers = await runner.connect(_FakeRedis())

    assert [(worker.asset, worker.timeframe) for worker in workers] == [
        ("BNBUSDT", "30m")
    ]
    await runner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [ValkeyTimeoutError("authority timeout"), ValkeyConnectionError("authority down")],
)
async def test_valkey_authority_read_failure_keeps_unrelated_route_active(
    failure: BaseException,
) -> None:
    _StubWorker.created = []
    authority = _AuthorityAdmission(
        {
            "BTCUSDT:1h": failure,
        }
    )
    runner = StrategyRuntimeRunner(
        [_pair("BTCUSDT:1h"), _pair("BNBUSDT:30m")],
        worker_factory=_StubWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=authority,  # type: ignore[arg-type]
    )

    workers = await runner.connect(_FakeRedis())

    assert [(worker.asset, worker.timeframe) for worker in workers] == [
        ("BNBUSDT", "30m")
    ]
    assert "BTCUSDT:1h" not in runner._worker_tasks
    await runner.stop()


@pytest.mark.asyncio
async def test_authority_bind_race_keeps_unrelated_route_active() -> None:
    _BindFailWorker.created = []
    _BindFailWorker.fail_route = "BTCUSDT:1h"
    route = "BTCUSDT:1h"
    authority = _AuthorityAdmission({route: _authority(route, "strategy")})
    runner = StrategyRuntimeRunner(
        [_pair(route), _pair("BNBUSDT:30m")],
        worker_factory=_BindFailWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=authority,  # type: ignore[arg-type]
    )

    workers = await runner.connect(_FakeRedis())

    assert [(worker.asset, worker.timeframe) for worker in workers] == [
        ("BNBUSDT", "30m")
    ]
    assert "BTCUSDT:1h" not in runner._worker_tasks
    _BindFailWorker.fail_route = None
    await runner.stop()


@pytest.mark.asyncio
async def test_authority_start_race_keeps_unrelated_route_active() -> None:
    _StartAuthorityFailWorker.created = []
    _StartAuthorityFailWorker.fail_route = "BTCUSDT:1h"
    route = "BTCUSDT:1h"
    authority = _AuthorityAdmission({route: _authority(route, "strategy")})
    runner = StrategyRuntimeRunner(
        [_pair(route), _pair("BNBUSDT:30m")],
        worker_factory=_StartAuthorityFailWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=authority,  # type: ignore[arg-type]
    )

    workers = await runner.connect(_FakeRedis())
    assert {f"{worker.asset}:{worker.timeframe}" for worker in workers} == {
        "BTCUSDT:1h",
        "BNBUSDT:30m",
    }
    runner._supervisor_task = asyncio.create_task(runner._supervise())
    await asyncio.sleep(0.2)

    assert "BTCUSDT:1h" not in runner._worker_tasks
    assert "BNBUSDT:30m" in runner._worker_tasks
    assert runner._supervisor_task is not None
    assert runner._supervisor_task.done() is False

    _StartAuthorityFailWorker.fail_route = None
    await runner.stop()


@pytest.mark.asyncio
async def test_unmanaged_connect_value_error_still_propagates() -> None:
    runner = StrategyRuntimeRunner(
        [_pair("BNBUSDT:30m")],
        worker_factory=_ConnectValueErrorWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=_AuthorityAdmission({}),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="worker connect defect"):
        await runner.connect(_FakeRedis())


@pytest.mark.asyncio
async def test_authority_disabled_connect_value_error_still_propagates() -> None:
    _ConnectValueErrorWorker.error_text = "legacy worker connect defect"
    runner = StrategyRuntimeRunner(
        [_pair("BTCUSDT:1h")],
        worker_factory=_ConnectValueErrorWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=False),
    )

    with pytest.raises(ValueError, match="legacy worker connect defect"):
        await runner.connect(_FakeRedis())


@pytest.mark.asyncio
async def test_authority_read_cancellation_propagates() -> None:
    runner = StrategyRuntimeRunner(
        [_pair("BTCUSDT:1h")],
        worker_factory=_StubWorker,
        worker_settings=StrategyWorkerSettings(signal_authority_enforced=True),
        authority_store=_AuthorityAdmission({"BTCUSDT:1h": asyncio.CancelledError()}),  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError):
        await runner.connect(_FakeRedis())


def test_production_default_topology_uses_authority_not_route_exclusions() -> None:
    models = yaml.safe_load((ROOT / "configs/models.yaml").read_text())
    assert models["strategy"]["runtime"]["signal_authority_enforced"] is True
    assert "relinquished_routes" not in models["strategy"]["runtime"]

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    decision = compose["services"]["decision"]
    assert "profiles" not in decision
    assert decision["depends_on"]["ingestion"] == {"condition": "service_healthy"}
    assert decision["deploy"]["resources"]["limits"] == {
        "memory": "512M",
        "cpus": "0.5",
    }


def test_stored_d11c_artifact_recomputes_fail_closed() -> None:
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    checks = evaluate_artifact(artifact)
    assert artifact["terminal_status"] == SUCCESS_STATUS
    assert all(checks.values())


@pytest.mark.parametrize(
    ("label", "mutate", "expected_gate"),
    [
        (
            "source",
            lambda artifact: artifact["raw_evidence"]["current_source_hashes"].update(
                {"tests/combined/d11c_real.py": "0" * 64}
            ),
            "source_lock",
        ),
        (
            "top_level_source",
            lambda artifact: artifact["current_source_hashes"].update(
                {"tests/combined/d11c_real.py": "0" * 64}
            ),
            "top_level_source_hashes_match",
        ),
        (
            "config",
            lambda artifact: artifact["raw_evidence"][
                "production_config_hashes"
            ].update({"configs/risk.yaml": "0" * 64}),
            "production_config_lock",
        ),
        (
            "protected",
            lambda artifact: artifact["raw_evidence"]["protected_hashes"].update(
                {"d11b": "0" * 64}
            ),
            "protected_hashes",
        ),
        (
            "identity_digest",
            lambda artifact: artifact.update({"identity_digest": "0" * 64}),
            "identity_digest_integrity",
        ),
        (
            "evidence_digest",
            lambda artifact: artifact.update({"evidence_digest": "0" * 64}),
            "evidence_digest_integrity",
        ),
        (
            "stored_gate",
            lambda artifact: artifact["gates"].update({"resource_envelope": False}),
            "stored_gates_match",
        ),
        (
            "terminal",
            lambda artifact: artifact.update({"terminal_status": "TAMPERED"}),
            "terminal_status_match",
        ),
        (
            "readiness",
            lambda artifact: artifact["raw_evidence"]["trials"][0]["flow"].update(
                {"decision_ready": False}
            ),
            "trial_1_decision_flow",
        ),
        (
            "authority",
            lambda artifact: artifact["raw_evidence"]["trials"][0]["authority"][
                "strategy_epoch_0"
            ].pop("BTCUSDT:1h"),
            "trial_1_authority_sequence",
        ),
        (
            "resource",
            lambda artifact: artifact["raw_evidence"]["trials"][0][
                "resources_final"
            ].pop("decision"),
            "resource_envelope",
        ),
        (
            "cleanup",
            lambda artifact: artifact["raw_evidence"]["trials"][0]["cleanup"][
                "leftovers"
            ].update({"containers": "d11c-leftover"}),
            "trial_1_cleanup",
        ),
        (
            "parity",
            lambda artifact: artifact["raw_evidence"]["trials"][0]["flow"].update(
                {"signals_before": 1}
            ),
            "trial_parity",
        ),
        (
            "parity_matches_false",
            lambda artifact: artifact["raw_evidence"]["trial_semantic_parity"].update(
                {"matches": False}
            ),
            "trial_parity",
        ),
        (
            "trial_failed",
            lambda artifact: artifact["raw_evidence"]["trials"][0].update(
                {"failed": True, "error": "synthetic late failure"}
            ),
            "trial_1_measured_trial",
        ),
        (
            "trial_not_real",
            lambda artifact: artifact["raw_evidence"]["trials"][0].update(
                {"real_disposable_stack": False}
            ),
            "trial_1_measured_trial",
        ),
    ],
)
def test_stored_d11c_tampering_fails_closed(
    label: str, mutate: object, expected_gate: str
) -> None:
    del label
    artifact = copy.deepcopy(json.loads(ARTIFACT_PATH.read_text(encoding="utf-8")))
    mutate(artifact)  # type: ignore[operator]
    checks = evaluate_artifact(artifact)
    assert checks[expected_gate] is False


@pytest.mark.parametrize(
    ("status", "expected"), [(SUCCESS_STATUS, 0), (BLOCKED_STATUS, 1)]
)
def test_d11c_certifier_exit_contract_subprocess(status: str, expected: int) -> None:
    command = [
        sys.executable,
        "-c",
        (
            "from scripts.certify_decision_d11c_default_topology import "
            f"exit_code_for_status; raise SystemExit(exit_code_for_status({status!r}))"
        ),
    ]
    result = subprocess.run(command, cwd=ROOT, check=False)
    assert result.returncode == expected
    assert exit_code_for_status(status) == expected
