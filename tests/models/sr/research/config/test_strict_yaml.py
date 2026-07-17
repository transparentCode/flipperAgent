from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.config.loader import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.config.strict_yaml import load_strict_research_yaml


def _write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "research.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_strict_loader_preserves_core_mapping_values_and_order(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "first: 1\nsecond:\n  nested: value\n")

    core = load_sr_config(path)
    strict = load_strict_research_yaml(path, description="research config")

    assert strict == core
    assert tuple(strict) == ("first", "second")


def test_strict_loader_rejects_recursive_duplicate_keys(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "outer:\n  value: 1\n  value: 2\n")

    with pytest.raises(ContractValidationError):
        load_strict_research_yaml(path, description="research config")


@pytest.mark.parametrize(
    "content",
    (
        "base: &base\n  value: 1\n",
        "base: {value: 1}\ncopy: *base\n",
        "base: &base\n  value: 1\ncopy:\n  <<: *base\n",
        "copy:\n  <<: {value: 1}\n",
    ),
)
def test_strict_loader_rejects_anchors_aliases_and_merge_keys(tmp_path: Path, content: str) -> None:
    path = _write_yaml(tmp_path, content)

    with pytest.raises(ContractValidationError, match="YAML aliases and merge keys are forbidden"):
        load_strict_research_yaml(path, description="research config")


@pytest.mark.parametrize("content", ("", "[]\n", "plain scalar\n"))
def test_strict_loader_rejects_empty_and_non_mapping_documents(tmp_path: Path, content: str) -> None:
    path = _write_yaml(tmp_path, content)

    with pytest.raises(ContractValidationError):
        load_strict_research_yaml(path, description="research config")
