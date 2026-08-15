from __future__ import annotations

import pytest

from apps.decision_app.planning.catalog import CatalogError, PluginCatalog
from libs.contracts.decision import ModelSpec


def make_spec(name: str, version: str = "1") -> ModelSpec:
    return ModelSpec(
        name=name,
        version=version,
        stateful=False,
        output_kind="analytical",
        produces_artifact_type=f"{name.lower()}.v1",
    )


def test_catalog_resolves_exact_versions_and_iterates_stably() -> None:
    catalog = PluginCatalog(
        [make_spec("Boundary", "2"), make_spec("Regression"), make_spec("Boundary")]
    )

    assert catalog.resolve("Boundary", "1").version == "1"
    assert catalog.resolve("Boundary", "2").version == "2"
    assert [f"{spec.name}@{spec.version}" for spec in catalog] == [
        "Boundary@1",
        "Boundary@2",
        "Regression@1",
    ]
    assert catalog.specs == tuple(catalog)


def test_catalog_rejects_duplicate_exact_registration() -> None:
    with pytest.raises(CatalogError, match="duplicate plugin registration"):
        PluginCatalog([make_spec("Boundary"), make_spec("Boundary")])


def test_catalog_rejects_unknown_exact_registration() -> None:
    catalog = PluginCatalog([make_spec("Boundary")])
    with pytest.raises(CatalogError, match="unknown plugin specification"):
        catalog.resolve("Boundary", "2")


def test_catalog_is_immutable() -> None:
    catalog = PluginCatalog([make_spec("Boundary")])
    with pytest.raises(AttributeError):
        catalog._by_key = {}  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del catalog._specs  # type: ignore[attr-defined]
