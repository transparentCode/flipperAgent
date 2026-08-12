from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import certify_ingestion_program_final as final


def _preflight() -> dict[str, object]:
    return {
        "protocol": {"checks": {"frozen": True}},
        "graph": {"enabled_assets": [], "pairs": []},
    }


def test_dry_run_does_not_execute_subcertifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(final, "_capture_preflight", _preflight)
    monkeypatch.setattr(
        final,
        "_build_images",
        lambda: pytest.fail("dry-run must not build images"),
    )
    monkeypatch.setattr(
        final,
        "_phase_gates",
        lambda: pytest.fail("dry-run must not execute phase gates"),
    )

    result = final.run_final(execute=False)

    assert result["status"] == final.DRY_RUN_STATUS


def test_execute_requires_final_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(final, "_capture_preflight", _preflight)
    monkeypatch.delenv(final.FINAL_GUARD, raising=False)
    monkeypatch.setattr(
        final,
        "_build_images",
        lambda: pytest.fail("guard failure must occur before build"),
    )

    with pytest.raises(final.FinalCertificationError, match=final.FINAL_GUARD):
        final.run_final(execute=True)


def test_execute_order_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    monkeypatch.setattr(final, "_capture_preflight", _preflight)
    monkeypatch.setenv(final.FINAL_GUARD, "1")
    monkeypatch.setattr(final, "_build_images", lambda: events.append("build") or {})
    monkeypatch.setattr(
        final,
        "_phase_gates",
        lambda evidence: events.append("gates"),
    )
    monkeypatch.setattr(
        final, "_steady_state", lambda graph: events.append("steady") or {}
    )
    monkeypatch.setattr(
        final,
        "_stop_final_services",
        lambda: events.append("restore") or {},
    )
    monkeypatch.setattr(final, "ARTIFACT_PATH", tmp_path / "final.json")

    result = final.run_final(execute=True)

    assert result["status"] == final.FINAL_PROGRAM_STATUS
    assert events == ["build", "gates", "steady", "restore"]
    assert (tmp_path / "final.json").exists()


def test_first_failed_gate_stops_later_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    evidence: dict[str, object] = {}

    def n3b(label: str) -> dict[str, object]:
        events.append(label)
        return {}

    def subcert(name: str, args: object, **kwargs: object) -> dict[str, object]:
        events.append(name)
        if name == "n1c_operations":
            raise final.FinalCertificationError(
                "BLOCKED_FINAL_N1C_OPERATIONS", "test failure"
            )
        return {}

    monkeypatch.setattr(final, "_n3b_verify", n3b)
    monkeypatch.setattr(final, "_run_subcert", subcert)

    with pytest.raises(final.FinalCertificationError, match="test failure"):
        final._phase_gates(evidence)

    assert events == ["n3b_retirement_pre", "n1c_operations"]
    assert evidence == {"n3b_pre": {}}


def test_failed_n2c_preserves_completed_gate_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(final, "_capture_preflight", _preflight)
    monkeypatch.setenv(final.FINAL_GUARD, "1")
    monkeypatch.setattr(final, "_build_images", lambda: {"return_code": 0})
    monkeypatch.setattr(final, "ARTIFACT_PATH", tmp_path / "final.json")
    monkeypatch.setattr(
        final,
        "_stop_final_services",
        lambda **kwargs: {"return_code": 0, "pending_outbox": 0, **kwargs},
    )
    later_gate_called = False

    def fail_at_n2c(evidence: dict[str, object]) -> None:
        nonlocal later_gate_called
        evidence["n3b_pre"] = {"status": "READY_FOR_REVIEW"}
        evidence["n1c"] = {"status": "READY_FOR_REVIEW"}
        evidence["l2b2"] = {"status": "pytest_pass"}
        evidence["n1d"] = {"status": "READY_FOR_REVIEW"}
        evidence["n2c_failure_attempted"] = True
        later_gate_called = True
        raise final.FinalCertificationError(
            "BLOCKED_FINAL_N2C_RETENTION_RECOVERY",
            "controlled N2C failure",
        )

    monkeypatch.setattr(final, "_phase_gates", fail_at_n2c)

    with pytest.raises(
        final.FinalCertificationError,
        match="controlled N2C failure",
    ):
        final.run_final(execute=True)

    artifact = json.loads((tmp_path / "final.json").read_text(encoding="utf-8"))
    assert later_gate_called is True
    assert all(key in artifact for key in ("n3b_pre", "n1c", "l2b2", "n1d"))
    assert "n2c" not in artifact
    assert "n3b_post" not in artifact
    assert "steady_state" not in artifact
    assert artifact["status"] == "BLOCKED_FINAL_N2C_RETENTION_RECOVERY"


def test_shutdown_orders_quiescence_before_ingestion_and_broker_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    running = {"broker": True, "ingestion": True, "signal-worker": True}

    def fake_compose(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert args[0] == "stop"
        service = args[1]
        events.append(f"stop:{service}")
        running[service] = False
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_state(service: str) -> dict[str, object]:
        if service == "db":
            return {
                "service": service,
                "exists": True,
                "running": True,
                "health": "healthy",
                "exit_code": 0,
                "oom_killed": False,
            }
        return {
            "service": service,
            "exists": True,
            "running": running.get(service, False),
            "health": "healthy" if running.get(service, False) else None,
            "exit_code": 0,
            "oom_killed": False,
        }

    def fake_quiescence() -> dict[str, object]:
        assert events == ["stop:signal-worker"]
        events.extend(("runtime_pause", "pending_outbox_zero"))
        return {"proven": True, "pre_stop_outbox": 0}

    monkeypatch.setattr(final, "_compose", fake_compose)
    monkeypatch.setattr(final, "_service_state", fake_state)
    monkeypatch.setattr(final, "_pause_ingestion_and_wait", fake_quiescence)
    monkeypatch.setattr(final, "_pending_outbox", lambda: 0)

    evidence = final._stop_final_services()

    assert events == [
        "stop:signal-worker",
        "runtime_pause",
        "pending_outbox_zero",
        "stop:ingestion",
        "stop:broker",
    ]
    assert evidence["shutdown_order"] == [
        "signal-worker",
        "runtime_pause",
        "pending_outbox_zero",
        "ingestion",
        "broker",
    ]
    assert evidence["pending_outbox"] == 0


@pytest.mark.parametrize("unavailable", ["broker", "ingestion"])
def test_failure_cleanup_does_not_wait_for_unavailable_publisher(
    monkeypatch: pytest.MonkeyPatch,
    unavailable: str,
) -> None:
    running = {
        "broker": unavailable != "broker",
        "ingestion": unavailable != "ingestion",
    }
    pause_called = False

    def fake_compose(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_state(service: str) -> dict[str, object]:
        if service == "db":
            return {"service": service, "running": True, "health": "healthy"}
        return {
            "service": service,
            "running": running.get(service, False),
            "exit_code": 0,
        }

    def fail_if_paused() -> dict[str, object]:
        nonlocal pause_called
        pause_called = True
        raise AssertionError("cleanup must not wait for an unavailable publisher")

    monkeypatch.setattr(final, "_compose", fake_compose)
    monkeypatch.setattr(final, "_service_state", fake_state)
    monkeypatch.setattr(final, "_pause_ingestion_and_wait", fail_if_paused)
    monkeypatch.setattr(final, "_pending_outbox", lambda: 0)

    evidence = final._stop_final_services(best_effort=True)

    assert pause_called is False
    assert evidence["quiescence"]["proven"] is False
    assert evidence["quiescence"]["skipped"] == "broker_or_ingestion_unavailable"


def test_post_n2c_signal_drain_precedes_retirement_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_state(service: str) -> dict[str, object]:
        return {"service": service, "running": False, "health": None}

    def fake_compose(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        events.append(":".join(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    async def fake_baseline(graph: object) -> dict[str, object]:
        del graph
        events.append("baseline")
        return {"inputs": {}, "outputs": {}}

    async def fake_signal(
        graph: object, baseline: object, startup_ms: int
    ) -> dict[str, object]:
        del graph, baseline, startup_ms
        events.append("signal_drain")
        return {"statuses": {}, "groups": {}, "outputs": {}}

    monkeypatch.setattr(final, "_service_state", fake_state)
    monkeypatch.setattr(final, "_compose", fake_compose)
    monkeypatch.setattr(final, "_wait_until", lambda *args, **kwargs: True)
    monkeypatch.setattr(final, "_valkey_inputs_and_outputs", fake_baseline)
    monkeypatch.setattr(final, "_signal_evidence", fake_signal)

    evidence = final._drain_signal_groups_after_n2c({"pairs": []})

    assert evidence["proven"] is True
    assert events == [
        "up:-d:broker",
        "baseline",
        "up:-d:signal-worker",
        "signal_drain",
        "stop:signal-worker",
        "stop:broker",
    ]


def test_wrong_subcert_status_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["certifier"],
        returncode=0,
        stdout=json.dumps({"status": "BLOCKED_N1C"}),
        stderr="",
    )
    monkeypatch.setattr(final, "_run_command", lambda *args, **kwargs: completed)

    with pytest.raises(final.FinalCertificationError, match="did not return"):
        final._run_subcert("n1c_operations", ("certifier",), env={})


def test_frozen_namespace_and_protocol_contract_is_current() -> None:
    compose = {
        "services": {
            "ingestion": {
                "command": "python -m apps.ingestion_app.main",
                "environment": {"OTEL_SERVICE_NAME": "ingestion"},
            }
        }
    }

    result = final._namespace_and_protocol_contract(compose)

    assert all(result["checks"].values())


def test_artifact_is_read_back_and_hashed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "final_certification.json"
    monkeypatch.setattr(final, "ARTIFACT_PATH", path)

    artifact_path, digest = final._write_artifact(
        {
            "schema_version": 1,
            "starting_sha": "test",
            "started_at": "2026-08-11T00:00:00Z",
            "status": final.DRY_RUN_STATUS,
            "preflight": {},
        }
    )

    assert artifact_path == str(path)
    assert digest == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    assert json.loads(path.read_text())["status"] == final.DRY_RUN_STATUS


def test_canonical_namespace_paths_are_current() -> None:
    assert (final.REPO_ROOT / "configs/ingestion/global.yaml").is_file()
    assert (final.REPO_ROOT / "src/apps/ingestion_app").is_dir()
    assert not (final.REPO_ROOT / "src/apps/ingestion").exists()
    assert (final.REPO_ROOT / "tests/ingestion").is_dir()
    assert not (final.REPO_ROOT / "tests" / ("ingestion" + "_" + "v2")).exists()
