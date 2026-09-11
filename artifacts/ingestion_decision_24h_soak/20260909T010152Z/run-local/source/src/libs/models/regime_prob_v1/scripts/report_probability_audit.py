"""Render Markdown audits from RegimeProbV1 research artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from libs.models.regime_prob_v1.edge.calibration_report import render_empirical_calibration_markdown
from libs.models.regime_prob_v1.optimization import render_markdown_report
from libs.models.regime_prob_v1.profile.asset_tf_profile import AssetTimeframeProfile, AssetTimeframeProfileReport
from libs.models.regime_prob_v1.profile.reports import render_asset_timeframe_profile_markdown
from libs.models.regime_prob_v1.scripts._shared import read_json, write_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a RegimeProbV1 markdown audit artifact")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--playbook")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--segment", default="oos")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = read_json(Path(args.input_json))
    markdown = _render_payload(
        payload,
        playbook=args.playbook,
        horizon=int(args.horizon),
        segment=args.segment,
    )
    write_text(args.output_md, markdown)
    return 0


def _render_payload(payload: object, *, playbook: str | None, horizon: int, segment: str) -> str:
    if isinstance(payload, dict) and {"model_name", "best_trial", "oos"} <= set(payload):
        return render_markdown_report(payload)
    if isinstance(payload, dict) and {"support_count", "buckets"} <= set(payload):
        if not playbook:
            raise ValueError("--playbook is required for calibration-report payloads")
        return render_empirical_calibration_markdown(
            payload,
            playbook=playbook,
            horizon=horizon,
            segment=segment,
        )
    if isinstance(payload, dict) and {"profile", "metrics", "diagnostics"} <= set(payload):
        report = AssetTimeframeProfileReport(
            profile=AssetTimeframeProfile(**payload["profile"]),
            metrics=dict(payload["metrics"]),
            diagnostics=dict(payload["diagnostics"]),
        )
        return render_asset_timeframe_profile_markdown(report)
    raise ValueError("Unsupported RegimeProbV1 audit payload")


if __name__ == "__main__":
    raise SystemExit(main())
