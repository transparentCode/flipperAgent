"""Immutable exact-line interaction observation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from ..domain.enums import LineRole
from ..domain.identity import deterministic_hash, require_hash
from ..domain.validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_integer,
    require_number,
    require_string,
    require_utc,
)
from ..tracking import TrackingStatus, TrendlineTrackingSnapshot


POLICY_IDENTITY_NAMESPACE = "trendline_v2_interaction_observation_policy"
EXPECTED_OBSERVATION_POLICY_IDENTITY = (
    "17a4f5e27483722091881349d775fe17adc018829efc6645d26a223c474bcdb4"
)
BAR_IDENTITY_NAMESPACE = "trendline_v2_confirmed_interaction_bar"
OBSERVATION_IDENTITY_NAMESPACE = "trendline_v2_exact_line_bar_observation"
INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE = "trendline_v2_interaction_snapshot"


class CandleDirection(str, Enum):
    DOWN = "down"
    FLAT = "flat"
    UP = "up"


class LinePriceRelation(str, Enum):
    BELOW = "below"
    ON = "on"
    ABOVE = "above"


@dataclass(frozen=True, slots=True)
class ExactLineObservationPolicy:
    policy_name: str = "exact_line_bar_observation"
    policy_version: str = "v1"
    source_family_scope: str = "active_families_only"
    family_coverage: str = "exactly_one_observation_per_active_family"
    line_projection_time: str = "bar_timestamp"
    distance_definition: str = "price_minus_exact_line_price"
    wick_intersection_rule: str = "low <= exact_line_price <= high"
    body_intersection_rule: str = (
        "min(open, close) <= exact_line_price <= max(open, close)"
    )
    same_step_visibility_rule: str = (
        "bar_timestamp >= tracking_observed_at and "
        "bar_available_at > tracking_observed_at"
    )
    source_input_advancement_rule: str = (
        "bar_source_input_identity != tracking_input_identity"
    )
    ordering_rule: str = "family_id_ascending"
    threshold_policy: str = "none"

    def __post_init__(self) -> None:
        expected = {
            "policy_name": "exact_line_bar_observation",
            "policy_version": "v1",
            "source_family_scope": "active_families_only",
            "family_coverage": "exactly_one_observation_per_active_family",
            "line_projection_time": "bar_timestamp",
            "distance_definition": "price_minus_exact_line_price",
            "wick_intersection_rule": "low <= exact_line_price <= high",
            "body_intersection_rule": (
                "min(open, close) <= exact_line_price <= max(open, close)"
            ),
            "same_step_visibility_rule": (
                "bar_timestamp >= tracking_observed_at and "
                "bar_available_at > tracking_observed_at"
            ),
            "source_input_advancement_rule": (
                "bar_source_input_identity != tracking_input_identity"
            ),
            "ordering_rule": "family_id_ascending",
            "threshold_policy": "none",
        }
        for field_name, expected_value in expected.items():
            value = require_string(
                getattr(self, field_name), field_name=f"interaction_policy.{field_name}"
            )
            if value != expected_value:
                raise ContractValidationError(
                    f"interaction policy {field_name} is immutable"
                )
            object.__setattr__(self, field_name, value)
        if self.policy_identity != EXPECTED_OBSERVATION_POLICY_IDENTITY:
            raise ContractValidationError("interaction policy identity is not canonical")

    def to_dict(self) -> dict[str, str]:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "source_family_scope": self.source_family_scope,
            "family_coverage": self.family_coverage,
            "line_projection_time": self.line_projection_time,
            "distance_definition": self.distance_definition,
            "wick_intersection_rule": self.wick_intersection_rule,
            "body_intersection_rule": self.body_intersection_rule,
            "same_step_visibility_rule": self.same_step_visibility_rule,
            "source_input_advancement_rule": self.source_input_advancement_rule,
            "ordering_rule": self.ordering_rule,
            "threshold_policy": self.threshold_policy,
        }

    @property
    def policy_identity(self) -> str:
        return deterministic_hash(POLICY_IDENTITY_NAMESPACE, self.to_dict())

    @property
    def policy_id(self) -> str:
        return self.policy_identity

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactLineObservationPolicy":
        if not isinstance(value, Mapping):
            raise ContractValidationError("interaction policy payload must be a mapping")
        expected = set(cls().to_dict())
        if set(value) != expected:
            raise ContractValidationError("interaction policy payload keys mismatch")
        result = cls(**dict(value))
        if result.to_dict() != dict(value):
            raise ContractValidationError("interaction policy payload is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class ConfirmedInteractionBar:
    bar_id: str
    asset: str
    timeframe: str
    timestamp: datetime
    available_at: datetime
    source_input_identity: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        bar_id = require_hash(self.bar_id, field_name="interaction_bar.bar_id")
        asset = require_string(self.asset, field_name="interaction_bar.asset")
        timeframe = require_string(
            self.timeframe, field_name="interaction_bar.timeframe"
        )
        timestamp = require_utc(
            self.timestamp, field_name="interaction_bar.timestamp"
        )
        available_at = require_utc(
            self.available_at, field_name="interaction_bar.available_at"
        )
        if timestamp >= available_at:
            raise ContractValidationError(
                "interaction_bar.timestamp must precede available_at"
            )
        source_input_identity = require_hash(
            self.source_input_identity,
            field_name="interaction_bar.source_input_identity",
        )
        open_price = require_number(self.open, field_name="interaction_bar.open")
        high = require_number(self.high, field_name="interaction_bar.high")
        low = require_number(self.low, field_name="interaction_bar.low")
        close = require_number(self.close, field_name="interaction_bar.close")
        volume = require_number(
            self.volume, field_name="interaction_bar.volume", minimum=0.0
        )
        if high < low:
            raise ContractValidationError("interaction_bar.high must not be below low")
        if not low <= open_price <= high:
            raise ContractValidationError("interaction_bar.open must be within candle")
        if not low <= close <= high:
            raise ContractValidationError(
                "interaction_bar.close must be within candle"
            )
        object.__setattr__(self, "bar_id", bar_id)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "source_input_identity", source_input_identity)
        object.__setattr__(self, "open", open_price)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)
        if self.expected_bar_id != bar_id:
            raise ContractValidationError("bar_id does not match canonical content")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "available_at": self.available_at,
            "source_input_identity": self.source_input_identity,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @property
    def expected_bar_id(self) -> str:
        return deterministic_hash(BAR_IDENTITY_NAMESPACE, self._identity_payload())

    @classmethod
    def create(
        cls,
        *,
        asset: str,
        timeframe: str,
        timestamp: datetime,
        available_at: datetime,
        source_input_identity: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> "ConfirmedInteractionBar":
        values = {
            "asset": require_string(asset, field_name="interaction_bar.asset"),
            "timeframe": require_string(
                timeframe, field_name="interaction_bar.timeframe"
            ),
            "timestamp": require_utc(
                timestamp, field_name="interaction_bar.timestamp"
            ),
            "available_at": require_utc(
                available_at, field_name="interaction_bar.available_at"
            ),
            "source_input_identity": require_hash(
                source_input_identity,
                field_name="interaction_bar.source_input_identity",
            ),
            "open": require_number(open, field_name="interaction_bar.open"),
            "high": require_number(high, field_name="interaction_bar.high"),
            "low": require_number(low, field_name="interaction_bar.low"),
            "close": require_number(close, field_name="interaction_bar.close"),
            "volume": require_number(
                volume, field_name="interaction_bar.volume", minimum=0.0
            ),
        }
        provisional = cls(
            bar_id=deterministic_hash(BAR_IDENTITY_NAMESPACE, values),
            **values,
        )
        return provisional

    def to_dict(self) -> dict[str, Any]:
        return {"bar_id": self.bar_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfirmedInteractionBar":
        if not isinstance(value, Mapping):
            raise ContractValidationError("interaction bar payload must be a mapping")
        expected = {
            "bar_id",
            "asset",
            "timeframe",
            "timestamp",
            "available_at",
            "source_input_identity",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
        if set(value) != expected:
            raise ContractValidationError("interaction bar payload keys mismatch")
        try:
            return cls(
                bar_id=value["bar_id"],
                asset=value["asset"],
                timeframe=value["timeframe"],
                timestamp=parse_utc_isoformat(
                    value["timestamp"], field_name="interaction_bar.timestamp"
                ),
                available_at=parse_utc_isoformat(
                    value["available_at"], field_name="interaction_bar.available_at"
                ),
                source_input_identity=value["source_input_identity"],
                open=value["open"],
                high=value["high"],
                low=value["low"],
                close=value["close"],
                volume=value["volume"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid interaction bar payload") from exc


def _line_differences(
    bar: ConfirmedInteractionBar, line: float
) -> tuple[float, float, float, float]:
    return (
        bar.open - line,
        bar.high - line,
        bar.low - line,
        bar.close - line,
    )


def _wick_intersects(open_minus_line: float, high_minus_line: float, low_minus_line: float, close_minus_line: float) -> bool:
    del open_minus_line, close_minus_line
    return low_minus_line <= 0.0 <= high_minus_line


def _body_intersects(open_minus_line: float, high_minus_line: float, low_minus_line: float, close_minus_line: float) -> bool:
    del high_minus_line, low_minus_line
    return min(open_minus_line, close_minus_line) <= 0.0 <= max(
        open_minus_line, close_minus_line
    )


def _close_relation(close_minus_line: float) -> LinePriceRelation:
    if close_minus_line > 0.0:
        return LinePriceRelation.ABOVE
    if close_minus_line < 0.0:
        return LinePriceRelation.BELOW
    return LinePriceRelation.ON


def _candle_direction(open_minus_line: float, close_minus_line: float) -> CandleDirection:
    if close_minus_line > open_minus_line:
        return CandleDirection.UP
    if close_minus_line < open_minus_line:
        return CandleDirection.DOWN
    return CandleDirection.FLAT


@dataclass(frozen=True, slots=True)
class ExactLineBarObservation:
    observation_id: str
    family_id: str
    family_version: int
    role: LineRole | str
    source_tracking_snapshot_id: str
    source_selection_snapshot_id: str
    source_candidate_id: str
    geometry_id: str
    bar_id: str
    bar_timestamp: datetime
    bar_available_at: datetime
    exact_line_price: float
    open_minus_line: float
    high_minus_line: float
    low_minus_line: float
    close_minus_line: float
    absolute_close_distance: float
    wick_intersects_line: bool
    body_intersects_line: bool
    close_relation: LinePriceRelation | str
    candle_direction: CandleDirection | str

    def __post_init__(self) -> None:
        observation_id = require_hash(
            self.observation_id, field_name="observation.observation_id"
        )
        family_id = require_hash(self.family_id, field_name="observation.family_id")
        family_version = require_integer(
            self.family_version, field_name="observation.family_version", minimum=1
        )
        try:
            role = LineRole(self.role)
            close_relation = LinePriceRelation(self.close_relation)
            candle_direction = CandleDirection(self.candle_direction)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid exact-line observation enum") from exc
        source_tracking_snapshot_id = require_hash(
            self.source_tracking_snapshot_id,
            field_name="observation.source_tracking_snapshot_id",
        )
        source_selection_snapshot_id = require_hash(
            self.source_selection_snapshot_id,
            field_name="observation.source_selection_snapshot_id",
        )
        source_candidate_id = require_hash(
            self.source_candidate_id,
            field_name="observation.source_candidate_id",
        )
        geometry_id = require_hash(self.geometry_id, field_name="observation.geometry_id")
        bar_id = require_hash(self.bar_id, field_name="observation.bar_id")
        bar_timestamp = require_utc(
            self.bar_timestamp, field_name="observation.bar_timestamp"
        )
        bar_available_at = require_utc(
            self.bar_available_at, field_name="observation.bar_available_at"
        )
        if bar_timestamp >= bar_available_at:
            raise ContractValidationError(
                "observation.bar_timestamp must precede bar_available_at"
            )
        exact_line_price = require_number(
            self.exact_line_price, field_name="observation.exact_line_price"
        )
        differences = tuple(
            require_number(
                value,
                field_name=f"observation.{field_name}",
            )
            for field_name, value in (
                ("open_minus_line", self.open_minus_line),
                ("high_minus_line", self.high_minus_line),
                ("low_minus_line", self.low_minus_line),
                ("close_minus_line", self.close_minus_line),
            )
        )
        absolute_close_distance = require_number(
            self.absolute_close_distance,
            field_name="observation.absolute_close_distance",
            minimum=0.0,
        )
        if absolute_close_distance != abs(differences[3]):
            raise ContractValidationError("observation close distance formula mismatch")
        expected_wick = _wick_intersects(*differences)
        expected_body = _body_intersects(*differences)
        if self.wick_intersects_line is not expected_wick:
            raise ContractValidationError("observation wick intersection mismatch")
        if self.body_intersects_line is not expected_body:
            raise ContractValidationError("observation body intersection mismatch")
        if close_relation is not _close_relation(differences[3]):
            raise ContractValidationError("observation close relation mismatch")
        if candle_direction is not _candle_direction(differences[0], differences[3]):
            raise ContractValidationError("observation candle direction mismatch")
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "family_version", family_version)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "source_tracking_snapshot_id", source_tracking_snapshot_id)
        object.__setattr__(self, "source_selection_snapshot_id", source_selection_snapshot_id)
        object.__setattr__(self, "source_candidate_id", source_candidate_id)
        object.__setattr__(self, "geometry_id", geometry_id)
        object.__setattr__(self, "bar_id", bar_id)
        object.__setattr__(self, "bar_timestamp", bar_timestamp)
        object.__setattr__(self, "bar_available_at", bar_available_at)
        object.__setattr__(self, "exact_line_price", exact_line_price)
        object.__setattr__(self, "open_minus_line", differences[0])
        object.__setattr__(self, "high_minus_line", differences[1])
        object.__setattr__(self, "low_minus_line", differences[2])
        object.__setattr__(self, "close_minus_line", differences[3])
        object.__setattr__(self, "absolute_close_distance", absolute_close_distance)
        object.__setattr__(self, "close_relation", close_relation)
        object.__setattr__(self, "candle_direction", candle_direction)
        if self.expected_observation_id != observation_id:
            raise ContractValidationError(
                "observation_id does not match canonical content"
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "family_version": self.family_version,
            "role": self.role.value,
            "source_tracking_snapshot_id": self.source_tracking_snapshot_id,
            "source_selection_snapshot_id": self.source_selection_snapshot_id,
            "source_candidate_id": self.source_candidate_id,
            "geometry_id": self.geometry_id,
            "bar_id": self.bar_id,
            "bar_timestamp": self.bar_timestamp,
            "bar_available_at": self.bar_available_at,
            "exact_line_price": self.exact_line_price,
            "open_minus_line": self.open_minus_line,
            "high_minus_line": self.high_minus_line,
            "low_minus_line": self.low_minus_line,
            "close_minus_line": self.close_minus_line,
            "absolute_close_distance": self.absolute_close_distance,
            "wick_intersects_line": self.wick_intersects_line,
            "body_intersects_line": self.body_intersects_line,
            "close_relation": self.close_relation.value,
            "candle_direction": self.candle_direction.value,
        }

    @property
    def expected_observation_id(self) -> str:
        return deterministic_hash(
            OBSERVATION_IDENTITY_NAMESPACE, self._identity_payload()
        )

    @classmethod
    def create(
        cls,
        *,
        family_id: str,
        family_version: int,
        role: LineRole | str,
        source_tracking_snapshot_id: str,
        source_selection_snapshot_id: str,
        source_candidate_id: str,
        geometry_id: str,
        bar: ConfirmedInteractionBar,
        exact_line_price: float,
    ) -> "ExactLineBarObservation":
        if not isinstance(bar, ConfirmedInteractionBar):
            raise ContractValidationError("observation.bar must be ConfirmedInteractionBar")
        line = require_number(
            exact_line_price, field_name="observation.exact_line_price"
        )
        differences = _line_differences(bar, line)
        try:
            role_value = LineRole(role).value
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid exact-line observation role") from exc
        payload = {
            "family_id": require_hash(family_id, field_name="observation.family_id"),
            "family_version": require_integer(
                family_version, field_name="observation.family_version", minimum=1
            ),
            "role": role_value,
            "source_tracking_snapshot_id": require_hash(
                source_tracking_snapshot_id,
                field_name="observation.source_tracking_snapshot_id",
            ),
            "source_selection_snapshot_id": require_hash(
                source_selection_snapshot_id,
                field_name="observation.source_selection_snapshot_id",
            ),
            "source_candidate_id": require_hash(
                source_candidate_id, field_name="observation.source_candidate_id"
            ),
            "geometry_id": require_hash(geometry_id, field_name="observation.geometry_id"),
            "bar_id": bar.bar_id,
            "bar_timestamp": bar.timestamp,
            "bar_available_at": bar.available_at,
            "exact_line_price": line,
            "open_minus_line": differences[0],
            "high_minus_line": differences[1],
            "low_minus_line": differences[2],
            "close_minus_line": differences[3],
            "absolute_close_distance": abs(differences[3]),
            "wick_intersects_line": _wick_intersects(*differences),
            "body_intersects_line": _body_intersects(*differences),
            "close_relation": _close_relation(differences[3]).value,
            "candle_direction": _candle_direction(differences[0], differences[3]).value,
        }
        return cls(
            observation_id=deterministic_hash(
                OBSERVATION_IDENTITY_NAMESPACE, payload
            ),
            **payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactLineBarObservation":
        if not isinstance(value, Mapping):
            raise ContractValidationError("observation payload must be a mapping")
        expected = {
            "observation_id",
            "family_id",
            "family_version",
            "role",
            "source_tracking_snapshot_id",
            "source_selection_snapshot_id",
            "source_candidate_id",
            "geometry_id",
            "bar_id",
            "bar_timestamp",
            "bar_available_at",
            "exact_line_price",
            "open_minus_line",
            "high_minus_line",
            "low_minus_line",
            "close_minus_line",
            "absolute_close_distance",
            "wick_intersects_line",
            "body_intersects_line",
            "close_relation",
            "candle_direction",
        }
        if set(value) != expected:
            raise ContractValidationError("observation payload keys mismatch")
        try:
            return cls(
                observation_id=value["observation_id"],
                family_id=value["family_id"],
                family_version=value["family_version"],
                role=value["role"],
                source_tracking_snapshot_id=value["source_tracking_snapshot_id"],
                source_selection_snapshot_id=value["source_selection_snapshot_id"],
                source_candidate_id=value["source_candidate_id"],
                geometry_id=value["geometry_id"],
                bar_id=value["bar_id"],
                bar_timestamp=parse_utc_isoformat(
                    value["bar_timestamp"], field_name="observation.bar_timestamp"
                ),
                bar_available_at=parse_utc_isoformat(
                    value["bar_available_at"], field_name="observation.bar_available_at"
                ),
                exact_line_price=value["exact_line_price"],
                open_minus_line=value["open_minus_line"],
                high_minus_line=value["high_minus_line"],
                low_minus_line=value["low_minus_line"],
                close_minus_line=value["close_minus_line"],
                absolute_close_distance=value["absolute_close_distance"],
                wick_intersects_line=value["wick_intersects_line"],
                body_intersects_line=value["body_intersects_line"],
                close_relation=value["close_relation"],
                candle_direction=value["candle_direction"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid observation payload") from exc


@dataclass(frozen=True, slots=True)
class InteractionObservationDiagnostics:
    source_active_family_count: int
    observation_count: int
    support_observation_count: int
    resistance_observation_count: int
    wick_intersection_count: int
    body_intersection_count: int

    def __post_init__(self) -> None:
        values = {}
        for field_name in (
            "source_active_family_count",
            "observation_count",
            "support_observation_count",
            "resistance_observation_count",
            "wick_intersection_count",
            "body_intersection_count",
        ):
            values[field_name] = require_integer(
                getattr(self, field_name),
                field_name=f"interaction.diagnostics.{field_name}",
            )
        if values["observation_count"] != values["source_active_family_count"]:
            raise ContractValidationError(
                "interaction observation count must equal source active family count"
            )
        if values["support_observation_count"] + values["resistance_observation_count"] != values["observation_count"]:
            raise ContractValidationError(
                "interaction role counts must equal observations"
            )
        if values["wick_intersection_count"] > values["observation_count"]:
            raise ContractValidationError("interaction wick count exceeds observations")
        if values["body_intersection_count"] > values["observation_count"]:
            raise ContractValidationError("interaction body count exceeds observations")
        for field_name, value in values.items():
            object.__setattr__(self, field_name, value)

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InteractionObservationDiagnostics":
        if not isinstance(value, Mapping):
            raise ContractValidationError("interaction diagnostics payload must be a mapping")
        expected = {
            "source_active_family_count",
            "observation_count",
            "support_observation_count",
            "resistance_observation_count",
            "wick_intersection_count",
            "body_intersection_count",
        }
        if set(value) != expected:
            raise ContractValidationError("interaction diagnostics payload keys mismatch")
        try:
            return cls(**dict(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid interaction diagnostics payload") from exc


@dataclass(frozen=True, slots=True)
class TrendlineInteractionSnapshot:
    snapshot_id: str
    asset: str
    timeframe: str
    observed_at: datetime
    source_tracking_snapshot_id: str
    source_tracking_observed_at: datetime
    tracking_input_identity: str
    bar_source_input_identity: str
    observation_policy_identity: str
    source_active_family_ids: tuple[str, ...]
    bar: ConfirmedInteractionBar
    observations: tuple[ExactLineBarObservation, ...]
    diagnostics: InteractionObservationDiagnostics

    def validate_source_tracking(
        self,
        tracking: TrendlineTrackingSnapshot,
    ) -> None:
        """Validate persisted evidence against its typed tracking source.

        Structural decoding validates payload shape and content identities only.
        Call this method before using a decoded snapshot as source evidence.
        """

        if not isinstance(tracking, TrendlineTrackingSnapshot):
            raise ContractValidationError(
                "interaction source tracking must be TrendlineTrackingSnapshot"
            )
        if tracking.status not in (
            TrackingStatus.UPDATED,
            TrackingStatus.SOURCE_UNAVAILABLE,
        ):
            raise ContractValidationError("interaction source tracking status is invalid")
        if (
            self.asset != tracking.asset
            or self.timeframe != tracking.timeframe
            or self.source_tracking_snapshot_id != tracking.snapshot_id
            or self.source_tracking_observed_at != tracking.observed_at
            or self.tracking_input_identity != tracking.input_identity
        ):
            raise ContractValidationError("interaction source tracking identity mismatch")
        expected_family_ids = tuple(
            family.family_id for family in tracking.active_families
        )
        if self.source_active_family_ids != expected_family_ids:
            raise ContractValidationError(
                "interaction source active families do not match tracking"
            )
        families = {family.family_id: family for family in tracking.active_families}
        for observation in self.observations:
            family = families.get(observation.family_id)
            if family is None:
                raise ContractValidationError(
                    "interaction observation family is not active in tracking"
                )
            if family.last_seen_at > tracking.observed_at:
                raise ContractValidationError(
                    "tracked family is newer than source tracking observation"
                )
            candidate = family.current_candidate
            if (
                candidate.asset != tracking.asset
                or candidate.timeframe != tracking.timeframe
            ):
                raise ContractValidationError(
                    "tracked family candidate market identity mismatch"
                )
            if self.bar.timestamp < candidate.geometry.end_time:
                raise ContractValidationError(
                    "interaction bar precedes tracked family geometry"
                )
            if (
                observation.family_version != family.version
                or observation.role is not candidate.role
                or observation.source_tracking_snapshot_id != tracking.snapshot_id
                or observation.source_selection_snapshot_id
                != family.current_selection_snapshot_id
                or observation.source_candidate_id != candidate.candidate_id
                or observation.geometry_id != candidate.geometry.geometry_id
            ):
                raise ContractValidationError(
                    "interaction observation family provenance mismatch"
                )
            expected_line = candidate.geometry.value_at(self.bar.timestamp)
            if observation.exact_line_price != expected_line:
                raise ContractValidationError(
                    "interaction exact line does not match tracked family geometry"
                )

    def __post_init__(self) -> None:
        snapshot_id = require_hash(
            self.snapshot_id, field_name="interaction_snapshot.snapshot_id"
        )
        asset = require_string(self.asset, field_name="interaction_snapshot.asset")
        timeframe = require_string(
            self.timeframe, field_name="interaction_snapshot.timeframe"
        )
        observed_at = require_utc(
            self.observed_at, field_name="interaction_snapshot.observed_at"
        )
        source_tracking_snapshot_id = require_hash(
            self.source_tracking_snapshot_id,
            field_name="interaction_snapshot.source_tracking_snapshot_id",
        )
        source_tracking_observed_at = require_utc(
            self.source_tracking_observed_at,
            field_name="interaction_snapshot.source_tracking_observed_at",
        )
        tracking_input_identity = require_hash(
            self.tracking_input_identity,
            field_name="interaction_snapshot.tracking_input_identity",
        )
        bar_source_input_identity = require_hash(
            self.bar_source_input_identity,
            field_name="interaction_snapshot.bar_source_input_identity",
        )
        observation_policy_identity = require_hash(
            self.observation_policy_identity,
            field_name="interaction_snapshot.observation_policy_identity",
        )
        if observation_policy_identity != EXPECTED_OBSERVATION_POLICY_IDENTITY:
            raise ContractValidationError("interaction policy identity mismatch")
        if not isinstance(self.source_active_family_ids, tuple):
            raise ContractValidationError("source active family IDs must be a tuple")
        if not isinstance(self.bar, ConfirmedInteractionBar):
            raise ContractValidationError("interaction snapshot bar type mismatch")
        if not isinstance(self.observations, tuple):
            raise ContractValidationError("interaction observations must be a tuple")
        if not isinstance(self.diagnostics, InteractionObservationDiagnostics):
            raise ContractValidationError("interaction diagnostics type mismatch")
        source_ids = tuple(
            require_hash(
                family_id,
                field_name="interaction_snapshot.source_active_family_id",
            )
            for family_id in self.source_active_family_ids
        )
        if len(set(source_ids)) != len(source_ids):
            raise ContractValidationError("source active family IDs must be unique")
        if source_ids != tuple(sorted(source_ids)):
            raise ContractValidationError(
                "source active family IDs must use canonical ordering"
            )
        observations = self.observations
        if any(not isinstance(item, ExactLineBarObservation) for item in observations):
            raise ContractValidationError("interaction observations must be observation values")
        observation_family_ids = tuple(item.family_id for item in observations)
        if len(set(observation_family_ids)) != len(observation_family_ids):
            raise ContractValidationError("interaction family observations must be unique")
        if observation_family_ids != tuple(sorted(observation_family_ids)):
            raise ContractValidationError("interaction observations must use family ordering")
        if len({item.observation_id for item in observations}) != len(observations):
            raise ContractValidationError("interaction observation IDs must be unique")
        if set(observation_family_ids) != set(source_ids):
            raise ContractValidationError(
                "interaction observations must cover exactly active families"
            )
        if observed_at != self.bar.available_at:
            raise ContractValidationError("interaction observed_at must equal bar availability")
        if self.bar.asset != asset or self.bar.timeframe != timeframe:
            raise ContractValidationError("interaction bar market identity mismatch")
        if self.bar.source_input_identity != bar_source_input_identity:
            raise ContractValidationError("interaction bar source identity mismatch")
        if self.bar.timestamp < source_tracking_observed_at:
            raise ContractValidationError("interaction bar precedes tracking observation")
        if self.bar.available_at <= source_tracking_observed_at:
            raise ContractValidationError("interaction bar is not available after tracking")
        if bar_source_input_identity == tracking_input_identity:
            raise ContractValidationError("interaction source input identity did not advance")
        for observation in observations:
            if (
                observation.source_tracking_snapshot_id != source_tracking_snapshot_id
                or observation.bar_id != self.bar.bar_id
                or observation.bar_timestamp != self.bar.timestamp
                or observation.bar_available_at != self.bar.available_at
            ):
                raise ContractValidationError("interaction observation ownership mismatch")
            differences = _line_differences(self.bar, observation.exact_line_price)
            if differences != (
                observation.open_minus_line,
                observation.high_minus_line,
                observation.low_minus_line,
                observation.close_minus_line,
            ):
                raise ContractValidationError("interaction persisted distance mismatch")
            if observation.wick_intersects_line != _wick_intersects(*differences):
                raise ContractValidationError("interaction persisted wick mismatch")
            if observation.body_intersects_line != _body_intersects(*differences):
                raise ContractValidationError("interaction persisted body mismatch")
        expected_diagnostics = InteractionObservationDiagnostics(
            source_active_family_count=len(source_ids),
            observation_count=len(observations),
            support_observation_count=sum(
                item.role is LineRole.SUPPORT for item in observations
            ),
            resistance_observation_count=sum(
                item.role is LineRole.RESISTANCE for item in observations
            ),
            wick_intersection_count=sum(
                item.wick_intersects_line for item in observations
            ),
            body_intersection_count=sum(
                item.body_intersects_line for item in observations
            ),
        )
        if self.diagnostics != expected_diagnostics:
            raise ContractValidationError("interaction diagnostics mismatch")
        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_tracking_snapshot_id", source_tracking_snapshot_id)
        object.__setattr__(self, "source_tracking_observed_at", source_tracking_observed_at)
        object.__setattr__(self, "tracking_input_identity", tracking_input_identity)
        object.__setattr__(self, "bar_source_input_identity", bar_source_input_identity)
        object.__setattr__(self, "observation_policy_identity", observation_policy_identity)
        object.__setattr__(self, "source_active_family_ids", source_ids)
        object.__setattr__(self, "observations", observations)
        if self.expected_snapshot_id != snapshot_id:
            raise ContractValidationError("snapshot_id does not match canonical content")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at,
            "source_tracking_snapshot_id": self.source_tracking_snapshot_id,
            "source_tracking_observed_at": self.source_tracking_observed_at,
            "tracking_input_identity": self.tracking_input_identity,
            "bar_source_input_identity": self.bar_source_input_identity,
            "observation_policy_identity": self.observation_policy_identity,
            "source_active_family_ids": list(self.source_active_family_ids),
            "bar": self.bar.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "diagnostics": self.diagnostics.to_dict(),
        }

    @property
    def expected_snapshot_id(self) -> str:
        return deterministic_hash(
            INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE, self._identity_payload()
        )

    @classmethod
    def create(
        cls,
        *,
        source_tracking: TrendlineTrackingSnapshot,
        observation_policy_identity: str,
        bar: ConfirmedInteractionBar,
        observations: tuple[ExactLineBarObservation, ...],
        diagnostics: InteractionObservationDiagnostics,
    ) -> "TrendlineInteractionSnapshot":
        if not isinstance(source_tracking, TrendlineTrackingSnapshot):
            raise ContractValidationError(
                "interaction snapshot source tracking type mismatch"
            )
        if not isinstance(observations, tuple):
            raise ContractValidationError(
                "interaction snapshot observations must be a tuple"
            )
        if not isinstance(bar, ConfirmedInteractionBar):
            raise ContractValidationError("interaction snapshot bar type mismatch")
        if not isinstance(diagnostics, InteractionObservationDiagnostics):
            raise ContractValidationError(
                "interaction snapshot diagnostics type mismatch"
            )
        if any(
            not isinstance(item, ExactLineBarObservation) for item in observations
        ):
            raise ContractValidationError(
                "interaction snapshot observations must be observation values"
            )
        observation_policy_identity = require_hash(
            observation_policy_identity,
            field_name="interaction_snapshot.observation_policy_identity",
        )
        asset = source_tracking.asset
        timeframe = source_tracking.timeframe
        observed_at = bar.available_at
        source_tracking_snapshot_id = source_tracking.snapshot_id
        source_tracking_observed_at = source_tracking.observed_at
        tracking_input_identity = source_tracking.input_identity
        bar_source_input_identity = bar.source_input_identity
        source_active_family_ids = tuple(
            family.family_id for family in source_tracking.active_families
        )
        payload = {
            "asset": asset,
            "timeframe": timeframe,
            "observed_at": observed_at,
            "source_tracking_snapshot_id": source_tracking_snapshot_id,
            "source_tracking_observed_at": source_tracking_observed_at,
            "tracking_input_identity": tracking_input_identity,
            "bar_source_input_identity": bar_source_input_identity,
            "observation_policy_identity": observation_policy_identity,
            "source_active_family_ids": list(
                require_hash(
                    family_id,
                    field_name="interaction_snapshot.source_active_family_id",
                )
                for family_id in source_active_family_ids
            ),
            "bar": bar.to_dict(),
            "observations": [item.to_dict() for item in observations],
            "diagnostics": diagnostics.to_dict(),
        }
        snapshot = cls(
            snapshot_id=deterministic_hash(
                INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE, payload
            ),
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            source_tracking_snapshot_id=source_tracking_snapshot_id,
            source_tracking_observed_at=source_tracking_observed_at,
            tracking_input_identity=tracking_input_identity,
            bar_source_input_identity=bar_source_input_identity,
            observation_policy_identity=observation_policy_identity,
            source_active_family_ids=tuple(
                require_hash(
                    family_id,
                    field_name="interaction_snapshot.source_active_family_id",
                )
                for family_id in source_active_family_ids
            ),
            bar=bar,
            observations=observations,
            diagnostics=diagnostics,
        )
        snapshot.validate_source_tracking(source_tracking)
        return snapshot

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineInteractionSnapshot":
        """Decode structure; call validate_source_tracking before use."""
        if not isinstance(value, Mapping):
            raise ContractValidationError("interaction snapshot payload must be a mapping")
        expected = {
            "snapshot_id",
            "asset",
            "timeframe",
            "observed_at",
            "source_tracking_snapshot_id",
            "source_tracking_observed_at",
            "tracking_input_identity",
            "bar_source_input_identity",
            "observation_policy_identity",
            "source_active_family_ids",
            "bar",
            "observations",
            "diagnostics",
        }
        if set(value) != expected:
            raise ContractValidationError("interaction snapshot payload keys mismatch")
        if not isinstance(value["source_active_family_ids"], list) or not isinstance(
            value["observations"], list
        ):
            raise ContractValidationError("interaction snapshot collections must be lists")
        try:
            return cls(
                snapshot_id=value["snapshot_id"],
                asset=value["asset"],
                timeframe=value["timeframe"],
                observed_at=parse_utc_isoformat(
                    value["observed_at"], field_name="interaction_snapshot.observed_at"
                ),
                source_tracking_snapshot_id=value["source_tracking_snapshot_id"],
                source_tracking_observed_at=parse_utc_isoformat(
                    value["source_tracking_observed_at"],
                    field_name="interaction_snapshot.source_tracking_observed_at",
                ),
                tracking_input_identity=value["tracking_input_identity"],
                bar_source_input_identity=value["bar_source_input_identity"],
                observation_policy_identity=value["observation_policy_identity"],
                source_active_family_ids=tuple(value["source_active_family_ids"]),
                bar=ConfirmedInteractionBar.from_dict(value["bar"]),
                observations=tuple(
                    ExactLineBarObservation.from_dict(item)
                    for item in value["observations"]
                ),
                diagnostics=InteractionObservationDiagnostics.from_dict(
                    value["diagnostics"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid interaction snapshot payload") from exc


__all__ = [
    "BAR_IDENTITY_NAMESPACE",
    "CandleDirection",
    "ConfirmedInteractionBar",
    "EXPECTED_OBSERVATION_POLICY_IDENTITY",
    "ExactLineBarObservation",
    "ExactLineObservationPolicy",
    "INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE",
    "InteractionObservationDiagnostics",
    "LinePriceRelation",
    "OBSERVATION_IDENTITY_NAMESPACE",
    "POLICY_IDENTITY_NAMESPACE",
    "TrendlineInteractionSnapshot",
]
