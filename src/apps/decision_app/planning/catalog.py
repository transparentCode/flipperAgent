"""Explicit immutable model-spec catalog for the D2 static planner."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import MappingProxyType

from libs.contracts.decision import ModelSpec


class CatalogError(ValueError):
    """Raised when a static plugin-spec catalog is invalid or incomplete."""


class PluginCatalog:
    """A deterministic catalog of explicitly supplied model specifications."""

    __slots__ = ("_by_key", "_specs")

    def __init__(self, specs: Iterable[ModelSpec]) -> None:
        entries = tuple(specs)
        if any(not isinstance(spec, ModelSpec) for spec in entries):
            raise TypeError("plugin catalog entries must be ModelSpec values")

        by_key: dict[tuple[str, str], ModelSpec] = {}
        for spec in entries:
            key = (spec.name, spec.version)
            if key in by_key:
                raise CatalogError(
                    f"duplicate plugin registration: {spec.name}@{spec.version}"
                )
            by_key[key] = spec

        ordered = tuple(sorted(entries, key=lambda spec: (spec.name, spec.version)))
        object.__setattr__(self, "_specs", ordered)
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("PluginCatalog is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("PluginCatalog is immutable")

    def __iter__(self) -> Iterator[ModelSpec]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def specs(self) -> tuple[ModelSpec, ...]:
        return self._specs

    def resolve(self, plugin_name: str, plugin_version: str) -> ModelSpec:
        """Resolve an exact plugin name/version pair."""

        key = (plugin_name, plugin_version)
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise CatalogError(
                f"unknown plugin specification: {plugin_name}@{plugin_version}"
            ) from exc

    def get(
        self, key: tuple[str, str], default: ModelSpec | None = None
    ) -> ModelSpec | None:
        """Return a spec by exact key without changing catalog state."""

        return self._by_key.get(key, default)


__all__ = ["CatalogError", "PluginCatalog"]
