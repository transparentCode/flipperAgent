"""Explicit runtime plugin factories for D6.

The static D2 catalog remains specification-only.  This module owns the small
runtime-only factory catalog and deliberately has no discovery or infrastructure
behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from apps.decision_app.contracts import ResolvedModelBinding
from libs.contracts.decision import DecisionModelPlugin, FrozenMapping

RuntimePluginFactory = Callable[[Mapping[str, object]], DecisionModelPlugin]


@dataclass(frozen=True, slots=True, kw_only=True)
class StateInitializationRequirement:
    """Bounded first-inception replay metadata for one stateful plugin."""

    trigger_steps: int

    def __post_init__(self) -> None:
        if isinstance(self.trigger_steps, bool) or not isinstance(
            self.trigger_steps, int
        ):
            raise TypeError("trigger_steps must be an integer")
        if self.trigger_steps <= 0:
            raise ValueError("trigger_steps must be positive")


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimePluginDefinition:
    """One exact runtime factory registration."""

    plugin_name: str
    plugin_version: str
    factory: RuntimePluginFactory
    initialization_requirement: (
        Callable[[ResolvedModelBinding], StateInitializationRequirement] | None
    ) = None

    def __post_init__(self) -> None:
        _require_non_empty(self.plugin_name, field_name="plugin_name")
        _require_non_empty(self.plugin_version, field_name="plugin_version")
        if not callable(self.factory):
            raise TypeError("runtime plugin factory must be callable")
        if self.initialization_requirement is not None and not callable(
            self.initialization_requirement
        ):
            raise TypeError("initialization_requirement must be callable")


class RuntimePluginCatalog:
    """Immutable exact-name/version runtime factory catalog."""

    __slots__ = ("_by_key", "_definitions")

    def __init__(self, definitions: Iterable[RuntimePluginDefinition]) -> None:
        entries = tuple(definitions)
        if any(not isinstance(item, RuntimePluginDefinition) for item in entries):
            raise TypeError(
                "runtime catalog entries must be RuntimePluginDefinition values"
            )
        by_key: dict[tuple[str, str], RuntimePluginDefinition] = {}
        for definition in entries:
            key = (definition.plugin_name, definition.plugin_version)
            if key in by_key:
                raise ValueError(
                    "duplicate runtime plugin registration: "
                    f"{definition.plugin_name}@{definition.plugin_version}"
                )
            by_key[key] = definition
        ordered = tuple(
            sorted(entries, key=lambda item: (item.plugin_name, item.plugin_version))
        )
        object.__setattr__(self, "_definitions", ordered)
        object.__setattr__(self, "_by_key", FrozenMapping(by_key))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("RuntimePluginCatalog is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("RuntimePluginCatalog is immutable")

    def __iter__(self):
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    @property
    def definitions(self) -> tuple[RuntimePluginDefinition, ...]:
        return self._definitions

    def resolve(self, plugin_name: str, plugin_version: str) -> RuntimePluginDefinition:
        key = (plugin_name, plugin_version)
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise ValueError(
                f"unknown runtime plugin: {plugin_name}@{plugin_version}"
            ) from exc

    def instantiate(self, binding: ResolvedModelBinding) -> DecisionModelPlugin:
        """Instantiate one plugin for one resolved binding."""

        if not isinstance(binding, ResolvedModelBinding):
            raise TypeError("binding must be a ResolvedModelBinding")
        definition = self.resolve(binding.plugin_name, binding.plugin_version)
        try:
            plugin = definition.factory(binding.parameters)
        except Exception as exc:
            raise ValueError(
                f"runtime plugin factory failed for {binding.slot_name}"
            ) from exc
        if not isinstance(plugin, DecisionModelPlugin):
            raise TypeError(
                f"runtime plugin {binding.slot_name} does not satisfy "
                "DecisionModelPlugin"
            )
        if plugin.spec != binding.model_spec:
            raise ValueError(
                f"runtime plugin {binding.slot_name} spec does not match resolved binding"
            )
        return plugin

    def initialization_for(
        self, binding: ResolvedModelBinding
    ) -> StateInitializationRequirement | None:
        """Resolve bounded first-inception metadata without loading a plugin."""

        if not isinstance(binding, ResolvedModelBinding):
            raise TypeError("binding must be a ResolvedModelBinding")
        definition = self.resolve(binding.plugin_name, binding.plugin_version)
        if definition.initialization_requirement is None:
            return None
        requirement = definition.initialization_requirement(binding)
        if not isinstance(requirement, StateInitializationRequirement):
            raise TypeError(
                "initialization_requirement must return StateInitializationRequirement"
            )
        return requirement


__all__ = [
    "RuntimePluginCatalog",
    "RuntimePluginDefinition",
    "RuntimePluginFactory",
    "StateInitializationRequirement",
]
