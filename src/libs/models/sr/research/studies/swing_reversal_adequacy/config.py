"""Strict, fully frozen configuration for the SR-V2.2 study."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from libs.models.sr.detection.causal_swing_reversal import CausalSwingReversalConfig
from libs.models.sr.domain import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.config import (
    require_exact_keys,
    require_finite_number,
    require_git_commit,
    require_integer,
    require_mapping,
    require_nonempty_string,
    require_safe_relative_path,
    require_sha256,
    require_utc_timestamp,
)
from libs.models.sr.research.config.strict_yaml import load_strict_research_yaml
from libs.models.sr.research.windows import CohortFold


CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v2.2-taousdt-1d-swing-reversal-adequacy"
VENUE, ASSET, TIMEFRAME = "binance_usdm", "TAOUSDT", "1d"
SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
SOURCE_IMPLEMENTATION_COMMIT = "be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2"
SOURCE_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
SOURCE_CAPSULE_BUNDLE_ID = (
    "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
)
SOURCE_BARS_SHA256 = "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
SOURCE_GRID_SHA256 = "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8"
SOURCE_ROWS = 629
SOURCE_START, SOURCE_END = (
    datetime(2024, 4, 11, tzinfo=timezone.utc),
    datetime(2025, 12, 31, tzinfo=timezone.utc),
)
SOURCE_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"
ATR_PAYLOAD = {
    "method": "wilder_rma",
    "period": 14,
    "seed": "sma",
    "common_start_index": 28,
}
OUTCOME_PAYLOAD = {
    "first_touch_offset_bars": 1,
    "touch_search_bars": 50,
    "horizon_bars": 10,
    "window_policy": "half_open_utc_daily",
}
APPROVED_DETECTOR = {"reversal_atr": 1.5}
APPROVED_GATES = {
    "minimum_completed_pairs": 24,
    "minimum_comparable_folds": 4,
    "minimum_pairs_per_comparable_fold": 4,
    "minimum_completed_naive_controls_per_side_per_comparable_fold": 4,
    "minimum_pooled_median_excess_quality_atr": 0.10,
    "minimum_positive_comparable_fold_fraction": 0.60,
    "minimum_worst_comparable_fold_excess_atr": -0.10,
}
FOLD_BOUNDS = (
    (
        "2024_q3",
        datetime(2024, 7, 1, tzinfo=timezone.utc),
        datetime(2024, 10, 1, tzinfo=timezone.utc),
    ),
    (
        "2024_q4",
        datetime(2024, 10, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 1, tzinfo=timezone.utc),
    ),
    (
        "2025_q1",
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 4, 1, tzinfo=timezone.utc),
    ),
    (
        "2025_q2",
        datetime(2025, 4, 1, tzinfo=timezone.utc),
        datetime(2025, 7, 1, tzinfo=timezone.utc),
    ),
    (
        "2025_q3",
        datetime(2025, 7, 1, tzinfo=timezone.utc),
        datetime(2025, 10, 1, tzinfo=timezone.utc),
    ),
    (
        "2025_q4",
        datetime(2025, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    ),
)
CONTROL_SIDE_ORDER = (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)
DISPOSITIONS = (
    "SWING_REVERSAL_BEATS_NAIVE_NULL",
    "SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL",
    "INSUFFICIENT_EVIDENCE",
)
ARTIFACT_MEMBERS = ("manifest.json", "study.json", "cases.json")
STAGE = "swing_reversal_adequacy_development"


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    return require_mapping(value, path=path)


def _string(value: Any, *, path: str) -> str:
    return require_nonempty_string(value, path=path)


def _path(value: Any, *, path: str) -> str:
    return require_safe_relative_path(value, path=path)


def _timestamp(value: Any, *, path: str) -> datetime:
    if type(value) is datetime:
        if (
            value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != timezone.utc.utcoffset(value)
        ):
            raise ContractValidationError(f"{path} must be UTC")
        if value.hour or value.minute or value.second or value.microsecond:
            raise ContractValidationError(f"{path} must be a UTC daily boundary")
        return value.astimezone(timezone.utc)
    return require_utc_timestamp(value, path=path, require_daily_boundary=True)


@dataclass(frozen=True)
class FrozenSource:
    bundle_path: str
    bundle_id: str
    implementation_commit: str
    source_id: str
    source_bundle_id: str
    bars_sha256: str
    grid_sha256: str
    row_count: int
    start: datetime
    end: datetime
    grid_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bundle_path", _path(self.bundle_path, path="source.bundle_path")
        )
        for name in (
            "bundle_id",
            "source_id",
            "source_bundle_id",
            "bars_sha256",
            "grid_sha256",
        ):
            object.__setattr__(
                self, name, require_sha256(getattr(self, name), path=f"source.{name}")
            )
        object.__setattr__(
            self,
            "implementation_commit",
            require_git_commit(
                self.implementation_commit, path="source.implementation_commit"
            ),
        )
        object.__setattr__(
            self,
            "row_count",
            require_integer(self.row_count, path="source.row_count", minimum=1),
        )
        object.__setattr__(self, "start", _timestamp(self.start, path="source.start"))
        object.__setattr__(self, "end", _timestamp(self.end, path="source.end"))
        object.__setattr__(
            self, "grid_policy", _string(self.grid_policy, path="source.grid_policy")
        )
        if self.to_payload() != {
            "bundle_path": f"research/tmp_sr_v1_7/source/{SOURCE_BUNDLE_ID}",
            "bundle_id": SOURCE_BUNDLE_ID,
            "implementation_commit": SOURCE_IMPLEMENTATION_COMMIT,
            "source_id": SOURCE_ID,
            "source_bundle_id": SOURCE_CAPSULE_BUNDLE_ID,
            "bars_sha256": SOURCE_BARS_SHA256,
            "grid_sha256": SOURCE_GRID_SHA256,
            "row_count": SOURCE_ROWS,
            "start": utc_isoformat(SOURCE_START),
            "end": utc_isoformat(SOURCE_END),
            "grid_policy": SOURCE_GRID_POLICY,
        }:
            raise ContractValidationError(
                "source is not the approved frozen TAOUSDT development identity"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "bundle_path": self.bundle_path,
            "bundle_id": self.bundle_id,
            "implementation_commit": self.implementation_commit,
            "source_id": self.source_id,
            "source_bundle_id": self.source_bundle_id,
            "bars_sha256": self.bars_sha256,
            "grid_sha256": self.grid_sha256,
            "row_count": self.row_count,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "grid_policy": self.grid_policy,
        }


@dataclass(frozen=True)
class FrozenSection:
    name: str
    payload: dict[str, object]
    expected: dict[str, object]

    def __post_init__(self) -> None:
        if type(self.payload) is not dict or self.payload != self.expected:
            raise ContractValidationError(
                f"{self.name} is not the approved immutable V2.2 payload"
            )

    def to_payload(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(frozen=True)
class AdequacyGates:
    minimum_completed_pairs: int
    minimum_comparable_folds: int
    minimum_pairs_per_comparable_fold: int
    minimum_completed_naive_controls_per_side_per_comparable_fold: int
    minimum_pooled_median_excess_quality_atr: float
    minimum_positive_comparable_fold_fraction: float
    minimum_worst_comparable_fold_excess_atr: float

    def __post_init__(self) -> None:
        for name in tuple(self.__dataclass_fields__)[:4]:
            object.__setattr__(
                self,
                name,
                require_integer(getattr(self, name), path=f"gates.{name}", minimum=1),
            )
        for name in tuple(self.__dataclass_fields__)[4:]:
            object.__setattr__(
                self,
                name,
                require_finite_number(getattr(self, name), path=f"gates.{name}"),
            )
        if (
            not 0.0 <= self.minimum_positive_comparable_fold_fraction <= 1.0
            or self.to_payload() != APPROVED_GATES
        ):
            raise ContractValidationError(
                "adequacy gates are not the approved immutable V2.2 payload"
            )

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ArtifactProtocol:
    output_root: str
    stage: str
    members: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "output_root", _path(self.output_root, path="artifact.output_root")
        )
        object.__setattr__(self, "stage", _string(self.stage, path="artifact.stage"))
        if (
            type(self.members) is not tuple
            or self.stage != STAGE
            or self.members != ARTIFACT_MEMBERS
        ):
            raise ContractValidationError(
                "artifact protocol must use the exact V2.2 stage and members"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "output_root": self.output_root,
            "stage": self.stage,
            "members": list(self.members),
        }


@dataclass(frozen=True)
class SwingReversalAdequacyConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    source: FrozenSource
    atr: FrozenSection
    detector: CausalSwingReversalConfig
    outcome: FrozenSection
    folds: tuple[CohortFold, ...]
    controls_per_real_candidate: int
    control_side_order: tuple[ZoneSide, ...]
    gates: AdequacyGates
    dispositions: tuple[str, ...]
    artifact: ArtifactProtocol
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION or (
            self.trial_name,
            self.venue,
            self.asset,
            self.timeframe,
        ) != (TRIAL_NAME, VENUE, ASSET, TIMEFRAME):
            raise ContractValidationError(
                "trial scope is outside the approved V2.2 TAOUSDT/1d study"
            )
        if (
            type(self.source) is not FrozenSource
            or type(self.atr) is not FrozenSection
            or type(self.detector) is not CausalSwingReversalConfig
            or type(self.outcome) is not FrozenSection
            or type(self.gates) is not AdequacyGates
            or type(self.artifact) is not ArtifactProtocol
        ):
            raise ContractValidationError(
                "V2.2 configuration sections have invalid types"
            )
        if (
            self.atr.name != "atr"
            or self.atr.expected != ATR_PAYLOAD
            or self.outcome.name != "outcome"
            or self.outcome.expected != OUTCOME_PAYLOAD
            or self.detector.to_payload() != APPROVED_DETECTOR
        ):
            raise ContractValidationError("V2.2 configuration protocol is not approved")
        if (
            type(self.folds) is not tuple
            or tuple((f.name, f.start, f.end) for f in self.folds) != FOLD_BOUNDS
            or self.controls_per_real_candidate != 2
            or self.control_side_order != CONTROL_SIDE_ORDER
            or self.dispositions != DISPOSITIONS
        ):
            raise ContractValidationError(
                "V2.2 folds, controls, or dispositions are not frozen"
            )
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "trial": {
                "trial_name": self.trial_name,
                "venue": self.venue,
                "asset": self.asset,
                "timeframe": self.timeframe,
            },
            "source": self.source.to_payload(),
            "atr": self.atr.to_payload(),
            "detector": self.detector.to_payload(),
            "outcome": self.outcome.to_payload(),
            "folds": [f.to_payload() for f in self.folds],
            "controls": {
                "per_real_candidate": self.controls_per_real_candidate,
                "side_order": [s.value for s in self.control_side_order],
            },
            "gates": self.gates.to_payload(),
            "dispositions": list(self.dispositions),
            "artifact": self.artifact.to_payload(),
        }


def load_swing_reversal_adequacy_config(path: str) -> SwingReversalAdequacyConfig:
    raw = _mapping(
        load_strict_research_yaml(
            path, description="V2.2 swing-reversal configuration"
        ),
        path="config",
    )
    require_exact_keys(
        raw,
        {
            "version",
            "trial",
            "source",
            "atr",
            "detector",
            "outcome",
            "folds",
            "controls",
            "gates",
            "dispositions",
            "artifact",
        },
        path="config",
    )
    trial, source, atr, detector, outcome, controls, gates, artifact = (
        _mapping(raw[name], path=name)
        for name in (
            "trial",
            "source",
            "atr",
            "detector",
            "outcome",
            "controls",
            "gates",
            "artifact",
        )
    )
    require_exact_keys(
        trial, {"trial_name", "venue", "asset", "timeframe"}, path="trial"
    )
    require_exact_keys(
        source,
        {
            "bundle_path",
            "bundle_id",
            "implementation_commit",
            "source_id",
            "source_bundle_id",
            "bars_sha256",
            "grid_sha256",
            "row_count",
            "start",
            "end",
            "grid_policy",
        },
        path="source",
    )
    require_exact_keys(atr, set(ATR_PAYLOAD), path="atr")
    require_exact_keys(detector, set(APPROVED_DETECTOR), path="detector")
    require_exact_keys(outcome, set(OUTCOME_PAYLOAD), path="outcome")
    require_exact_keys(controls, {"per_real_candidate", "side_order"}, path="controls")
    require_exact_keys(gates, set(APPROVED_GATES), path="gates")
    require_exact_keys(artifact, {"output_root", "stage", "members"}, path="artifact")
    if (
        type(raw["folds"]) is not list
        or type(controls["side_order"]) is not list
        or type(raw["dispositions"]) is not list
        or type(artifact["members"]) is not list
    ):
        raise ContractValidationError("V2.2 list protocol is invalid")
    folds = tuple(
        CohortFold(
            name=_string(item.get("name"), path=f"folds[{index}].name"),
            start=_timestamp(item.get("start"), path=f"folds[{index}].start"),
            end=_timestamp(item.get("end"), path=f"folds[{index}].end"),
        )
        for index, item in enumerate(raw["folds"])
        if type(item) is dict
        and require_exact_keys(item, {"name", "start", "end"}, path=f"folds[{index}]")
        is None
    )
    if len(folds) != len(raw["folds"]):
        raise ContractValidationError("folds must be mappings")
    try:
        sides = tuple(ZoneSide(item) for item in controls["side_order"])
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            "controls.side_order contains an invalid zone side"
        ) from exc
    return SwingReversalAdequacyConfig(
        version=_string(raw["version"], path="version"),
        trial_name=_string(trial["trial_name"], path="trial.trial_name"),
        venue=_string(trial["venue"], path="trial.venue"),
        asset=_string(trial["asset"], path="trial.asset"),
        timeframe=_string(trial["timeframe"], path="trial.timeframe"),
        source=FrozenSource(
            bundle_path=_path(source["bundle_path"], path="source.bundle_path"),
            bundle_id=require_sha256(source["bundle_id"], path="source.bundle_id"),
            implementation_commit=require_git_commit(
                source["implementation_commit"], path="source.implementation_commit"
            ),
            source_id=require_sha256(source["source_id"], path="source.source_id"),
            source_bundle_id=require_sha256(
                source["source_bundle_id"], path="source.source_bundle_id"
            ),
            bars_sha256=require_sha256(
                source["bars_sha256"], path="source.bars_sha256"
            ),
            grid_sha256=require_sha256(
                source["grid_sha256"], path="source.grid_sha256"
            ),
            row_count=require_integer(
                source["row_count"], path="source.row_count", minimum=1
            ),
            start=_timestamp(source["start"], path="source.start"),
            end=_timestamp(source["end"], path="source.end"),
            grid_policy=_string(source["grid_policy"], path="source.grid_policy"),
        ),
        atr=FrozenSection("atr", dict(atr), ATR_PAYLOAD),
        detector=CausalSwingReversalConfig(
            require_finite_number(
                detector["reversal_atr"], path="detector.reversal_atr"
            )
        ),
        outcome=FrozenSection("outcome", dict(outcome), OUTCOME_PAYLOAD),
        folds=folds,
        controls_per_real_candidate=require_integer(
            controls["per_real_candidate"],
            path="controls.per_real_candidate",
            minimum=1,
        ),
        control_side_order=sides,
        gates=AdequacyGates(**{name: gates[name] for name in APPROVED_GATES}),
        dispositions=tuple(
            _string(value, path=f"dispositions[{i}]")
            for i, value in enumerate(raw["dispositions"])
        ),
        artifact=ArtifactProtocol(
            _path(artifact["output_root"], path="artifact.output_root"),
            _string(artifact["stage"], path="artifact.stage"),
            tuple(
                _string(value, path=f"artifact.members[{i}]")
                for i, value in enumerate(artifact["members"])
            ),
        ),
    )


__all__ = [
    "AdequacyGates",
    "ArtifactProtocol",
    "FrozenSource",
    "SwingReversalAdequacyConfig",
    "load_swing_reversal_adequacy_config",
]
