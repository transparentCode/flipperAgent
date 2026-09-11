from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.research.artifacts import ResearchArtifact


def test_research_artifact_has_separate_promotion():
    evidence = {"source": "manifest"}
    artifact = ResearchArtifact(schema_version=1, conclusion="INCONCLUSIVE", promotion_recommendation="NO_PROMOTION", evidence=evidence, artifact_id=canonical_hash({"schema_version": 1, "conclusion": "INCONCLUSIVE", "promotion_recommendation": "NO_PROMOTION", "evidence": evidence}))
    assert artifact.promotion_recommendation == "NO_PROMOTION"
