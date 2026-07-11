"""Batch manifest runner for RegimeV2 optimization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path when run as a script.
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import yaml  # noqa: E402

from libs.models.regime_v2.optimization.optimize import (  # noqa: E402
    _load_ohlcv,
    _validation_config_from_args,
    run_study,
)
from libs.models.regime_v2.optimization.reports import render_markdown_report  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RegimeV2 optimization from a batch manifest")
    parser.add_argument("--manifest", type=Path, required=True, help="YAML or JSON batch manifest")
    parser.add_argument("--output-dir", type=Path, default=Path("research/regime_v2_optimization"))
    parser.add_argument("--storage", default=None, help="Optuna storage URL, e.g. sqlite:///research/regime_v2.db")
    parser.add_argument("--resume", action="store_true", help="Resume existing Optuna studies")
    parser.add_argument("--write-markdown", action="store_true", help="Write per-run markdown reports")
    parser.add_argument("--n-trials", type=int, default=None, help="Override manifest n_trials")
    parser.add_argument("--profile", default=None, choices=["core", "windows", "fusion", "policy", "full"])
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    manifest = load_manifest(args.manifest)
    report = run_manifest(
        manifest,
        output_dir=args.output_dir,
        storage=args.storage,
        resume=args.resume,
        write_markdown=args.write_markdown,
        n_trials_override=args.n_trials,
        profile_override=args.profile,
        seed_override=args.seed,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.output_dir / "index.json"
    index_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.write_markdown:
        (args.output_dir / "index.md").write_text(render_batch_markdown(report), encoding="utf-8")
    print(f"RegimeV2 batch complete: {report['completed_runs']}/{report['total_runs']} runs")
    print(f"Batch index: {index_path}")


def load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(raw)
    return yaml.safe_load(raw) or {}


def run_manifest(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    storage: str | None = None,
    resume: bool = False,
    write_markdown: bool = False,
    n_trials_override: int | None = None,
    profile_override: str | None = None,
    seed_override: int | None = None,
) -> dict[str, Any]:
    defaults = manifest.get("defaults") or {}
    runs = expand_manifest_runs(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    for run in runs:
        cfg = {**defaults, **run}
        if n_trials_override is not None:
            cfg["n_trials"] = n_trials_override
        if profile_override is not None:
            cfg["profile"] = profile_override
        if seed_override is not None:
            cfg["seed"] = seed_override

        args = _namespace_from_run(cfg)
        ohlcv = _load_ohlcv(args)
        study_name = cfg.get("study_name") or _study_name(cfg)
        result = run_study(
            ohlcv,
            asset=cfg["asset"],
            timeframe=cfg["timeframe"],
            profile=cfg.get("profile", "core"),
            n_trials=int(cfg.get("n_trials", 80)),
            horizon_bars=int(cfg.get("horizon_bars", 12)),
            study_name=study_name,
            storage=storage or cfg.get("storage"),
            load_if_exists=bool(resume or cfg.get("resume", False)),
            seed=int(cfg.get("seed", 42)),
            train_ratio=float(cfg.get("train_ratio", 0.60)),
            val_ratio=float(cfg.get("val_ratio", 0.20)),
            purge_bars=int(cfg.get("purge_bars", 24)),
            validation_config=_validation_config_from_args(args),
            include_baseline=not bool(cfg.get("skip_baseline", False)),
            include_threshold_sweep=bool(cfg.get("threshold_sweep", False)),
            threshold_sweep_step=float(cfg.get("threshold_sweep_step", 0.02)),
            threshold_sweep_radius=int(cfg.get("threshold_sweep_radius", 2)),
        )

        json_path = output_dir / f"{study_name}.json"
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        markdown_path = None
        if write_markdown:
            markdown_path = output_dir / f"{study_name}.md"
            markdown_path.write_text(render_markdown_report(result), encoding="utf-8")
        summaries.append(_run_summary(result, json_path=json_path, markdown_path=markdown_path))

    return {
        "model_name": "RegimeV2",
        "total_runs": len(runs),
        "completed_runs": len(summaries),
        "output_dir": str(output_dir),
        "storage": storage,
        "runs": summaries,
    }


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


def render_batch_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RegimeV2 Optimization Batch",
        "",
        f"- Completed runs: `{report.get('completed_runs')}/{report.get('total_runs')}`",
        f"- Storage: `{report.get('storage') or 'per-run/in-memory'}`",
        "",
        "| Asset | TF | Profile | Completed | Rejected | OOS Score | Delta | Deployed | Report |",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("runs", []):
        lines.append(
            f"| `{row['asset']}` | `{row['timeframe']}` | `{row['profile']}` | "
            f"`{row['completed_trials']}` | `{row['rejected_trials']}` | "
            f"`{_fmt(row.get('oos_score'))}` | `{_fmt(row.get('oos_score_delta'))}` | "
            f"`{row['deployed']}` | `{row.get('markdown_path') or row['json_path']}` |"
        )
    return "\n".join(lines) + "\n"


def _namespace_from_run(cfg: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        asset=cfg["asset"],
        timeframe=cfg["timeframe"],
        profile=cfg.get("profile", "core"),
        n_trials=cfg.get("n_trials"),
        horizon_bars=cfg.get("horizon_bars", 12),
        days=cfg.get("days", 180),
        since=cfg.get("since"),
        until=cfg.get("until"),
        input_csv=Path(cfg["input_csv"]) if cfg.get("input_csv") else None,
        output_json=None,
        output_markdown=None,
        study_name=cfg.get("study_name"),
        storage=cfg.get("storage"),
        resume=cfg.get("resume", False),
        seed=cfg.get("seed", 42),
        train_ratio=cfg.get("train_ratio", 0.60),
        val_ratio=cfg.get("val_ratio", 0.20),
        purge_bars=cfg.get("purge_bars", 24),
        window_bars=cfg.get("window_bars", 240),
        step_bars=cfg.get("step_bars", 120),
        min_window_bars=cfg.get("min_window_bars", 120),
        min_support_count=cfg.get("min_support_count", 20),
        min_support_rate=cfg.get("min_support_rate", 0.02),
        max_flip_rate=cfg.get("max_flip_rate", 0.35),
        max_policy_turnover=cfg.get("max_policy_turnover", 0.45),
        min_oos_score_ratio=cfg.get("min_oos_score_ratio", 0.50),
        skip_baseline=cfg.get("skip_baseline", False),
        threshold_sweep=cfg.get("threshold_sweep", False),
        threshold_sweep_step=cfg.get("threshold_sweep_step", 0.02),
        threshold_sweep_radius=cfg.get("threshold_sweep_radius", 2),
    )


def _study_name(cfg: dict[str, Any]) -> str:
    return f"RegimeV2_{str(cfg['asset']).upper()}_{cfg['timeframe']}_{cfg.get('profile', 'core')}"


def _run_summary(
    result: dict[str, Any],
    *,
    json_path: Path,
    markdown_path: Path | None,
) -> dict[str, Any]:
    oos = result.get("oos") or {}
    tuned_oos = ((oos.get("oos") or {}).get("aggregate") or {})
    delta = result.get("default_vs_tuned") or {}
    return {
        "asset": result["asset"],
        "timeframe": result["timeframe"],
        "profile": result["profile"],
        "study_name": result["study_name"],
        "completed_trials": result["completed_trials"],
        "rejected_trials": result["rejected_trials"],
        "oos_score": tuned_oos.get("score"),
        "oos_score_delta": delta.get("oos_score_delta"),
        "deployed": bool(oos.get("deployed")),
        "rejection_reasons": list(oos.get("rejection_reasons") or []),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path) if markdown_path else None,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8f}"
    return str(value)


if __name__ == "__main__":
    main()
