"""Strict YAML boundary for SR research configuration documents."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from libs.models.sr.config.loader import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError


def _contains_merge_key(node: Node | None, seen: set[int]) -> bool:
    if node is None or id(node) in seen:
        return False
    seen.add(id(node))
    if isinstance(node, MappingNode):
        for key, value in node.value:
            if getattr(key, "value", None) == "<<":
                return True
            if _contains_merge_key(key, seen) or _contains_merge_key(value, seen):
                return True
    elif isinstance(node, SequenceNode):
        return any(_contains_merge_key(item, seen) for item in node.value)
    return False


def _read_research_yaml(path: str | Path, *, description: str) -> tuple[Path, str]:
    try:
        config_path = Path(path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"cannot read {description}: {path!r}") from exc
    try:
        return config_path, config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"cannot read {description}: {config_path}") from exc


def load_strict_research_yaml(
    path: str | Path,
    *,
    description: str,
    forbid_aliases: bool = True,
) -> Mapping[str, Any]:
    """Load research YAML through core loader after stricter syntax checks."""

    if type(description) is not str or not description.strip():
        raise ContractValidationError("research YAML description must be a non-empty string")
    if type(forbid_aliases) is not bool:
        raise ContractValidationError("research YAML forbid_aliases must be a boolean")
    config_path, text = _read_research_yaml(path, description=description)
    try:
        tokens = tuple(yaml.scan(text))
    except yaml.YAMLError:
        return load_sr_config(config_path)
    if forbid_aliases and any(isinstance(token, (AnchorToken, AliasToken)) for token in tokens):
        raise ContractValidationError("YAML aliases and merge keys are forbidden")
    try:
        documents = tuple(yaml.compose_all(text))
    except yaml.YAMLError:
        return load_sr_config(config_path)
    if any(_contains_merge_key(document, set()) for document in documents):
        raise ContractValidationError("YAML aliases and merge keys are forbidden")
    return load_sr_config(config_path)


__all__ = ["load_strict_research_yaml"]
