from __future__ import annotations

import ast
from pathlib import Path

from libs.models.trendline import TrendlineFamilySnapshot as NewTrendlineFamilySnapshot
from libs.models.trendline.config import ResolvedTrendlineFamilyConfig as NewResolvedTrendlineFamilyConfig
from libs.models.trendline.contracts import FamilyTransition as NewFamilyTransition
from libs.models.trendline.optimization.candidate_optimizer import CandidateGeometryEvaluator as NewCandidateGeometryEvaluator
from libs.models.trendline.optimization.contracts import CandidateEvaluationSpec as NewCandidateEvaluationSpec
from libs.integrations.trendline_regime_v2.ablation import WeightedFeatureScorer, scorer_identity
from libs.models.trendline.provider import NativeDeterministicLineProvider as NewNativeDeterministicLineProvider
from libs.models.trendline.provider import CandidateGenerationResult as NewCandidateGenerationResult
from libs.models.trendline.provider import CandidateGenerationStatus as NewCandidateGenerationStatus
from libs.models.trendline.provider import LineCandidateProvider as NewLineCandidateProvider
from libs.models.trendline.discovery.contracts import CandidateGenerationResult as DiscoveryCandidateGenerationResult
from libs.models.trendline.discovery.contracts import CandidateGenerationStatus as DiscoveryCandidateGenerationStatus
from libs.models.trendline.discovery.contracts import LineCandidateProvider as DiscoveryLineCandidateProvider
from libs.models.trendline.discovery.provider import NativeDeterministicLineProvider as DiscoveryNativeDeterministicLineProvider
from libs.models.trendline.discovery.fitting.pathfinding import PathfindingLineFitter as DiscoveryPathfindingLineFitter
from libs.models.trendline.discovery.pivots.fractal import CausalFractalPivotExtractor as DiscoveryFractalPivotExtractor
from libs.models.trendline.fitting import PathfindingLineFitter
from libs.models.trendline.pivots import CausalFractalPivotExtractor
from libs.models.trendline.provider import provider_identity
from libs.models.trendline.repository import serialize_snapshot as new_serialize_snapshot
from libs.models.trendline_family import TrendlineFamilySnapshot as OldTrendlineFamilySnapshot
from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig as OldResolvedTrendlineFamilyConfig
from libs.models.trendline_family.contracts import FamilyTransition as OldFamilyTransition
from libs.models.trendline_family.optimization.candidate_optimizer import CandidateGeometryEvaluator as OldCandidateGeometryEvaluator
from libs.models.trendline_family.optimization.contracts import CandidateEvaluationSpec as OldCandidateEvaluationSpec
from libs.models.trendline_family.provider import NativeDeterministicLineProvider as OldNativeDeterministicLineProvider
from libs.models.trendline_family.provider import CandidateGenerationResult as OldCandidateGenerationResult
from libs.models.trendline_family.provider import CandidateGenerationStatus as OldCandidateGenerationStatus
from libs.models.trendline_family.provider import LineCandidateProvider as OldLineCandidateProvider
from libs.models.trendline_family.repository import serialize_snapshot as old_serialize_snapshot
from libs.models.trendlines_old import __name__ as legacy_copy_name
from libs.trendlines import __name__ as legacy_name

from .support import candidate_ohlcv, resolved_config


_ROOT = Path(__file__).parents[3] / "src" / "libs" / "models"
_CANONICAL_ROOT = _ROOT / "trendline"
_LEGACY_ROOT = Path(__file__).parents[3] / "src" / "libs" / "trendlines"
_FORBIDDEN_CANONICAL_IMPORTS = (
    "libs.models.trendline_family",
    "libs.trendlines",
    "libs.models.trendlines_old",
    "app.trendlines",
    "libs.models.sr",
)


def _imports_under(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_canonical_package_has_one_way_import_direction_and_runtime_research_boundary() -> None:
    imports = _imports_under(_CANONICAL_ROOT)
    assert not {value for value in imports if value.startswith(_FORBIDDEN_CANONICAL_IMPORTS)}
    runtime_files = [path for path in _CANONICAL_ROOT.glob("*.py") if path.name != "__init__.py"]
    runtime_imports: set[str] = set()
    for path in runtime_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                runtime_imports.add(node.module)
            elif isinstance(node, ast.Import):
                runtime_imports.update(alias.name for alias in node.names)
    assert not {value for value in runtime_imports if value.startswith("libs.models.trendline.optimization")}
    assert not {value for value in runtime_imports if value.startswith("libs.models.trendline.research_lab")}


def test_legacy_trendline_packages_remain_distinct_from_canonical_family_model() -> None:
    assert legacy_name == "libs.trendlines"
    assert legacy_copy_name == "libs.models.trendlines_old"
    assert not {value for value in _imports_under(_LEGACY_ROOT) if value.startswith("libs.models.trendline")}


def test_compatibility_modules_resolve_to_canonical_objects() -> None:
    assert OldTrendlineFamilySnapshot is NewTrendlineFamilySnapshot
    assert OldResolvedTrendlineFamilyConfig is NewResolvedTrendlineFamilyConfig
    assert OldFamilyTransition is NewFamilyTransition
    assert OldNativeDeterministicLineProvider is NewNativeDeterministicLineProvider
    assert OldCandidateGeometryEvaluator is NewCandidateGeometryEvaluator
    assert DiscoveryNativeDeterministicLineProvider is NewNativeDeterministicLineProvider
    assert DiscoveryPathfindingLineFitter is PathfindingLineFitter
    assert DiscoveryFractalPivotExtractor is CausalFractalPivotExtractor
    assert OldCandidateGenerationResult is NewCandidateGenerationResult is DiscoveryCandidateGenerationResult
    assert OldCandidateGenerationStatus is NewCandidateGenerationStatus is DiscoveryCandidateGenerationStatus
    assert OldLineCandidateProvider is NewLineCandidateProvider is DiscoveryLineCandidateProvider


def test_serialized_contract_and_provider_identity_parity(snapshot) -> None:
    assert old_serialize_snapshot(snapshot) == new_serialize_snapshot(snapshot)
    assert snapshot.transitions[0].to_dict() == NewFamilyTransition.from_dict(snapshot.transitions[0].to_dict()).to_dict()
    assert snapshot.model_version == "trendline_family_v1"
    assert provider_identity(NewNativeDeterministicLineProvider()) == "libs.models.trendline_family.provider.NativeDeterministicLineProvider"


def test_candidate_config_and_optimization_semantics_keep_historical_identity() -> None:
    frame = candidate_ohlcv()
    config = resolved_config()
    old_result = OldNativeDeterministicLineProvider().generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=config,
    )
    new_result = NewNativeDeterministicLineProvider().generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=config,
    )
    assert old_result.status is new_result.status
    assert old_result.reason_codes == new_result.reason_codes
    assert old_result.metadata == new_result.metadata
    assert tuple(candidate.to_dict() for candidate in old_result.candidates) == tuple(
        candidate.to_dict() for candidate in new_result.candidates
    )
    assert config.model_version == "trendline_family_v1"
    assert config.to_dict()["candidate"]["lookback_bars"] == 24
    old_spec = OldCandidateEvaluationSpec(
        provider_identity=provider_identity(OldNativeDeterministicLineProvider()),
        provider_state_hash="a" * 64,
        outcome_policy=None,
    )
    new_spec = NewCandidateEvaluationSpec(
        provider_identity=provider_identity(NewNativeDeterministicLineProvider()),
        provider_state_hash="a" * 64,
        outcome_policy=None,
    )
    assert old_spec.to_stage_spec().to_dict() == new_spec.to_stage_spec().to_dict()
    assert scorer_identity(WeightedFeatureScorer(weights={"trendline_family_valid": 1.0})) == (
        "libs.models.trendline_family.optimization.ablation.WeightedFeatureScorer"
    )
