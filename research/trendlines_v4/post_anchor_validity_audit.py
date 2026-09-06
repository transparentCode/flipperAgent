"""Compact, evidence-only audit of post-anchor legacy line validity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    EmittedLine,
    analyze_legacy,
)


@dataclass(frozen=True, slots=True)
class PostAnchorAuditWindow:
    """Aggregate post-anchor body-crossing evidence for one window."""

    prefixes_audited: int
    support_emitted_lines: int
    resistance_emitted_lines: int
    emitted_lines_with_post_anchor_exposure: int
    post_anchor_bars_inspected: int
    emitted_lines_with_body_crossing: int
    support_lines_body_broken_at_cutoff: int
    resistance_lines_body_broken_at_cutoff: int
    total_body_crossings: int
    first_violation: dict[str, int | float | str] | None

    @property
    def total_emitted_lines(self) -> int:
        return self.support_emitted_lines + self.resistance_emitted_lines

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["total_emitted_lines"] = self.total_emitted_lines
        return payload


def post_anchor_body_crossings(
    bars: Sequence[Bar], line: EmittedLine, side: str
) -> tuple[tuple[int, float, float], ...]:
    """Return adverse body crossings strictly after an emitted line anchor."""

    if side not in ("support", "resistance"):
        raise ValueError(f"unknown side: {side}")
    if line.end_index < 0 or line.end_index >= len(bars):
        raise ValueError("line end_index must identify a bar in the input")

    crossings: list[tuple[int, float, float]] = []
    for index in range(line.end_index + 1, len(bars)):
        line_value = line.slope * index + line.intercept
        body_top = max(bars[index].open, bars[index].close)
        body_bottom = min(bars[index].open, bars[index].close)
        if side == "support" and body_bottom < line_value:
            crossings.append((index, line_value, body_bottom))
        elif side == "resistance" and body_top > line_value:
            crossings.append((index, line_value, body_top))
    return tuple(crossings)


def audit_window(bars: Sequence[Bar], pivot_window: int = 3) -> PostAnchorAuditWindow:
    """Audit every emitted G1 line at every causal prefix."""

    if pivot_window < 1:
        raise ValueError("pivot_window must be >= 1")

    emitted = {"support": 0, "resistance": 0}
    exposed_lines = 0
    inspected_bars = 0
    lines_with_crossing = 0
    broken_at_cutoff = {"support": 0, "resistance": 0}
    total_crossings = 0
    first_violation: dict[str, int | float | str] | None = None

    for prefix_length in range(1, len(bars) + 1):
        result = analyze_legacy(bars[:prefix_length], pivot_window)
        for side_result in (result.support, result.resistance):
            line = side_result.emitted_line
            if line is None:
                continue

            side = side_result.side
            emitted[side] += 1
            available_after_anchor = prefix_length - line.end_index - 1
            if available_after_anchor <= 0:
                continue

            exposed_lines += 1
            inspected_bars += available_after_anchor
            crossings = post_anchor_body_crossings(bars[:prefix_length], line, side)
            total_crossings += len(crossings)
            if not crossings:
                continue

            lines_with_crossing += 1
            broken_at_cutoff[side] += 1
            if first_violation is None:
                index, line_value, body_value = crossings[0]
                first_violation = {
                    "side": side,
                    "prefix_length": prefix_length,
                    "anchor_index": line.end_index,
                    "bar_index": index,
                    "bars_after_anchor": index - line.end_index,
                    "line_value": line_value,
                    "adverse_body_value": body_value,
                }

    return PostAnchorAuditWindow(
        prefixes_audited=len(bars),
        support_emitted_lines=emitted["support"],
        resistance_emitted_lines=emitted["resistance"],
        emitted_lines_with_post_anchor_exposure=exposed_lines,
        post_anchor_bars_inspected=inspected_bars,
        emitted_lines_with_body_crossing=lines_with_crossing,
        support_lines_body_broken_at_cutoff=broken_at_cutoff["support"],
        resistance_lines_body_broken_at_cutoff=broken_at_cutoff["resistance"],
        total_body_crossings=total_crossings,
        first_violation=first_violation,
    )


__all__ = [
    "PostAnchorAuditWindow",
    "audit_window",
    "post_anchor_body_crossings",
]
