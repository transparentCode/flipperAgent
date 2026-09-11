"""Immutable metadata for one analysis capability."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisCapabilityDescriptor:
    """Describe a discoverable analysis capability without loading it."""

    capability_id: str
    display_name: str
    description: str
    canonical_module: str

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "display_name",
            "description",
            "canonical_module",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")


__all__ = ("AnalysisCapabilityDescriptor",)
