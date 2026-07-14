"""YAML loading boundary for SR configuration.

This adapter parses a YAML document into a mapping with duplicate-key
rejection. Schema validation and global/timeframe/asset-timeframe precedence
remain owned by ``SRConfigResolver``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from libs.models.sr.domain.identity import ContractValidationError


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate keys recursively."""


def _construct_unique_mapping(
    loader: Any, node: Any, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in mapping:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key ({key!r})",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_sr_config(path: str | Path) -> Mapping[str, Any]:
    """Load an SR YAML document without resolving or applying overrides."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            payload = yaml.load(stream, Loader=_UniqueKeySafeLoader)
    except OSError as exc:
        raise ContractValidationError(
            f"cannot read SR config: {config_path}"
        ) from exc
    except UnicodeError as exc:
        raise ContractValidationError(
            f"cannot decode SR config: {config_path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ContractValidationError(
            f"invalid SR YAML: {config_path}"
        ) from exc

    if not isinstance(payload, Mapping) or not payload:
        raise ContractValidationError(
            "SR YAML root must be a non-empty mapping"
        )
    return payload
