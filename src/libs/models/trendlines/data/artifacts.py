"""Deterministic persistence helpers for trendlines replay artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from libs.models.trendlines.data.contracts import TrendlineArtifactRef, TrendlineDatasetManifest
from libs.models.trendlines.data.temporal import TemporalSplitManifest


def artifact_path(artifact: TrendlineArtifactRef) -> Path:
    root = Path(artifact.artifact_root)
    return root / artifact.relative_path if artifact.relative_path else root


def _write_json_artifact(payload: dict, artifact: TrendlineArtifactRef) -> Path:
    path = artifact_path(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _read_json_artifact(path_or_artifact: str | Path | TrendlineArtifactRef) -> dict:
    if isinstance(path_or_artifact, TrendlineArtifactRef):
        path = artifact_path(path_or_artifact)
    else:
        path = Path(path_or_artifact)
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_manifest_artifact(
    explicit_artifact: TrendlineArtifactRef | None,
    fallback_artifact: TrendlineArtifactRef | None,
) -> TrendlineArtifactRef:
    artifact = explicit_artifact or fallback_artifact
    if artifact is None:
        raise ValueError("An artifact reference is required for persistence")
    return artifact


def write_dataset_manifest(
    manifest: TrendlineDatasetManifest,
    artifact: TrendlineArtifactRef | None = None,
) -> Path:
    resolved = _resolve_manifest_artifact(artifact, manifest.artifact)
    return _write_json_artifact(manifest.to_dict(), resolved)


def read_dataset_manifest(
    path_or_artifact: str | Path | TrendlineArtifactRef,
) -> TrendlineDatasetManifest:
    return TrendlineDatasetManifest.from_dict(_read_json_artifact(path_or_artifact))


def write_temporal_split_manifest(
    manifest: TemporalSplitManifest,
    artifact: TrendlineArtifactRef,
) -> Path:
    return _write_json_artifact(manifest.to_dict(), artifact)


def read_temporal_split_manifest(
    path_or_artifact: str | Path | TrendlineArtifactRef,
) -> TemporalSplitManifest:
    return TemporalSplitManifest.from_dict(_read_json_artifact(path_or_artifact))


__all__ = [
    "artifact_path",
    "read_dataset_manifest",
    "read_temporal_split_manifest",
    "write_dataset_manifest",
    "write_temporal_split_manifest",
]