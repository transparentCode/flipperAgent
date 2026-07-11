"""Batch manifest runner for RegimeProbV1 optimization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import yaml

from libs.models.regime_prob_v1.optimization.optimize import run_study
from libs.models.regime_prob_v1.optimization.reports import render_markdown_report

DatasetLoader = Callable[[dict[str, Any]], dict[str, Any]]


def load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(raw)
    return yaml.safe_load(raw) or {}


def expand_manifest_runs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand manifest assets/timeframes into concrete run dictionaries."""
    runs: list[dict[str, Any]] = []
    for item in manifest.get("runs") or []:
        asset = item.get("asset") or item.get("symbol")
        if not asset:
            raise ValueError(f"Manifest run missing asset: {item}")
        timeframes = item.get("timeframes") or [item.get("timeframe")]
        for timeframe in timeframes:
            if not timeframe:
                raise ValueError(f"Manifest run missing timeframe: {item}")
            expanded = dict(item)
            expanded["asset"] = str(asset).upper()
            expanded["timeframe"] = str(timeframe)
            expanded.pop("timeframes", None)
            runs.append(expanded)
    return runs


def run_manifest(
    manifest: dict[str, Any],
    *,
    dataset_loader: DatasetLoader,
    output_dir: Path | None = None,
    storage: str | None = None,
    resume: bool = False,
    write_markdown: bool = False,
    n_trials_override: int | None = None,
    profile_override: str | None = None,
    seed_override: int | None = None,
) -> dict[str, Any]:
    """Run a batch of RegimeProbV1 optimization studies from a manifest."""
    defaults = manifest.get("defaults") or {}
    runs = expand_manifest_runs(manifest)
    summaries: list[dict[str, Any]] = []
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for run in runs:
        cfg = {**defaults, **run}
        if n_trials_override is not None:
            cfg["n_trials"] = n_trials_override
        if profile_override is not None:
            cfg["profile"] = profile_override
        if seed_override is not None:
            cfg["seed"] = seed_override

        bundle = dataset_loader(cfg)
        result = run_study(
            bundle["feature_frame"],
            bundle["label_frame"],
            asset=cfg["asset"],
            timeframe=cfg["timeframe"],
            profile=cfg.get("profile", "edge_calibration"),
            playbook=cfg.get("playbook"),
            horizon=int(cfg.get("horizon", 3)),
            mtf_context_frame=bundle.get("mtf_context_frame"),
            n_trials=int(cfg.get("n_trials", 80)),
            study_name=cfg.get("study_name"),
            storage=storage or cfg.get("storage"),
            load_if_exists=bool(resume or cfg.get("resume", False)),
            seed=int(cfg.get("seed", 42)),
            validation_config=cfg.get("validation_config"),
            include_baseline=not bool(cfg.get("skip_baseline", False)),
            include_threshold_sweep=bool(cfg.get("threshold_sweep", False)),
            threshold_sweep_step=float(cfg.get("threshold_sweep_step", 0.02)),
            threshold_sweep_radius=int(cfg.get("threshold_sweep_radius", 2)),
        )

        json_path = None
        markdown_path = None
        if output_dir is not None:
            study_name = result["study_name"]
            json_path = output_dir / f"{study_name}.json"
            json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            if write_markdown:
                markdown_path = output_dir / f"{study_name}.md"
                markdown_path.write_text(render_markdown_report(result), encoding="utf-8")
        summaries.append(_run_summary(result, json_path=json_path, markdown_path=markdown_path))

    return {
        "model_name": "RegimeProbV1",
        "total_runs": len(runs),
        "completed_runs": len(summaries),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "storage": storage,
        "runs": summaries,
    }


def _run_summary(
    result: dict[str, Any],
    *,
    json_path: Path | None,
    markdown_path: Path | None,
) -> dict[str, Any]:
    oos = result.get("oos") or {}
    tuned_oos = ((oos.get("oos") or {}).get("aggregate") or {})
    delta = result.get("default_vs_tuned") or {}
    promotion = result.get("promotion_gate") or {}
    return {
        "asset": result["asset"],
        "timeframe": result["timeframe"],
        "profile": result["profile"],
        "playbook": result.get("playbook"),
        "horizon": result.get("horizon"),
        "study_name": result["study_name"],
        "completed_trials": result["completed_trials"],
        "rejected_trials": result["rejected_trials"],
        "oos_score": tuned_oos.get("score"),
        "oos_score_delta": delta.get("oos_score_delta"),
        "deployed": bool(oos.get("deployed")),
        "promotion_ready": bool(promotion.get("ready")),
        "rejection_reasons": list(oos.get("rejection_reasons") or []),
        "json_path": str(json_path) if json_path else None,
        "markdown_path": str(markdown_path) if markdown_path else None,
    }


__all__ = ["expand_manifest_runs", "load_manifest", "run_manifest"]
