"""Frozen causal baseline definitions for trendline adequacy studies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from libs.models.trendlines.contracts.identity import canonical_hash


BASELINE_SEMANTICS_VERSION = "trendlines.adequacy-baseline.v1"


class TrendlineAdequacyBaselineKind(str, Enum):
    """Naive and null geometry families reserved for later study phases."""

    RANDOM_VALID_PIVOT_PAIR = "random_valid_pivot_pair"
    RECENT_EXTREMA = "recent_extrema"
    HORIZONTAL_SUPPORT_RESISTANCE = "horizontal_support_resistance"
    TIME_SHIFTED_GEOMETRY = "time_shifted_geometry"
    ROLE_SHUFFLED_GEOMETRY = "role_shuffled_geometry"
    DENSITY_MATCHED_NULL = "density_matched_null"


class TrendlineAdequacyBaselineDataPolicy(str, Enum):
    """Permitted information boundary for baseline construction."""

    CAUSAL_PREFIX_ONLY = "causal_prefix_only"


_RANDOMIZED_KINDS = frozenset(
    {
        TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        TrendlineAdequacyBaselineKind.TIME_SHIFTED_GEOMETRY,
        TrendlineAdequacyBaselineKind.ROLE_SHUFFLED_GEOMETRY,
        TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
    }
)
_PRESERVABLE_FIELDS = frozenset(
    {
        "asset",
        "timeframe",
        "position",
        "role",
        "pivot_count",
        "line_count",
        "ray_count",
        "observation_density",
        "causal_prefix",
    }
)


@dataclass(frozen=True)
class TrendlineAdequacyBaselineSpec:
    """A content-addressed baseline definition; no baseline is executed here."""

    name: str
    kind: TrendlineAdequacyBaselineKind
    repetitions: int
    preserves: tuple[str, ...]
    seed: int | None = None
    data_policy: TrendlineAdequacyBaselineDataPolicy = (
        TrendlineAdequacyBaselineDataPolicy.CAUSAL_PREFIX_ONLY
    )

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("baseline name is required")
        kind = self.kind
        if not isinstance(kind, TrendlineAdequacyBaselineKind):
            try:
                kind = TrendlineAdequacyBaselineKind(str(kind).strip().lower())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown baseline kind: {self.kind!r}") from exc
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int):
            raise ValueError("baseline repetitions must be a non-boolean integer")
        if self.repetitions < 1:
            raise ValueError("baseline repetitions must be positive")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("baseline seed must be a non-boolean integer")
        if kind in _RANDOMIZED_KINDS and self.seed is None:
            raise ValueError("randomized baselines require an explicit seed")
        if kind not in _RANDOMIZED_KINDS and self.seed is not None:
            raise ValueError("deterministic baselines must not define a seed")
        policy = self.data_policy
        if not isinstance(policy, TrendlineAdequacyBaselineDataPolicy):
            try:
                policy = TrendlineAdequacyBaselineDataPolicy(str(policy).strip().lower())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown baseline data policy: {self.data_policy!r}") from exc
        if policy is not TrendlineAdequacyBaselineDataPolicy.CAUSAL_PREFIX_ONLY:
            raise ValueError("baseline data policy must be causal_prefix_only")
        preserves = tuple(str(value).strip() for value in self.preserves)
        if not preserves or any(not value for value in preserves):
            raise ValueError("baseline preserves must be non-empty")
        if len(set(preserves)) != len(preserves):
            raise ValueError("baseline preserves must be unique and ordered")
        unknown = set(preserves) - _PRESERVABLE_FIELDS
        if unknown:
            raise ValueError(f"unknown baseline preserved fields: {sorted(unknown)}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "data_policy", policy)
        object.__setattr__(self, "preserves", preserves)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "repetitions": self.repetitions,
            "preserves": list(self.preserves),
            "seed": self.seed,
            "data_policy": self.data_policy.value,
            "semantics_version": BASELINE_SEMANTICS_VERSION,
        }

    @property
    def baseline_id(self) -> str:
        return canonical_hash(
            self.to_dict(),
            semantics_version=BASELINE_SEMANTICS_VERSION,
        )


__all__ = [
    "BASELINE_SEMANTICS_VERSION",
    "TrendlineAdequacyBaselineDataPolicy",
    "TrendlineAdequacyBaselineKind",
    "TrendlineAdequacyBaselineSpec",
]
