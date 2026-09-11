import pytest

from libs.analysis_capabilities import (
    AnalysisCapabilityDescriptor,
    AnalysisCapabilityRegistry,
)


def _descriptor(capability_id: str) -> AnalysisCapabilityDescriptor:
    return AnalysisCapabilityDescriptor(
        capability_id=capability_id,
        display_name=capability_id,
        description="Structure analysis.",
        canonical_module=f"libs.example.{capability_id.rsplit('.', 1)[-1]}",
    )


def test_registry_sorts_and_returns_an_immutable_ordered_collection() -> None:
    registry = AnalysisCapabilityRegistry(
        (
            _descriptor("model.trendlines"),
            _descriptor("model.regression"),
            _descriptor("model.sr"),
        )
    )

    assert tuple(item.capability_id for item in registry) == (
        "model.regression",
        "model.sr",
        "model.trendlines",
    )
    assert registry.descriptors == tuple(registry)
    assert len(registry) == 3

    with pytest.raises(TypeError):
        registry.descriptors[0] = _descriptor("model.other")

    assert not hasattr(registry, "register")
    assert not hasattr(registry, "add")


def test_registry_performs_exact_lookup_and_rejects_unknown_ids() -> None:
    trendlines = _descriptor("model.trendlines")
    registry = AnalysisCapabilityRegistry((trendlines, _descriptor("model.sr")))

    assert registry.get("model.trendlines") is trendlines
    with pytest.raises(KeyError):
        registry.get("model.unknown")


def test_registry_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate capability_id"):
        AnalysisCapabilityRegistry((_descriptor("model.sr"), _descriptor("model.sr")))


def test_registry_rejects_non_descriptor_entries() -> None:
    with pytest.raises(TypeError, match="registry entries"):
        AnalysisCapabilityRegistry((object(),))
