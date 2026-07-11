"""Evaluate one RegimeProbV1 parameter set on offline splits."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from libs.models.regime_prob_v1.optimization import (
    evaluate_oos,
    extract_profile_defaults,
    format_deploy_params,
    render_markdown_report,
)
from libs.models.regime_prob_v1.scripts._shared import (
    build_feature_and_labels,
    load_context_frames,
    load_ohlcv,
    read_json,
    write_json,
    write_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate RegimeProbV1 params on offline data")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--profile", default="edge_calibration")
    parser.add_argument("--playbook")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--input-csv")
    parser.add_argument("--context-csv", action="append", default=[])
    parser.add_argument("--params-json")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context_frames = load_context_frames(args.context_csv)
    ohlcv = load_ohlcv(
        asset=args.asset,
        timeframe=args.timeframe,
        input_csv=args.input_csv,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    feature_frame, label_frame = build_feature_and_labels(
        ohlcv,
        asset=args.asset,
        timeframe=args.timeframe,
        external_context_frames=context_frames or None,
    )
    params = _load_params(args.params_json, profile=args.profile)
    evaluation = evaluate_oos(
        feature_frame,
        label_frame,
        params,
        profile=args.profile,
        playbook=args.playbook,
        horizon=int(args.horizon),
    )
    payload = {
        "model_name": "RegimeProbV1",
        "asset": args.asset.upper(),
        "timeframe": args.timeframe,
        "profile": args.profile,
        "playbook": args.playbook,
        "horizon": int(args.horizon),
        "data": {
            "rows": int(len(feature_frame)),
            "start": feature_frame.index[0].isoformat() if len(feature_frame) else None,
            "end": feature_frame.index[-1].isoformat() if len(feature_frame) else None,
        },
        "best_trial": {
            "number": 0,
            "value": ((evaluation.get("validation") or {}).get("score")),
            "params": params,
            "validation": evaluation.get("validation"),
        },
        "oos": evaluation,
        "baseline_oos": None,
        "default_vs_tuned": None,
        "threshold_sweep": None,
        "deploy_params": format_deploy_params(params, profile=args.profile),
        "completed_trials": 1,
        "rejected_trials": int(not evaluation.get("deployed", False)),
        "n_trials": 1,
        "study_name": f"RegimeProbV1_evaluation_{args.asset.upper()}_{args.timeframe}_{args.profile}",
        "storage": None,
    }
    write_json(args.output_json, payload)
    if args.output_md:
        write_text(args.output_md, render_markdown_report(payload))
    return 0


def _load_params(path: str | None, *, profile: str) -> dict[str, Any]:
    if not path:
        return extract_profile_defaults(profile)
    payload = read_json(Path(path))
    if isinstance(payload, dict):
        deploy_params = payload.get("deploy_params")
        if isinstance(deploy_params, dict) and isinstance(deploy_params.get("params"), dict):
            return dict(deploy_params["params"])
        if isinstance(payload.get("params"), dict):
            return dict(payload["params"])
    raise ValueError(f"Could not find params payload in {path}")


if __name__ == "__main__":
    raise SystemExit(main())
