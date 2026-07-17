"""Purely ordered baseline-trial orchestration around approved SR APIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

from libs.models.sr.domain import create_initial_state
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.evaluation.diagnostics import compute_diagnostics
from libs.models.sr.evaluation.trace_builder import build_evaluation_trace
from libs.models.sr.replay.runner import replay_bars

from .artifacts import publish_bundle
from .config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
    load_trial_config,
)
from .contracts import (
    BundlePublication,
    ResolvedInputConfig,
    TrialResult,
    TrialSpec,
)
from .dataset import HistoricalOHLCVAdapter, build_model_bars, fetch_validated_dataset


def _repository_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine repository implementation commit") from exc


def _config_path(repo_root: Path, relative_path: str) -> Path:
    root = repo_root.resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents:
        raise ContractValidationError("configuration path escaped repository root")
    return path


async def run_trial(
    trial: TrialSpec,
    *,
    repo_root: str | Path,
    adapter: HistoricalOHLCVAdapter | None = None,
    implementation_commit: str | None = None,
) -> tuple[TrialResult, BundlePublication]:
    """Run one frozen trial and publish its evidence bundle."""
    root = Path(repo_root).resolve()
    sr_config = load_resolved_sr_config(
        _config_path(root, trial.sr_config_path),
        asset=trial.symbol,
        timeframe=trial.timeframe,
    )
    if sr_config.asset != trial.symbol or sr_config.timeframe != trial.timeframe:
        raise ContractValidationError("resolved SR config does not match trial")
    resolved_input: ResolvedInputConfig = load_and_resolve_input_config(
        _config_path(root, trial.input_config_path),
        asset=trial.symbol,
        timeframe=trial.timeframe,
    )
    if resolved_input.asset != trial.symbol or resolved_input.timeframe != trial.timeframe:
        raise ContractValidationError("resolved input config does not match trial")

    if adapter is None:
        from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter

        adapter = BinanceNativeAdapter()
    dataset = await fetch_validated_dataset(adapter, trial)
    model_bars, atr_provenance = build_model_bars(dataset, resolved_input, trial)
    state_key = model_bars[0].state_key
    initial_state = create_initial_state(state_key, sr_config)
    final_state, snapshots = replay_bars(initial_state, model_bars, sr_config)
    trace = build_evaluation_trace(snapshots, sr_config)
    diagnostics = compute_diagnostics(trace)
    result = TrialResult(
        trial=trial,
        resolved_sr_config=sr_config,
        resolved_input=resolved_input,
        dataset=dataset,
        model_bars=model_bars,
        atr=atr_provenance,
        final_state=final_state,
        snapshots=snapshots,
        trace=trace,
        diagnostics=diagnostics,
    )
    publication = publish_bundle(
        result,
        repo_root=root,
        implementation_commit=implementation_commit or _repository_commit(root),
    )
    return result, publication


async def run_trial_from_config(
    config_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    adapter: HistoricalOHLCVAdapter | None = None,
    implementation_commit: str | None = None,
) -> tuple[TrialResult, BundlePublication]:
    root = Path(repo_root or Path.cwd()).resolve()
    trial_path = Path(config_path)
    if not trial_path.is_absolute():
        trial_path = root / trial_path
    trial = load_trial_config(trial_path)
    return await run_trial(
        trial,
        repo_root=root,
        adapter=adapter,
        implementation_commit=implementation_commit,
    )


def run_trial_sync(
    trial: TrialSpec,
    *,
    repo_root: str | Path,
    adapter: HistoricalOHLCVAdapter | None = None,
    implementation_commit: str | None = None,
) -> tuple[TrialResult, BundlePublication]:
    return asyncio.run(
        run_trial(
            trial,
            repo_root=repo_root,
            adapter=adapter,
            implementation_commit=implementation_commit,
        )
    )


__all__ = ["run_trial", "run_trial_from_config", "run_trial_sync"]
