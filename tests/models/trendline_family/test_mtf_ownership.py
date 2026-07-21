from __future__ import annotations

import ast
from pathlib import Path

from libs.models.trendline.mtf import (
    LatestMTFSnapshotStore,
    MTFCluster,
    MTFGeometrySnapshot,
    MTFRelation,
    ProjectedMTFFamily,
    build_mtf_shadow_features,
    compose_mtf_snapshot,
    serialize_mtf_snapshot,
)
from libs.models.trendline.mtf.clustering import MTFCluster as OwnedMTFCluster
from libs.models.trendline.mtf.composition import compose_mtf_snapshot as OwnedCompose
from libs.models.trendline.mtf.contracts import (
    MTFGeometrySnapshot as OwnedMTFGeometrySnapshot,
    MTFRelation as OwnedMTFRelation,
    ProjectedMTFFamily as OwnedProjectedMTFFamily,
)
from libs.models.trendline.mtf.features import (
    build_mtf_shadow_features as OwnedFeatureBuilder,
)
from libs.models.trendline.mtf.serialization import (
    serialize_mtf_snapshot as OwnedSerializer,
)
from libs.models.trendline.mtf.store import LatestMTFSnapshotStore as OwnedStore
from libs.models.trendline_family.mtf import (
    LatestMTFSnapshotStore as CompatibilityStore,
    MTFCluster as CompatibilityMTFCluster,
    MTFGeometrySnapshot as CompatibilityMTFGeometrySnapshot,
    MTFRelation as CompatibilityMTFRelation,
    ProjectedMTFFamily as CompatibilityProjectedMTFFamily,
    build_mtf_shadow_features as CompatibilityFeatureBuilder,
    compose_mtf_snapshot as CompatibilityCompose,
    serialize_mtf_snapshot as CompatibilitySerializer,
)


_MTF_ROOT = (
    Path(__file__).parents[3]
    / "src"
    / "libs"
    / "models"
    / "trendline"
    / "mtf"
)


def _top_level_definitions(module: str) -> set[str]:
    path = _MTF_ROOT / f"{module}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_mtf_responsibility_modules_own_real_implementation() -> None:
    expected = {
        "contracts": {"MTFGeometrySnapshot", "ProjectedMTFFamily", "MTFRelation", "MTFCluster"},
        "projection": {"_project_families", "_projected_family_payload"},
        "freshness": {"_freshness", "_source_audit", "_source_atr"},
        "relations": {"_build_relations", "_finite_intersection"},
        "clustering": {"_build_clusters", "_make_cluster"},
        "serialization": {"compute_mtf_snapshot_id", "serialize_mtf_snapshot", "deserialize_mtf_snapshot"},
        "features": {"build_mtf_shadow_features", "_nearest_cluster"},
        "store": {"LatestMTFSnapshotStore"},
    }
    for module, required in expected.items():
        assert required <= _top_level_definitions(module)


def test_mtf_composition_contains_orchestration_not_responsibility_implementations() -> None:
    definitions = _top_level_definitions("composition")
    assert "compose_mtf_snapshot" in definitions
    assert not definitions.intersection(
        {
            "MTFGeometrySnapshot",
            "ProjectedMTFFamily",
            "MTFRelation",
            "MTFCluster",
            "_project_families",
            "_build_relations",
            "_build_clusters",
            "serialize_mtf_snapshot",
            "build_mtf_shadow_features",
            "LatestMTFSnapshotStore",
        }
    )


def test_mtf_public_and_compatibility_surfaces_keep_object_identity() -> None:
    assert MTFGeometrySnapshot is OwnedMTFGeometrySnapshot is CompatibilityMTFGeometrySnapshot
    assert ProjectedMTFFamily is OwnedProjectedMTFFamily is CompatibilityProjectedMTFFamily
    assert MTFRelation is OwnedMTFRelation is CompatibilityMTFRelation
    assert MTFCluster is OwnedMTFCluster is CompatibilityMTFCluster
    assert LatestMTFSnapshotStore is OwnedStore is CompatibilityStore
    assert compose_mtf_snapshot is OwnedCompose is CompatibilityCompose
    assert build_mtf_shadow_features is OwnedFeatureBuilder is CompatibilityFeatureBuilder
    assert serialize_mtf_snapshot is OwnedSerializer is CompatibilitySerializer
