"""VolCircuitBreakerRule — reactive volatility circuit breaker.

Rejects or reduces position size when volatility conditions indicate
elevated risk. Does NOT predict — reacts to observed conditions.

Three independent triggers:
1. Vol spike: realized vol exceeds N × median vol → REJECT
2. Rapid drawdown: account drawdown velocity too high → REJECT
3. Vol scaling: scale position size by inverse vol percentile → MODIFY

Reads thresholds from risk_config["vol_circuit_breaker"].
When regime descriptors are available in signal metadata, uses them.
Falls back to pure account-state reactive checks when regime data is absent.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from libs.contracts.schemas import RiskVerdict
from libs.risk.rules.base import RiskContext, RiskRule, RiskRuleRegistry


@RiskRuleRegistry.register("VolCircuitBreakerRule")
class VolCircuitBreakerRule(RiskRule):

    def __init__(self) -> None:
        self._dd_history: deque[tuple[float, float]] = deque(maxlen=100)
        self._last_reject_ts: float = 0.0

    @property
    def name(self) -> str:
        return "VolCircuitBreakerRule"

    def evaluate(self, context: RiskContext) -> RiskVerdict:
        cb_config = self._circuit_config(context.risk_config)
        if not cb_config.get("enabled", True):
            return RiskVerdict(action="ALLOW", rule_name=self.name)

        # Get regime descriptors from signal metadata (optional)
        regime = context.signal.metadata.get("regime_classification", {})

        # Trigger 1: Vol percentile spike (requires regime data)
        vol_pct = regime.get("vol_percentile")
        vol_reject = cb_config.get("vol_percentile_reject_threshold", 95)
        if vol_pct is not None and vol_pct > vol_reject:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=f"Vol percentile {vol_pct:.1f} exceeds circuit breaker threshold {vol_reject}",
            )

        # Trigger 2: Changepoint probability spike (requires regime data)
        cp_prob = regime.get("changepoint_prob")
        cp_reject = cb_config.get("changepoint_reject_threshold", 0.85)
        if cp_prob is not None and cp_prob > cp_reject:
            return RiskVerdict(
                action="REJECT",
                rule_name=self.name,
                reason=f"Changepoint probability {cp_prob:.3f} exceeds threshold {cp_reject}",
            )

        # Trigger 3: Drawdown velocity (always available — account state based)
        current_dd = context.account.current_drawdown_pct
        now = self._timestamp_seconds(context.signal.timestamp)
        self._dd_history.append((now, current_dd))

        velocity_pct = cb_config.get("drawdown_velocity_reject_pct", 2.0)
        velocity_window_h = cb_config.get("drawdown_velocity_window_hours", 4)
        velocity_window_s = velocity_window_h * 3600

        # Calculate drawdown velocity over window
        window_start = now - velocity_window_s
        window_entries = [
            (ts, dd) for ts, dd in self._dd_history
            if window_start <= ts < now
        ]
        if window_entries:
            baseline_dd = window_entries[0][1]
            dd_delta = current_dd - baseline_dd
            if dd_delta > velocity_pct:
                return RiskVerdict(
                    action="REJECT",
                    rule_name=self.name,
                    reason=(
                        f"Drawdown velocity {dd_delta:.2f}% over {velocity_window_h}h "
                        f"exceeds threshold {velocity_pct}%"
                    ),
                )

        # Trigger 4: Vol-based position scaling (requires regime data)
        if cb_config.get("vol_scaling_enabled", True) and vol_pct is not None:
            scale_start = cb_config.get("vol_scaling_start_percentile", 70)
            scale_floor = cb_config.get("vol_scaling_floor", 0.25)

            if vol_pct > scale_start:
                # Linear scaling from 1.0 at scale_start to scale_floor at 100
                scale_range = 100 - scale_start
                if scale_range > 0:
                    scale = 1.0 - (1.0 - scale_floor) * (vol_pct - scale_start) / scale_range
                    scale = max(scale_floor, min(1.0, scale))
                    adjusted = context.proposed_size * scale
                    return RiskVerdict(
                        action="MODIFY",
                        rule_name=self.name,
                        reason=f"Vol percentile {vol_pct:.1f} → position scaled to {scale:.2f}x",
                        adjusted_size=adjusted,
                    )

        return RiskVerdict(action="ALLOW", rule_name=self.name)

    @staticmethod
    def _circuit_config(risk_config: dict[str, Any]) -> dict[str, Any]:
        """Support both direct rule tests and production risk.yaml nesting."""
        direct = risk_config.get("vol_circuit_breaker")
        if isinstance(direct, dict):
            return direct
        nested = risk_config.get("global_limits", {}).get("vol_circuit_breaker", {})
        return nested if isinstance(nested, dict) else {}

    @staticmethod
    def _timestamp_seconds(value: Any) -> float:
        """Normalize signal timestamps before drawdown-window arithmetic."""
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return float(dt.timestamp())
        return float(value)
