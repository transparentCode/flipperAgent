from dataclasses import FrozenInstanceError

import pytest

from libs.analysis_capabilities import AnalysisCapabilityDescriptor


def _descriptor() -> AnalysisCapabilityDescriptor:
    return AnalysisCapabilityDescriptor(
        capability_id="model.example",
        display_name="Example",
        description="Example structure analysis.",
        canonical_module="libs.example.api",
    )


def test_descriptor_is_value_equal_frozen_and_slotted() -> None:
    first = _descriptor()
    second = _descriptor()

    assert first == second
    assert first is not second
    assert not hasattr(first, "__dict__")

    with pytest.raises(FrozenInstanceError):
        first.description = "changed"


@pytest.mark.parametrize(
    "field_name, value",
    (
        ("capability_id", ""),
        ("display_name", "   "),
        ("description", "\t"),
        ("canonical_module", ""),
    ),
)
def test_descriptor_rejects_empty_text(field_name: str, value: str) -> None:
    values = {
        "capability_id": "model.example",
        "display_name": "Example",
        "description": "Example structure analysis.",
        "canonical_module": "libs.example.api",
    }
    values[field_name] = value

    with pytest.raises(ValueError):
        AnalysisCapabilityDescriptor(**values)


def test_descriptor_rejects_non_string_fields() -> None:
    values = {
        "capability_id": "model.example",
        "display_name": "Example",
        "description": "Example structure analysis.",
        "canonical_module": "libs.example.api",
    }
    values["canonical_module"] = None

    with pytest.raises(TypeError):
        AnalysisCapabilityDescriptor(**values)
