"""Compact, evidence-only causal audit for the frozen legacy pathfinder."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    analyze_legacy,
    extract_pivots,
)


@dataclass(frozen=True, slots=True)
class CausalAuditWindow:
    """Aggregate audit evidence for one fixed corpus window."""

    prefixes_audited: int
    support_emitted_paths: int
    resistance_emitted_paths: int
    path_pivot_references: int
    unconfirmed_path_pivot_violations: int
    confirmed_pivots_audited: int
    post_confirmation_truth_revisions: int
    first_violation: dict[str, int | str] | None

    @property
    def total_emitted_paths(self) -> int:
        return self.support_emitted_paths + self.resistance_emitted_paths

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["total_emitted_paths"] = self.total_emitted_paths
        return payload


def pivot_confirmation_index(pivot_index: int, pivot_window: int) -> int:
    """Return the final source index required to confirm a pivot."""

    return pivot_index + pivot_window


def pivot_available_at_prefix(
    pivot_index: int, prefix_length: int, pivot_window: int
) -> bool:
    """Apply the audit-only prefix availability rule."""

    return pivot_confirmation_index(pivot_index, pivot_window) < prefix_length


def unconfirmed_path_pivots(
    path: Sequence[tuple[int, float]], prefix_length: int, pivot_window: int
) -> tuple[tuple[int, int], ...]:
    """Return path pivots unavailable at the prefix, without repairing them."""

    return tuple(
        (index, pivot_confirmation_index(index, pivot_window))
        for index, _ in path
        if not pivot_available_at_prefix(index, prefix_length, pivot_window)
    )


def audit_window(bars: Sequence[Bar], pivot_window: int = 3) -> CausalAuditWindow:
    """Audit all prefix paths and fixed-window pivot truth for one window."""

    if pivot_window < 1:
        raise ValueError("pivot_window must be >= 1")

    emitted = {"support": 0, "resistance": 0}
    path_pivot_references = 0
    violations = 0
    first_violation: dict[str, int | str] | None = None
    for prefix_length in range(1, len(bars) + 1):
        result = analyze_legacy(bars[:prefix_length], pivot_window)
        for side_result in (result.support, result.resistance):
            path = side_result.winning_path
            if not path:
                continue
            emitted[side_result.side] += 1
            path_pivot_references += len(path)
            invalid = unconfirmed_path_pivots(path, prefix_length, pivot_window)
            violations += len(invalid)
            if invalid and first_violation is None:
                pivot_index, confirmation_index = invalid[0]
                first_violation = {
                    "side": side_result.side,
                    "prefix_length": prefix_length,
                    "pivot_index": pivot_index,
                    "confirmation_index": confirmation_index,
                }

    confirmed_pivots = 0
    revisions = 0
    for side in ("support", "resistance"):
        for pivot_index, _ in extract_pivots(bars, pivot_window, side):
            confirmation_prefix = (
                pivot_confirmation_index(pivot_index, pivot_window) + 1
            )
            if confirmation_prefix > len(bars):
                continue
            confirmed_pivots += 1
            original_truth = _fixed_pivot_truth(
                bars[:confirmation_prefix], pivot_index, pivot_window, side
            )
            for prefix_length in range(confirmation_prefix, len(bars) + 1):
                if (
                    _fixed_pivot_truth(
                        bars[:prefix_length], pivot_index, pivot_window, side
                    )
                    != original_truth
                ):
                    revisions += 1

    return CausalAuditWindow(
        prefixes_audited=len(bars),
        support_emitted_paths=emitted["support"],
        resistance_emitted_paths=emitted["resistance"],
        path_pivot_references=path_pivot_references,
        unconfirmed_path_pivot_violations=violations,
        confirmed_pivots_audited=confirmed_pivots,
        post_confirmation_truth_revisions=revisions,
        first_violation=first_violation,
    )


def _fixed_pivot_truth(
    bars: Sequence[Bar], pivot_index: int, pivot_window: int, side: str
) -> bool:
    left = pivot_index - pivot_window
    right = pivot_index + pivot_window
    if left < 0 or right >= len(bars):
        return False
    values = [
        bar.low if side == "support" else bar.high for bar in bars[left : right + 1]
    ]
    pivot_value = values[pivot_window]
    return pivot_value == (min(values) if side == "support" else max(values))


__all__ = [
    "CausalAuditWindow",
    "audit_window",
    "pivot_available_at_prefix",
    "pivot_confirmation_index",
    "unconfirmed_path_pivots",
]
