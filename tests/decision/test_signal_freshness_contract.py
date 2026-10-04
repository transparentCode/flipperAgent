from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_decision_signal_freshness_matches_risk_signal_timeout() -> None:
    decision = yaml.safe_load(
        (ROOT / "configs/decision/global.yaml").read_text(encoding="utf-8")
    )
    risk = yaml.safe_load((ROOT / "configs/risk.yaml").read_text(encoding="utf-8"))

    assert decision["decision"]["signal_publication"]["signal_freshness_seconds"] == 300
    assert (
        decision["decision"]["signal_publication"]["signal_freshness_seconds"]
        == (risk["risk"]["mtf"]["signal_timeout_seconds"])
    )
