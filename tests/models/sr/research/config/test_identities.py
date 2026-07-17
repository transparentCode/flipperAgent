from __future__ import annotations

import ast
import builtins
from collections import Counter
from dataclasses import FrozenInstanceError
import inspect

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.config.identities import (
    BundleReference,
    ConfigReference,
    ContentIdentity,
    SourceIdentity,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.config import (
    CandidateAuditConfig,
    FrozenSource,
    UpstreamV10,
    UpstreamV11,
    UpstreamV19,
    load_candidate_audit_config,
)


_SHA256 = "a" * 64
_SHA1 = "b" * 40


@pytest.mark.parametrize(
    ("identity", "payload"),
    (
        (ConfigReference("configs/trial.yaml", _SHA256), {"path": "configs/trial.yaml", "sha256": _SHA256}),
        (
            BundleReference("research/bundle", _SHA256, _SHA1),
            {
                "path": "research/bundle",
                "bundle_id": _SHA256,
                "implementation_commit": _SHA1,
            },
        ),
        (ContentIdentity(_SHA256, 0), {"sha256": _SHA256, "byte_length": 0}),
        (
            SourceIdentity(_SHA256, "c" * 64, "d" * 64, 1),
            {
                "source_bundle_id": _SHA256,
                "source_id": "c" * 64,
                "bars_sha256": "d" * 64,
                "row_count": 1,
            },
        ),
    ),
)
def test_identity_contracts_are_immutable_and_have_stable_payloads(identity, payload) -> None:
    assert identity.to_payload() == payload
    assert identity.to_payload() == payload
    with pytest.raises(FrozenInstanceError):
        setattr(identity, next(iter(identity.__dataclass_fields__)), "mutated")


@pytest.mark.parametrize("identity_type", (ConfigReference, BundleReference))
@pytest.mark.parametrize(
    "path",
    ("/absolute.yaml", "C:\\absolute.yaml", "\\\\server\\share\\bundle", "../escape", "nul\x00path"),
)
def test_path_identities_reject_unsafe_relative_paths(identity_type, path: str) -> None:
    arguments = (path, _SHA256) if identity_type is ConfigReference else (path, _SHA256, _SHA1)
    with pytest.raises(ContractValidationError):
        identity_type(*arguments)


@pytest.mark.parametrize("invalid", ("A" * 64, "g" * 64, "a" * 63))
def test_identity_contracts_reject_non_lowercase_sha256(invalid: str) -> None:
    with pytest.raises(ContractValidationError):
        ConfigReference("configs/trial.yaml", invalid)
    with pytest.raises(ContractValidationError):
        ContentIdentity(invalid, 0)
    with pytest.raises(ContractValidationError):
        SourceIdentity(_SHA256, invalid, _SHA256, 1)


def test_bundle_reference_accepts_exact_sha1_and_sha256_commits() -> None:
    assert BundleReference("research/bundle", _SHA256, _SHA1).implementation_commit == _SHA1
    assert BundleReference("research/bundle", _SHA256, "c" * 64).implementation_commit == "c" * 64
    for invalid in ("a" * 39, "a" * 41, "a" * 63, "a" * 65, "A" * 40, "g" * 40):
        with pytest.raises(ContractValidationError):
            BundleReference("research/bundle", _SHA256, invalid)


@pytest.mark.parametrize("byte_length", (True, False, -1))
def test_content_identity_rejects_boolean_and_negative_byte_lengths(byte_length: int) -> None:
    with pytest.raises(ContractValidationError):
        ContentIdentity(_SHA256, byte_length)


def test_content_identity_accepts_zero_and_positive_byte_lengths() -> None:
    assert ContentIdentity(_SHA256, 0).byte_length == 0
    assert ContentIdentity(_SHA256, 1).byte_length == 1


@pytest.mark.parametrize("row_count", (True, False, 0))
def test_source_identity_requires_positive_non_boolean_row_count(row_count: int) -> None:
    with pytest.raises(ContractValidationError):
        SourceIdentity(_SHA256, "c" * 64, "d" * 64, row_count)


def test_source_identity_accepts_positive_row_count() -> None:
    assert SourceIdentity(_SHA256, "c" * 64, "d" * 64, 1).row_count == 1


def test_identity_contracts_have_no_study_import_or_io(monkeypatch) -> None:
    import libs.models.sr.research.config.identities as identities_module

    parsed = ast.parse(inspect.getsource(identities_module))
    imported_modules = [
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert not any(module.startswith("libs.models.sr.scripts") for module in imported_modules)
    assert not {"os", "pathlib", "subprocess"} & set(imported_modules)

    def fail_open(*args, **kwargs):
        raise AssertionError("identity contract performed I/O")

    monkeypatch.setattr(builtins, "open", fail_open)
    assert ConfigReference("configs/trial.yaml", _SHA256).to_payload()["sha256"] == _SHA256


@pytest.mark.parametrize(
    ("cls", "fields"),
    (
        (UpstreamV11, ("config_path", "config_hash", "bundle_path", "bundle_id", "study_id", "implementation_commit", "manifest_sha256", "manifest_bytes", "study_sha256", "study_bytes")),
        (UpstreamV19, ("config_path", "config_hash", "bundle_path", "bundle_id", "study_id", "implementation_commit", "disposition", "manifest_sha256", "manifest_bytes", "study_sha256", "study_bytes")),
        (UpstreamV10, ("config_path", "config_hash", "bundle_path", "bundle_id", "audit_id", "implementation_commit", "manifest_sha256", "manifest_bytes", "audit_sha256", "audit_bytes", "chart_sha256", "chart_bytes")),
        (FrozenSource, ("source_bundle_id", "upstream_source_bundle_id", "source_id", "bars_sha256", "row_count", "start", "end", "grid_policy", "sr_config_path", "sr_config_hash", "input_config_path", "input_config_hash")),
    ),
)
def test_v1_12_study_identity_signatures_remain_unchanged(cls, fields: tuple[str, ...]) -> None:
    assert tuple(inspect.signature(cls).parameters) == fields
    assert tuple(cls.__dataclass_fields__) == fields


def test_v1_12_config_payload_hash_remains_frozen() -> None:
    config = load_candidate_audit_config(
        "configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml"
    )
    assert tuple(inspect.signature(CandidateAuditConfig).parameters) == (
        "version",
        "trial_name",
        "venue",
        "asset",
        "timeframe",
        "v11",
        "v19",
        "v10",
        "source",
        "replay",
        "decision_categories",
        "readiness",
        "artifact",
    )
    assert tuple(CandidateAuditConfig.__dataclass_fields__) == (
        *inspect.signature(CandidateAuditConfig).parameters,
        "config_hash",
    )
    assert tuple(config.to_payload()) == (
        "version",
        "trial",
        "inputs",
        "protocol",
        "decisions",
        "gates",
        "artifact",
    )
    assert config.config_hash == "9855c190ed91744b7a6bd86590be33d480bdf44cc94cc51a29e82eec9d4b099e"


def test_v1_12_parsing_instantiates_neutral_identity_contracts(monkeypatch) -> None:
    import libs.models.sr.scripts.candidate_reinforcement_audit.config as candidate_config_module

    calls: list[str] = []

    def spy(identity_type):
        def validate(*args, **kwargs):
            calls.append(identity_type.__name__)
            return identity_type(*args, **kwargs)

        return validate

    monkeypatch.setattr(candidate_config_module, "ConfigReference", spy(ConfigReference))
    monkeypatch.setattr(candidate_config_module, "BundleReference", spy(BundleReference))
    monkeypatch.setattr(candidate_config_module, "ContentIdentity", spy(ContentIdentity))
    monkeypatch.setattr(candidate_config_module, "SourceIdentity", spy(SourceIdentity))

    config = candidate_config_module.load_candidate_audit_config(
        "configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml"
    )

    assert config.config_hash == "9855c190ed91744b7a6bd86590be33d480bdf44cc94cc51a29e82eec9d4b099e"
    assert Counter(calls) == {
        "ConfigReference": 3,
        "BundleReference": 3,
        "ContentIdentity": 7,
        "SourceIdentity": 1,
    }
