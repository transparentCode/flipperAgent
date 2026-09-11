"""Deterministic, immutable registry for analysis capability metadata."""

from collections.abc import Iterable, Iterator
from types import MappingProxyType

from .descriptor import AnalysisCapabilityDescriptor


class AnalysisCapabilityRegistry:
    """Hold capability descriptors in deterministic ID order."""

    __slots__ = ("_by_id", "_descriptors")

    def __init__(self, descriptors: Iterable[AnalysisCapabilityDescriptor]) -> None:
        items = tuple(descriptors)
        for descriptor in items:
            if not isinstance(descriptor, AnalysisCapabilityDescriptor):
                raise TypeError(
                    "registry entries must be AnalysisCapabilityDescriptor instances"
                )

        ordered = tuple(sorted(items, key=lambda item: item.capability_id))
        by_id: dict[str, AnalysisCapabilityDescriptor] = {}
        for descriptor in ordered:
            if descriptor.capability_id in by_id:
                raise ValueError(f"duplicate capability_id: {descriptor.capability_id}")
            by_id[descriptor.capability_id] = descriptor

        self._by_id = MappingProxyType(by_id)
        self._descriptors = ordered

    @property
    def descriptors(self) -> tuple[AnalysisCapabilityDescriptor, ...]:
        """Return the immutable descriptors in ascending ID order."""

        return self._descriptors

    def get(self, capability_id: str) -> AnalysisCapabilityDescriptor:
        """Return the exact descriptor for ``capability_id``."""

        if not isinstance(capability_id, str):
            raise TypeError("capability_id must be a string")
        return self._by_id[capability_id]

    def __iter__(self) -> Iterator[AnalysisCapabilityDescriptor]:
        return iter(self._descriptors)

    def __len__(self) -> int:
        return len(self._descriptors)


__all__ = ("AnalysisCapabilityRegistry",)
