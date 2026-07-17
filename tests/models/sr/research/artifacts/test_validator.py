from __future__ import annotations

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.artifacts.validator import load_strict_json


def test_load_strict_json_rejects_duplicate_keys_recursively(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"nested":{"key":1,"key":2}}', encoding="utf-8")

    with pytest.raises(ContractValidationError, match="invalid research JSON"):
        load_strict_json(path, description="research JSON")


def test_load_strict_json_rejects_nonfinite_values_with_path(tmp_path):
    path = tmp_path / "nonfinite.json"
    path.write_text('{"nested":[1e400]}', encoding="utf-8")

    with pytest.raises(ContractValidationError, match=r"non-finite research artifact value at json.nested\[0\]"):
        load_strict_json(
            path,
            description="research JSON",
            value_description="research artifact",
        )


def test_load_strict_json_requires_a_regular_file(tmp_path):
    path = tmp_path / "directory.json"
    path.mkdir()

    with pytest.raises(ContractValidationError, match="research JSON must be a regular file"):
        load_strict_json(path, description="research JSON")
