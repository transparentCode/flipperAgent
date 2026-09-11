"""Immutable discovery snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .candidates import LineCandidate
from .enums import AbstentionReason, DiscoveryStatus
from .identity import (
    deterministic_hash,
    provider_identity as canonical_provider_identity,
    require_hash,
)
from .validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_string,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    asset: str
    timeframe: str
    observed_at: datetime
    input_identity: str
    config_identity: str
    provider_identity: str
    status: DiscoveryStatus | str
    candidates: tuple[LineCandidate, ...]
    reason: AbstentionReason | str | None = None

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="snapshot.asset")
        timeframe = require_string(self.timeframe, field_name="snapshot.timeframe")
        observed = require_utc(self.observed_at, field_name="snapshot.observed_at")
        input_identity = require_hash(self.input_identity, field_name="snapshot.input_identity")
        config_identity = require_hash(self.config_identity, field_name="snapshot.config_identity")
        provider_identity_value = require_hash(
            self.provider_identity, field_name="snapshot.provider_identity"
        )
        try:
            status = DiscoveryStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid discovery status: {self.status!r}") from exc
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, LineCandidate) for candidate in candidates):
            raise ContractValidationError("snapshot candidates must be LineCandidate values")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ContractValidationError("snapshot candidate IDs must be unique")
        ordered = tuple(sorted(candidates, key=lambda item: (item.role.value, item.candidate_id)))
        if ordered != candidates:
            raise ContractValidationError("snapshot candidates must use canonical ordering")
        reason = None
        if self.reason is not None:
            try:
                reason = AbstentionReason(self.reason)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError(f"invalid snapshot reason: {self.reason!r}") from exc
        if status is DiscoveryStatus.VALID and (not candidates or reason is not None):
            raise ContractValidationError("valid snapshot requires candidates and no reason")
        if status is not DiscoveryStatus.VALID and (candidates or reason is None):
            raise ContractValidationError("abstained/failed snapshot requires reason and no candidates")
        if any(candidate.observed_at != observed for candidate in candidates):
            raise ContractValidationError("candidate observation boundary mismatch")
        if any(
            candidate.asset != asset or candidate.timeframe != timeframe
            for candidate in candidates
        ):
            raise ContractValidationError("candidate market identity mismatch")
        if any(
            canonical_provider_identity(candidate.provider_name, candidate.provider_version)
            != provider_identity_value
            for candidate in candidates
        ):
            raise ContractValidationError("candidate provider identity mismatch")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "input_identity", input_identity)
        object.__setattr__(self, "config_identity", config_identity)
        object.__setattr__(self, "provider_identity", provider_identity_value)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason", reason)

    @property
    def snapshot_id(self) -> str:
        return deterministic_hash("trendline_v2_snapshot", self._identity_payload())

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at,
            "input_identity": self.input_identity,
            "config_identity": self.config_identity,
            "provider_identity": self.provider_identity,
            "status": self.status.value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "reason": self.reason.value if self.reason is not None else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoverySnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("snapshot payload must be a mapping")
        if set(value) != {
            "snapshot_id",
            "asset",
            "timeframe",
            "observed_at",
            "input_identity",
            "config_identity",
            "provider_identity",
            "status",
            "candidates",
            "reason",
        }:
            raise ContractValidationError("snapshot payload keys mismatch")
        try:
            result = cls(
                asset=value["asset"],
                timeframe=value["timeframe"],
                observed_at=parse_utc_isoformat(value["observed_at"], field_name="snapshot.observed_at"),
                input_identity=value["input_identity"],
                config_identity=value["config_identity"],
                provider_identity=value["provider_identity"],
                status=value["status"],
                candidates=tuple(LineCandidate.from_dict(item) for item in value["candidates"]),
                reason=value.get("reason"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid snapshot payload") from exc
        if value.get("snapshot_id") != result.snapshot_id:
            raise ContractValidationError("snapshot_id does not match canonical content")
        return result


__all__ = ["DiscoverySnapshot"]
