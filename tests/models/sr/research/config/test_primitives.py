from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.config.primitives import (
    require_exact_keys,
    require_finite_number,
    require_git_commit,
    require_integer,
    require_mapping,
    require_nonempty_string,
    require_safe_relative_path,
    require_sha256,
    require_utc_timestamp,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.config import (
    _commit,
    _exact,
    _hash,
    _integer,
    _mapping,
    _number,
    _path,
    _string,
    _utc,
)


def test_mapping_and_exact_keys_fail_closed_with_deterministic_error() -> None:
    mapping = {"present": 1, "unexpected": 2}
    assert require_mapping(mapping, path="root") is mapping

    with pytest.raises(ContractValidationError, match="root must be a mapping with string keys"):
        require_mapping({1: "value"}, path="root")
    with pytest.raises(
        ContractValidationError,
        match=r"root keys mismatch; missing=\['missing'\] unknown=\['unexpected'\]",
    ):
        require_exact_keys(mapping, {"present", "missing"}, path="root")


def test_nonempty_string_preserves_valid_text_and_rejects_blank() -> None:
    assert require_nonempty_string(" value ", path="value") == " value "
    with pytest.raises(ContractValidationError, match="value must be a non-empty string"):
        require_nonempty_string(" \t", path="value")


@pytest.mark.parametrize("value", (True, False, 1.0))
def test_integer_rejects_booleans_and_non_exact_integers(value: object) -> None:
    with pytest.raises(ContractValidationError, match="count must be an integer >= 1"):
        require_integer(value, path="count", minimum=1)


def test_integer_enforces_inclusive_bounds() -> None:
    assert require_integer(2, path="count", minimum=1, maximum=2) == 2
    with pytest.raises(ContractValidationError, match="count must be an integer <= 2"):
        require_integer(3, path="count", minimum=1, maximum=2)


@pytest.mark.parametrize("value", (True, False, float("nan"), float("inf"), float("-inf")))
def test_finite_number_rejects_booleans_nan_and_infinity(value: object) -> None:
    with pytest.raises(ContractValidationError):
        require_finite_number(value, path="ratio")


def test_finite_number_enforces_bounds_and_normalizes_signed_zero() -> None:
    assert require_finite_number(-0.0, path="ratio") == 0.0
    assert require_finite_number(0.25, path="ratio", minimum=0.0, maximum=0.25) == 0.25
    with pytest.raises(ContractValidationError, match="ratio must be >= 0.0"):
        require_finite_number(-0.01, path="ratio", minimum=0.0)
    with pytest.raises(ContractValidationError, match="ratio must be <= 0.25"):
        require_finite_number(0.26, path="ratio", maximum=0.25)


def test_sha256_requires_exact_lowercase_digest() -> None:
    digest = "a" * 64
    assert require_sha256(digest, path="digest") == digest
    for invalid in ("a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ContractValidationError, match="digest must be a lowercase SHA-256 hex string"):
            require_sha256(invalid, path="digest")


def test_git_commit_requires_exact_sha1_or_sha256() -> None:
    assert require_git_commit("a" * 40, path="commit") == "a" * 40
    assert require_git_commit("b" * 64, path="commit") == "b" * 64
    for invalid in ("a" * 39, "a" * 41, "a" * 63, "a" * 65, "A" * 40, "g" * 40):
        with pytest.raises(ContractValidationError, match="commit must be a git SHA"):
            require_git_commit(invalid, path="commit")


def test_safe_relative_path_preserves_valid_nested_path() -> None:
    relative_path = "research\\audit/bundle.json"
    assert require_safe_relative_path(relative_path, path="artifact.path") == relative_path


@pytest.mark.parametrize(
    "value",
    (
        "/absolute.json",
        "C:\\drive\\absolute.json",
        "\\\\server\\share\\bundle.json",
        "../escaped.json",
        "nested/../escaped.json",
        "nul\x00path",
    ),
)
def test_safe_relative_path_rejects_unsafe_forms(value: str) -> None:
    with pytest.raises(ContractValidationError, match="artifact.path must be a safe relative path"):
        require_safe_relative_path(value, path="artifact.path")


def test_utc_timestamp_requires_trailing_z_and_optional_daily_boundary() -> None:
    timestamp = require_utc_timestamp("2024-01-02T03:04:05Z", path="window.start")
    assert timestamp == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert require_utc_timestamp(
        "2024-01-02T00:00:00Z",
        path="window.start",
        require_daily_boundary=True,
    ) == datetime(2024, 1, 2, tzinfo=timezone.utc)
    for invalid in ("2024-01-02T00:00:00+00:00", "2024-01-02T00:00:00"):
        with pytest.raises(ContractValidationError, match="window.start must use strict UTC Z notation"):
            require_utc_timestamp(invalid, path="window.start")
    with pytest.raises(ContractValidationError, match="window.start must align to a UTC daily boundary"):
        require_utc_timestamp(
            "2024-01-02T03:04:05Z",
            path="window.start",
            require_daily_boundary=True,
        )


def test_v1_12_private_wrappers_remain_compatible() -> None:
    digest = "c" * 64
    commit = "d" * 40
    assert _mapping({"field": "value"}, path="input") == {"field": "value"}
    assert _exact({"field": "value"}, {"field"}, path="input") is None
    assert _string("value", path="input") == "value"
    assert _hash(digest, path="input") == digest
    assert _commit(commit, path="input") == commit
    assert _integer(2, path="input", minimum=1) == 2
    assert _number(-0.0, path="input") == 0.0
    assert _path("research/audit.json", path="input") == "research/audit.json"
    assert _utc("2024-01-02T00:00:00Z", path="input") == datetime(
        2024,
        1,
        2,
        tzinfo=timezone.utc,
    )
