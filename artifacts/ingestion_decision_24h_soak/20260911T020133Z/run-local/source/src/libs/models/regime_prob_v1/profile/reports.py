"""Reporting helpers for RegimeProbV1 asset/timeframe profiles."""

from __future__ import annotations

import json

from libs.models.regime_prob_v1.profile.asset_tf_profile import AssetTimeframeProfileReport


def render_asset_timeframe_profile_markdown(report: AssetTimeframeProfileReport) -> str:
    """Render a review-friendly markdown profile summary."""
    profile = report.profile
    lines = [
        f"# RegimeProbV1 Profile: {profile.asset} {profile.timeframe}",
        "",
        "## Profile",
        f"- Recommended profile: `{profile.recommended_profile}`",
        f"- Liquidity tier: `{profile.liquidity_tier}`",
        f"- Volatility tier: `{profile.volatility_tier}`",
        f"- Trend persistence tier: `{profile.trend_persistence_tier}`",
        f"- Mean reversion tier: `{profile.mean_reversion_tier}`",
        f"- Breakout followthrough tier: `{profile.breakout_followthrough_tier}`",
        f"- False breakout tier: `{profile.false_breakout_tier}`",
        "",
        "## Cross-Asset",
        f"- BTC beta tier: `{profile.btc_beta_tier}`",
        f"- ETH beta tier: `{profile.eth_beta_tier}`",
        f"- TOTAL2 beta tier: `{profile.total2_beta_tier}`",
        f"- TOTAL3 beta tier: `{profile.total3_beta_tier}`",
        "",
        "## Metrics",
    ]
    for key in sorted(report.metrics):
        value = report.metrics[key]
        if isinstance(value, float):
            lines.append(f"- {key}: `{value:.8f}`")
        else:
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Diagnostics", "```json", json.dumps(report.diagnostics, indent=2, sort_keys=True), "```"])
    return "\n".join(lines) + "\n"


__all__ = ["render_asset_timeframe_profile_markdown"]
