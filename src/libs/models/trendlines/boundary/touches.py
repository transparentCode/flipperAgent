"""Helpers for declustering structurally dense touch indices."""

from __future__ import annotations

from typing import Iterable, Sequence

from libs.models.trendlines.boundary.policy import TouchDeclusterConfig, TouchDiagnostics


def decluster_touch_indices(
    indices: Sequence[int] | Iterable[int],
    config: TouchDeclusterConfig | None = None,
    *,
    min_bars_between_touches: int | None = None,
) -> TouchDiagnostics:
    """Collapse dense touch clusters using a minimum retained index gap."""

    resolved_gap = _resolve_min_gap(config, min_bars_between_touches)
    raw_touch_indices = tuple(sorted({int(index) for index in indices}))

    if resolved_gap <= 0:
        effective_touch_indices = raw_touch_indices
    else:
        kept: list[int] = []
        for index in raw_touch_indices:
            if not kept or (index - kept[-1]) >= resolved_gap:
                kept.append(index)
        effective_touch_indices = tuple(kept)

    return TouchDiagnostics(
        raw_touch_count=len(raw_touch_indices),
        effective_touch_count=len(effective_touch_indices),
        raw_touch_indices=raw_touch_indices,
        effective_touch_indices=effective_touch_indices,
        min_bars_between_touches=resolved_gap,
    )


def _resolve_min_gap(
    config: TouchDeclusterConfig | None,
    min_bars_between_touches: int | None,
) -> int:
    if min_bars_between_touches is not None:
        if min_bars_between_touches < 0:
            raise ValueError("min_bars_between_touches must be >= 0")
        return int(min_bars_between_touches)
    if config is None:
        return 0
    return int(config.min_bars_between_touches)


__all__ = ["decluster_touch_indices"]