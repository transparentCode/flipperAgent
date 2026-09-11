"""Content-addressed research evidence artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.identity import canonical_hash
from .consumption import (
    claim_consumption,
    finalize_consumption,
    verify_consumption_claim,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchArtifact:
    schema_version: int
    conclusion: str
    promotion_recommendation: str
    evidence: Mapping[str, Any]
    artifact_id: str
    consumption_identity: str | None = None

    def __post_init__(self) -> None:
        if self.conclusion not in {"POSITIVE", "NEGATIVE", "INCONCLUSIVE"}:
            raise ValueError("invalid research conclusion")
        if not self.promotion_recommendation.strip():
            raise ValueError("promotion recommendation must be explicit")
        if self.consumption_identity is not None and not self.consumption_identity.strip():
            raise ValueError("consumption_identity must be non-empty")
        semantic = {"schema_version": self.schema_version, "conclusion": self.conclusion, "promotion_recommendation": self.promotion_recommendation, "evidence": self.evidence}
        if self.consumption_identity is not None:
            semantic["consumption_identity"] = self.consumption_identity
        expected = canonical_hash(semantic)
        if self.artifact_id != expected:
            raise ValueError("artifact_id does not match evidence")


def write_research_artifact(
    path: str | Path,
    *,
    conclusion: str,
    promotion_recommendation: str,
    evidence: Mapping[str, Any],
    consumption_identity: str | None = None,
    evidence_root: str | Path | None = None,
    consumption_claim: str | Path | None = None,
) -> ResearchArtifact:
    if consumption_identity is None:
        candidate_identity = evidence.get("consumption_identity") if isinstance(evidence, Mapping) else None
        if isinstance(candidate_identity, str):
            consumption_identity = candidate_identity
    if consumption_identity is not None and (
        not isinstance(consumption_identity, str) or not consumption_identity.strip()
    ):
        raise ValueError("consumption_identity must be non-empty")
    if consumption_identity is not None and evidence_root is None:
        raise ValueError("durable evidence_root is required for protected artifact identity")
    if consumption_claim is not None and consumption_identity is None:
        raise ValueError("consumption_claim requires a protected consumption_identity")
    semantic = {"schema_version": 1, "conclusion": conclusion, "promotion_recommendation": promotion_recommendation, "evidence": evidence}
    if consumption_identity is not None:
        semantic["consumption_identity"] = consumption_identity
    artifact_id = canonical_hash(semantic)
    artifact = ResearchArtifact(schema_version=1, conclusion=conclusion, promotion_recommendation=promotion_recommendation, evidence=evidence, artifact_id=artifact_id, consumption_identity=consumption_identity)
    destination = Path(path)
    if destination.exists():
        raise FileExistsError("research artifacts are append-only")
    claim_marker = None
    if consumption_identity is not None:
        if consumption_claim is None:
            claim_marker = claim_consumption(
                evidence_root,
                identity=consumption_identity,
                metadata={"artifact_id": artifact.artifact_id},
            )
        else:
            claim_marker = verify_consumption_claim(
                evidence_root,
                identity=consumption_identity,
                claim=consumption_claim,
            )
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema_version": artifact.schema_version, "conclusion": artifact.conclusion, "promotion_recommendation": artifact.promotion_recommendation, "evidence": artifact.evidence, "artifact_id": artifact.artifact_id, "consumption_identity": artifact.consumption_identity}, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    except FileExistsError:
        raise FileExistsError("research artifacts are append-only") from None
    if consumption_identity is not None and claim_marker is not None:
        finalize_consumption(
            evidence_root,
            identity=consumption_identity,
            claim=claim_marker,
            artifact_id=artifact.artifact_id,
            output_path=destination,
        )
    return artifact


__all__ = ["ResearchArtifact", "write_research_artifact"]
