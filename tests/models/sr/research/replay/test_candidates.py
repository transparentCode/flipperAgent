from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError, replace
import inspect
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.replay.candidates import CandidateReplay
from libs.models.sr.scripts.atr_calibration.candidates import replay_candidate
from libs.models.sr.scripts.atr_calibration.config import load_calibration_config
from libs.models.sr.scripts.atr_calibration.contracts import CandidateReplay as LegacyCandidateReplay
from libs.models.sr.scripts.atr_calibration.runner import resolve_frozen_sr_config
from libs.models.sr.scripts.atr_calibration.source import build_development_capsule


_ROOT = Path(__file__).parents[5]


@pytest.fixture(scope="module")
def replay() -> CandidateReplay:
    config = load_calibration_config(_ROOT / "configs/sr_trials/taousdt_1d_atr_calibration.yaml")
    capsule = build_development_capsule(
        config,
        repo_root=_ROOT,
        implementation_commit=config.source_implementation_commit,
    )
    return replay_candidate(
        capsule,
        14,
        config=config,
        resolved_config=resolve_frozen_sr_config(config, repo_root=_ROOT),
    )


def test_legacy_candidate_replay_reexports_canonical_class_with_exact_signature(replay) -> None:
    fields = (
        "period",
        "reference_period",
        "common_start_index",
        "model_bars",
        "reference_atr",
        "initial_state",
        "final_state",
        "snapshots",
        "trace",
        "diagnostics",
    )
    assert LegacyCandidateReplay is CandidateReplay
    assert tuple(inspect.signature(CandidateReplay).parameters) == fields
    assert tuple(CandidateReplay.__dataclass_fields__) == fields
    assert LegacyCandidateReplay(**{name: getattr(replay, name) for name in fields}) == replay


def test_candidate_replay_remains_immutable_and_enforces_alignment(replay) -> None:
    with pytest.raises(FrozenInstanceError):
        replay.period = 7
    with pytest.raises(ContractValidationError, match="reference_atr must align to model_bars"):
        replace(replay, reference_atr=replay.reference_atr[:-1])
    with pytest.raises(ContractValidationError, match="model_bars must be a non-empty tuple"):
        replace(replay, model_bars=())
    with pytest.raises(ContractValidationError, match="reference_atr values must be positive"):
        replace(replay, reference_atr=(0.0, *replay.reference_atr[1:]))


def test_candidate_replay_contract_imports_no_studies_or_io(replay, monkeypatch) -> None:
    import libs.models.sr.research.replay.candidates as candidates_module

    parsed = ast.parse(inspect.getsource(candidates_module))
    imported_modules = [
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert not any(module.startswith("libs.models.sr.scripts") for module in imported_modules)
    assert not {"os", "pathlib", "subprocess"} & set(imported_modules)

    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("replay contract performed I/O"))
    assert CandidateReplay(**{name: getattr(replay, name) for name in CandidateReplay.__dataclass_fields__}) == replay
