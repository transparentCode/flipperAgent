"""Hermetic tests for the bounded Phase 10C.2 replay boundary."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts import replay_trendline_v2_lookback_eviction as replay
from libs.models.trendline_v2.domain.candidates import AnchorRef
from libs.models.trendline_v2.domain.identity import canonical_json
from libs.models.trendline_v2.domain.provider_input import ProviderInput


UTC = timezone.utc


def _small_input() -> ProviderInput:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int(
            (
                start.replace(hour=hour) - datetime(1970, 1, 1, tzinfo=UTC)
            ).total_seconds()
        )
        * 1_000_000_000
        for hour in (0, 4, 8)
    )
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=datetime(2025, 1, 1, 12, tzinfo=UTC),
        confirmed_through=datetime(2025, 1, 1, 12, tzinfo=UTC),
        timestamps=timestamps,
        open=(100.0, 101.0, 102.0),
        high=(101.0, 102.0, 103.0),
        low=(99.0, 100.0, 101.0),
        close=(100.5, 101.5, 102.5),
        volume=(1.0, 1.0, 1.0),
    )


def _anchor(name: str, pivot_time: datetime) -> AnchorRef:
    return AnchorRef(
        anchor_id=name,
        pivot_time=pivot_time,
        confirmation_time=pivot_time + timedelta(hours=1),
        price=100.0,
    )


def _window(start: datetime) -> replay.EffectiveWindow:
    return replay.EffectiveWindow(
        start=start,
        end=start + timedelta(days=30),
        row_count=replay.EFFECTIVE_ROWS,
        first_timestamp=start,
        last_timestamp=start + timedelta(hours=4),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _removal_case(
    first_pivot: datetime,
    *,
    previous_start: datetime,
    current_start: datetime,
) -> dict[str, object]:
    previous_window = _window(previous_start)
    current_window = _window(current_start)
    checkpoint = replay.CheckpointSpec(
        index=2,
        observed_at=current_start + timedelta(days=1),
        prefix_rows=918,
        effective_window_start=current_start,
    )
    return replay._removal_attribution(
        family_id="family-1",
        role="support",
        first_anchor=_anchor("first", first_pivot),
        second_anchor=_anchor("second", first_pivot + timedelta(hours=4)),
        previous_observed_at=current_start + timedelta(hours=12),
        checkpoint=checkpoint,
        previous_window=previous_window,
        current_window=current_window,
        current_family_ids=set(),
    )


def test_replay_contract_identity_is_pinned() -> None:
    payload = replay._replay_contract_payload()
    assert replay.REPLAY_CONTRACT_EXPECTED_ID == (
        "166b156a471f06dcc2d4fbf09196df95"
        "c4648e4b60cac52d1d315f7e7794af96"
    )
    assert replay.replay_contract_id(payload) == replay.REPLAY_CONTRACT_ID


def test_previous_contract_is_explicitly_superseded() -> None:
    assert replay.SUPERSEDED_REPLAY_CONTRACT_ID == (
        "fe93c86fc67638e81219e68100ce7dde7d629db7f528073a0581fd5eda986314"
    )
    assert replay.REPLAY_CONTRACT_ID != replay.SUPERSEDED_REPLAY_CONTRACT_ID


@pytest.mark.parametrize("field", ["source_input_identity"])
def test_replay_contract_identity_changes_on_source_mutation(field: str) -> None:
    payload = replay._replay_contract_payload()
    mutated = dict(payload)
    mutated[field] = "f" * 64
    assert replay.replay_contract_id(mutated) != replay.replay_contract_id(payload)


def test_replay_contract_identity_changes_on_checkpoint_mutation() -> None:
    payload = replay._replay_contract_payload()
    checkpoints = [dict(item) for item in payload["checkpoints"]]
    checkpoints[0]["observed_at"] = "2025-12-01T04:00:00Z"
    mutated = {**payload, "checkpoints": checkpoints}
    assert replay.replay_contract_id(mutated) != replay.replay_contract_id(payload)


def test_replay_contract_identity_changes_on_prefix_and_window_mutations() -> None:
    payload = replay._replay_contract_payload()
    prefix_mutated = [dict(item) for item in payload["checkpoints"]]
    prefix_mutated[0]["prefix_row_count"] += 1
    window_mutated = [dict(item) for item in payload["checkpoints"]]
    window_mutated[0]["effective_window_start"] = "2025-08-01T04:00:00Z"
    assert replay.replay_contract_id(
        {**payload, "checkpoints": prefix_mutated}
    ) != replay.replay_contract_id(payload)
    assert replay.replay_contract_id(
        {**payload, "checkpoints": window_mutated}
    ) != replay.replay_contract_id(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: {
            **payload,
            "anchor_eligibility_context": {
                **payload["anchor_eligibility_context"],
                "left_confirmation_bars": 2,
            },
        },
        lambda payload: {
            **payload,
            "anchor_eligibility_context": {
                **payload["anchor_eligibility_context"],
                "interval_seconds": 28_800,
            },
        },
        lambda payload: {
            **payload,
            "anchor_eligibility_context": {
                **payload["anchor_eligibility_context"],
                "required_history_start_rule": "changed-rule",
            },
        },
    ],
)
def test_replay_contract_identity_changes_on_anchor_context_mutation(mutation) -> None:
    payload = replay._replay_contract_payload()
    assert replay.replay_contract_id(mutation(payload)) != replay.replay_contract_id(
        payload
    )


def test_checkpoints_are_exact_and_ordered() -> None:
    assert tuple(item.index for item in replay.CHECKPOINTS) == (1, 2, 3, 4, 5)
    assert tuple(item.prefix_rows for item in replay.CHECKPOINTS) == (
        732,
        918,
        1104,
        1272,
        1458,
    )
    assert tuple(item.effective_window_start for item in replay.CHECKPOINTS) == (
        datetime(2025, 8, 1, tzinfo=UTC),
        datetime(2025, 9, 1, tzinfo=UTC),
        datetime(2025, 10, 2, tzinfo=UTC),
        datetime(2025, 10, 30, tzinfo=UTC),
        datetime(2025, 11, 30, tzinfo=UTC),
    )


def test_causal_prefix_excludes_checkpoint_row_and_future_rows() -> None:
    source = _small_input()
    checkpoint = replay.CheckpointSpec(
        index=1,
        observed_at=datetime(2025, 1, 1, 8, tzinfo=UTC),
        prefix_rows=2,
        effective_window_start=datetime(2025, 1, 1, 4, tzinfo=UTC),
    )
    result = replay._prefix_input(source, checkpoint)
    assert result.row_count == 2
    assert result.timestamps[-1] == source.timestamps[1]

    future_changed = ProviderInput(
        asset=source.asset,
        timeframe=source.timeframe,
        observed_at=source.observed_at,
        confirmed_through=source.confirmed_through,
        timestamps=source.timestamps,
        open=source.open,
        high=source.high,
        low=source.low,
        close=source.close,
        volume=(1.0, 1.0, 99.0),
    )
    assert (
        replay._prefix_input(future_changed, checkpoint).to_dict() == result.to_dict()
    )


def test_effective_window_uses_inclusive_lower_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _small_input()
    checkpoint = replay.CheckpointSpec(
        index=1,
        observed_at=datetime(2025, 1, 1, 12, tzinfo=UTC),
        prefix_rows=3,
        effective_window_start=datetime(2025, 1, 1, 4, tzinfo=UTC),
    )
    monkeypatch.setattr(replay, "EFFECTIVE_ROWS", 2)
    window = replay._effective_window(source, checkpoint)
    assert window.row_count == 2
    assert window.first_timestamp == checkpoint.effective_window_start


def test_fixed_configuration_identities_are_canonical() -> None:
    config, provider, selection, tracking = replay._fixed_configuration()
    assert config.semantic_hash == replay.FOUNDATION_CONFIG_ID
    assert provider.semantic_hash == replay.PROVIDER_CONFIG_ID
    assert provider.left_confirmation_bars == replay.LEFT_CONFIRMATION_BARS
    assert selection.policy_identity == replay.SELECTION_POLICY_ID
    assert tracking.policy_identity == replay.TRACKING_POLICY_ID


def test_first_anchor_required_history_start_is_causal() -> None:
    pivot = datetime(2025, 1, 2, tzinfo=UTC)
    assert replay._first_anchor_required_history_start(_anchor("a", pivot)) == (
        pivot - timedelta(hours=4)
    )


def test_first_anchor_eviction_is_attributed() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    record = _removal_case(
        current_start - timedelta(hours=8),
        previous_start=current_start - timedelta(days=2),
        current_start=current_start,
    )
    assert record["removal_cause"] == "first_anchor_evicted"
    assert record["attribution_status"] == "attributed_source_eviction"
    assert record["first_anchor_required_history_start"] == "2025-01-09T12:00:00Z"


def test_first_anchor_at_window_start_is_left_context_eviction() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    record = _removal_case(
        current_start,
        previous_start=current_start - timedelta(days=2),
        current_start=current_start,
    )
    assert record["removal_cause"] == "first_anchor_left_context_evicted"
    assert record["left_confirmation_bars"] == 1
    assert record["interval_seconds"] == 14_400


def test_one_full_interval_after_window_start_is_not_attributable() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    with pytest.raises(replay.ReplayScopeBlocked, match="UNATTRIBUTED"):
        _removal_case(
            current_start + timedelta(hours=4),
            previous_start=current_start - timedelta(days=2),
            current_start=current_start,
        )


def test_required_history_before_previous_window_is_not_attributable() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    with pytest.raises(replay.ReplayScopeBlocked, match="UNATTRIBUTED"):
        _removal_case(
            current_start - timedelta(days=2),
            previous_start=current_start - timedelta(days=2),
            current_start=current_start,
        )


def test_active_anchor_at_window_start_is_rejected() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    checkpoint = replay.CheckpointSpec(
        2,
        current_start + timedelta(days=1),
        918,
        current_start,
    )
    with pytest.raises(replay.ReplayScopeBlocked, match="outside rolling window"):
        replay._validate_active_anchor_window(
            (_anchor("first", current_start), _anchor("second", current_start + timedelta(hours=4))),
            window=_window(current_start),
            checkpoint=checkpoint,
        )


def test_active_anchor_required_history_at_window_start_is_accepted() -> None:
    current_start = datetime(2025, 1, 10, tzinfo=UTC)
    checkpoint = replay.CheckpointSpec(
        2,
        current_start + timedelta(days=1),
        918,
        current_start,
    )
    replay._validate_active_anchor_window(
        (
            _anchor("first", current_start + timedelta(hours=4)),
            _anchor("second", current_start + timedelta(hours=8)),
        ),
        window=_window(current_start),
        checkpoint=checkpoint,
    )


def test_duplicate_removal_attribution_is_rejected() -> None:
    with pytest.raises(replay.ReplayScopeBlocked, match="duplicate"):
        replay._validate_unique_removal_attributions(
            ({"family_id": "family-1"}, {"family_id": "family-1"})
        )


def test_blocked_diagnostic_reports_count_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "phase10c2"
    monkeypatch.setenv(replay.NETWORK_ENV, "1")
    monkeypatch.setattr(replay, "_verify_source", lambda: ({}, _small_input()))

    def blocked_replay(*args: object, **kwargs: object) -> object:
        state = kwargs["execution_state"]
        assert isinstance(state, replay.ReplayExecutionState)
        state.completed_provider_execution_count = 3
        state.current_checkpoint_index = 4
        state.previous_effective_window_start = datetime(2025, 10, 2, tzinfo=UTC)
        state.current_effective_window_start = datetime(2025, 10, 30, tzinfo=UTC)
        raise replay.ReplayScopeBlocked("UNATTRIBUTED_SOURCE_REMOVAL")

    monkeypatch.setattr(replay, "_replay_records", blocked_replay)
    with pytest.raises(replay.ReplayScopeBlocked):
        replay.execute_replay(output_root=output)

    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["study_status"] == "BLOCKED_PHASE_10C2_REPLAY"
    assert diagnostic["replay_contract_id"] == replay.REPLAY_CONTRACT_ID
    assert diagnostic["completed_provider_execution_count"] == 3
    assert diagnostic["failed_checkpoint_index"] == 4
    assert diagnostic["failure_code"] == "UNATTRIBUTED_SOURCE_REMOVAL"
    assert diagnostic["network_request_count"] == 0
    assert diagnostic["retry_count"] == 0
    assert diagnostic["fallback_count"] == 0
    assert not output.exists()


def test_missing_output_parent_and_staging_ready_before_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "missing" / "nested" / "phase10c2"
    observed: dict[str, object] = {}
    monkeypatch.setenv(replay.NETWORK_ENV, "1")
    monkeypatch.setattr(replay, "_verify_source", lambda: ({}, _small_input()))

    def blocked_replay(*args: object, **kwargs: object) -> object:
        observed["parent_exists"] = output.parent.is_dir()
        observed["staging_entries"] = tuple(
            path.name for path in output.parent.glob(f".{output.name}.*")
        )
        raise replay.ReplayScopeBlocked("pre-provider stop")

    monkeypatch.setattr(replay, "_replay_records", blocked_replay)
    with pytest.raises(replay.ReplayScopeBlocked):
        replay.execute_replay(output_root=output)
    capsys.readouterr()

    assert observed["parent_exists"] is True
    assert observed["staging_entries"]
    assert not output.exists()
    assert not tuple(output.parent.glob(f".{output.name}.*"))


def test_staging_preparation_failure_makes_zero_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "missing" / "phase10c2"
    provider_calls = 0
    monkeypatch.setenv(replay.NETWORK_ENV, "1")
    monkeypatch.setattr(replay, "_verify_source", lambda: ({}, _small_input()))

    def fail_staging(*args: object, **kwargs: object) -> object:
        raise OSError("staging unavailable")

    def provider(*args: object, **kwargs: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not run")

    monkeypatch.setattr(replay.tempfile, "mkdtemp", fail_staging)
    monkeypatch.setattr(replay, "_replay_records", provider)
    with pytest.raises(OSError, match="staging unavailable"):
        replay.execute_replay(output_root=output)

    assert provider_calls == 0
    assert output.parent.is_dir()
    assert not output.exists()


def test_replay_failure_removes_precreated_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "missing" / "phase10c2"
    observed_staging: list[Path] = []
    monkeypatch.setenv(replay.NETWORK_ENV, "1")
    monkeypatch.setattr(replay, "_verify_source", lambda: ({}, _small_input()))

    def blocked_replay(*args: object, **kwargs: object) -> object:
        observed_staging.extend(output.parent.glob(f".{output.name}.*"))
        raise replay.ReplayScopeBlocked("replay failure")

    monkeypatch.setattr(replay, "_replay_records", blocked_replay)
    with pytest.raises(replay.ReplayScopeBlocked):
        replay.execute_replay(output_root=output)
    capsys.readouterr()

    assert observed_staging
    assert all(not path.exists() for path in observed_staging)
    assert not output.exists()


def test_synthetic_success_publishes_atomically_from_missing_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "missing" / "phase10c2"
    observed: dict[str, object] = {}
    verify_calls: list[Path] = []
    monkeypatch.setenv(replay.NETWORK_ENV, "1")
    monkeypatch.setattr(replay, "_verify_source", lambda: ({}, _small_input()))

    def fake_replay(*args: object, **kwargs: object) -> tuple[object, ...]:
        observed["parent_exists"] = output.parent.is_dir()
        observed["staging_entries"] = tuple(
            output.parent.glob(f".{output.name}.*")
        )
        return ()

    def fake_write_bundle(staging: Path, **kwargs: object) -> dict[str, bool]:
        observed["staging"] = staging
        (staging / "evidence.json").write_text('{"ok":true}\n')
        return {"written": True}

    def fake_verify_bundle(*, output_root: Path = replay.OUTPUT_ROOT) -> dict[str, bool]:
        verify_calls.append(Path(output_root))
        return {"verified": True}

    monkeypatch.setattr(replay, "_replay_records", fake_replay)
    monkeypatch.setattr(replay, "_write_bundle", fake_write_bundle)
    monkeypatch.setattr(replay, "verify_bundle", fake_verify_bundle)

    result = replay.execute_replay(output_root=output)

    assert result == {"written": True, "verified": {"verified": True}}
    assert observed["parent_exists"] is True
    assert observed["staging_entries"]
    assert verify_calls[0] == observed["staging"]
    assert verify_calls[1] == output
    assert (output / "evidence.json").read_text() == '{"ok":true}\n'
    assert tuple(path.name for path in output.iterdir()) == ("evidence.json",)


def test_generation_requires_environment_and_existing_root_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.delenv(replay.NETWORK_ENV, raising=False)
    with pytest.raises(replay.ReplayError, match="existing output root"):
        replay.execute_replay(output_root=output)


def test_generation_guard_rejects_without_environment(tmp_path: Path) -> None:
    with pytest.raises(replay.ReplayError, match=replay.NETWORK_ENV):
        replay.execute_replay(output_root=tmp_path / "new")


def test_atomic_write_and_canonical_json(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "value.json"
    replay._write_json(path, {"b": 2, "a": 1})
    assert path.read_bytes() == (canonical_json({"a": 1, "b": 2}) + "\n").encode()
    with pytest.raises(replay.ReplayError, match="existing output file"):
        replay._write_json(path, {"a": 1})


def test_manifest_binds_exactly_eleven_members(tmp_path: Path) -> None:
    for index in range(11):
        (tmp_path / f"member_{index}.json").write_bytes(b"{}\n")
    decision = {"decision_id": "a" * 64}
    manifest = replay._manifest(tmp_path, decision)
    assert manifest["member_count"] == 11
    assert len(manifest["members"]) == 11
    assert manifest["manifest_id"] == replay.deterministic_hash(
        replay.MANIFEST_NAMESPACE,
        {key: value for key, value in manifest.items() if key != "manifest_id"},
    )


def test_output_root_path_is_bounded() -> None:
    assert (
        replay.OUTPUT_ROOT.as_posix()
        == "/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401"
    )


@pytest.mark.skipif(
    __import__("os").environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires the one authorized external replay bundle",
)
def test_external_bundle_verifies_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider(*args: object, **kwargs: object) -> object:
        raise AssertionError("verification must not execute a provider")

    monkeypatch.setattr(replay, "discover_trendlines", fail_provider)
    result = replay.verify_bundle()
    assert result == {
        "study_status": "LOOKBACK_EVICTION_TRANSITIONS_VERIFIED",
        "decision_id": (
            "ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6"
        ),
        "manifest_id": (
            "4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5"
        ),
        "output_inventory_sha256": (
            "64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c"
        ),
        "provider_execution_count": 0,
        "network_request_count": 0,
        "checkpoint_count": 5,
    }

    root = replay.OUTPUT_ROOT
    assert {
        name: _sha256(root / name)
        for name in (
            "removal_attribution.json",
            "provider_execution_audit.json",
            "checkpoint_summary.csv",
        )
    } == {
        "removal_attribution.json": (
            "14cadcbbf061ed37f8cf0926b458f9729c856f74c3e1d525cbc43feeab430691"
        ),
        "provider_execution_audit.json": (
            "b5643c4e00125ce5e661b91675e5606806c1817c3446f5e148c50df6dff4f962"
        ),
        "checkpoint_summary.csv": (
            "d6ec714ca01c83e97340dfaf3ffd0a8eb91b4234057e3935cb225feccaad48ed"
        ),
    }

    with (root / "checkpoint_summary.csv").open(newline="") as handle:
        summary_rows = tuple(csv.DictReader(handle))
    checkpoint_rows = []
    for summary in summary_rows:
        checkpoint_index = int(summary["checkpoint_index"])
        checkpoint_path = next(
            root.glob(
                "datasets/btcusdt_4h/"
                f"checkpoint_{checkpoint_index:02d}_*.json"
            )
        )
        payload = replay._load_json(checkpoint_path)
        checkpoint_rows.append(
            {
                "checkpoint": checkpoint_index,
                "prefix_input_id": payload["prefix_input_identity"],
                "provider_result_id": summary["provider_result_id"],
                "discovery_id": summary["discovery_snapshot_id"],
                "selection_id": summary["selection_snapshot_id"],
                "tracking_id": summary["tracking_snapshot_id"],
                "candidate_count": int(summary["candidate_count"]),
                "selected_count": len(payload["selection_snapshot"]["decisions"]),
                "active_count": int(summary["active_family_count"]),
                "births": int(summary["birth_count"]),
                "continuations": int(summary["continuation_count"]),
                "removals": int(summary["source_removed_count"]),
                "cumulative_removals": int(summary["cumulative_removed_count"]),
            }
        )
    assert tuple(checkpoint_rows) == (
        {
            "checkpoint": 1,
            "prefix_input_id": (
                "b413ae38dd59c085c38774148b641e253e06df4591ed36f2357109ac1ea39371"
            ),
            "provider_result_id": (
                "045036f558c1fcca770cd29713b3e86beb1d9d6feafca95f7d26d11615b55973"
            ),
            "discovery_id": (
                "13bec863774047756a71a083f1dba0619d2d04756195d6ec8dba048241901db7"
            ),
            "selection_id": (
                "5a896d7ea73cf8a3794271412125bea76a0e33e72b2b745b73c81eed326b2b03"
            ),
            "tracking_id": (
                "f836dfe21846fbff3c6beca13482b4ec2cef961e0468ccc706d59570dc046848"
            ),
            "candidate_count": 2697,
            "selected_count": 321,
            "active_count": 321,
            "births": 321,
            "continuations": 0,
            "removals": 0,
            "cumulative_removals": 0,
        },
        {
            "checkpoint": 2,
            "prefix_input_id": (
                "58ab7ff0d752f816af2a0cd4079381903db4c99075477e500307e2349ab11d5b"
            ),
            "provider_result_id": (
                "eb35d1ebf9a0235fc4cd27f39500e069b4900faa8177658a6c1fc1db07000d95"
            ),
            "discovery_id": (
                "0f8f134c3d41b0cbf81d7ebb93ff2e35cbcd17169733170e56232ded0be07f7c"
            ),
            "selection_id": (
                "26cb8258fdceb128c29b58212d7e8c78bf13de722b553e1d9dd7827b98f67e13"
            ),
            "tracking_id": (
                "7558ecec494f61895f9fa82c3e4f06d8833903b927da1b30a83e85cbaaa4d966"
            ),
            "candidate_count": 2832,
            "selected_count": 330,
            "active_count": 330,
            "births": 91,
            "continuations": 239,
            "removals": 82,
            "cumulative_removals": 82,
        },
        {
            "checkpoint": 3,
            "prefix_input_id": (
                "d5bbabac6a2c041ef91c5c31b68bedac4cf97980417ae7d304551295c65274df"
            ),
            "provider_result_id": (
                "9eec7386c944bbd980277aba7e32954a63f4bd404b2c35f2632cb938ccc5bff9"
            ),
            "discovery_id": (
                "2d2b639724f33cd2ab774c21852f5b9f31dfad8424e11cef342ea89efd533905"
            ),
            "selection_id": (
                "fba6a34c43175be404f0dfcfd33bb0f5116e504e57191e5c7e11a5951f2d6f04"
            ),
            "tracking_id": (
                "ea4b3c3ca0434104d618f2b5d6a6d3cc30ec449722e0020cb67a35151b1dc321"
            ),
            "candidate_count": 3106,
            "selected_count": 335,
            "active_count": 335,
            "births": 87,
            "continuations": 248,
            "removals": 82,
            "cumulative_removals": 164,
        },
        {
            "checkpoint": 4,
            "prefix_input_id": (
                "10d3f6cf3ba4031ecad0322e89a9c6058c3f504a465ace38c3d2d9635f6b00be"
            ),
            "provider_result_id": (
                "0f1e689158916f66901b436a26683fba6194eb0a01950891df7d2064491c8591"
            ),
            "discovery_id": (
                "ba7c22a19322060e30cf208b1e4bf2a3de49dd645209da248ed3b1e3aa00e0aa"
            ),
            "selection_id": (
                "a134a540ffffab8017374789e8c9c878a9f96e0be73a82a0baf6a93f38f527d2"
            ),
            "tracking_id": (
                "0dbcb2374f2571a64a352f8e6fd13e30a76ba7b5463a05aa200bc13e338da630"
            ),
            "candidate_count": 2819,
            "selected_count": 325,
            "active_count": 325,
            "births": 68,
            "continuations": 257,
            "removals": 78,
            "cumulative_removals": 242,
        },
        {
            "checkpoint": 5,
            "prefix_input_id": (
                "6397fc215f0c9d2fc7c6cdf1fe44e60e5530d7fef2c040cce2731661a5657a4c"
            ),
            "provider_result_id": (
                "45ebf182dec6855508244361933d553c53856ed0245fb9f1dc4c6337d96d256a"
            ),
            "discovery_id": (
                "c4d1b8d13c957ef88101c1aefd726a4235e673dd1e6933ba12db092583035b0e"
            ),
            "selection_id": (
                "0f8b10c8cc6511c64d06275e0bb72c2c8ff6d5566364ba8eca915ea53307ccac"
            ),
            "tracking_id": (
                "82bca487e57d4add2d938b8c1d13a93a3fe2f8600150fc34c0f638f05540c94f"
            ),
            "candidate_count": 2641,
            "selected_count": 323,
            "active_count": 323,
            "births": 78,
            "continuations": 245,
            "removals": 80,
            "cumulative_removals": 322,
        },
    )

    decision = replay._load_json(root / "decision.json")
    assert {
        key: decision[key]
        for key in (
            "initial_active_family_count",
            "final_active_family_count",
            "total_birth_count",
            "total_continuation_count",
            "total_source_removed_count",
            "attributed_removal_count",
            "unattributed_removal_count",
            "unique_removed_family_count",
            "cumulative_removed_family_count",
            "removed_family_reappearance_count",
            "candidate_id_turnover_count",
            "removal_checkpoint_count",
        )
    } == {
        "initial_active_family_count": 321,
        "final_active_family_count": 323,
        "total_birth_count": 645,
        "total_continuation_count": 989,
        "total_source_removed_count": 322,
        "attributed_removal_count": 322,
        "unattributed_removal_count": 0,
        "unique_removed_family_count": 322,
        "cumulative_removed_family_count": 322,
        "removed_family_reappearance_count": 0,
        "candidate_id_turnover_count": 989,
        "removal_checkpoint_count": 4,
    }
    assert decision["removal_cause_counts"] == {
        "first_anchor_evicted": 321,
        "first_anchor_left_context_evicted": 1,
    }


def test_canonical_loader_rejects_noncanonical_json(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    path.write_text(json.dumps({"b": 2, "a": 1}, indent=2) + "\n")
    with pytest.raises(replay.ReplayError, match="non-canonical"):
        replay._load_json(path)
