"""Pure-Python confirmed-extrema pair reference provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations

from ..configuration.provider import (
    ConfirmedExtremaPairConfig,
    PROVIDER_NAME,
    PROVIDER_VERSION,
)
from ..domain.candidates import AnchorRef, CandidateEvidence, LineCandidate
from ..domain.enums import LineRole
from ..domain.geometry import LineGeometry
from ..domain.identity import deterministic_hash
from ..domain.validation import ContractValidationError
from .contracts import (
    ProviderDiagnostics,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from .provider_evidence import ConfirmedExtremaPairEvidence, ExtremaKind


_UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class _ConfirmedExtremum:
    kind: ExtremaKind
    source_position: int
    confirmation_position: int
    timestamp: datetime
    confirmation_time: datetime
    price: float


def _datetime_from_ns(timestamp_ns: int) -> datetime:
    seconds, remainder_ns = divmod(timestamp_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=_UTC) + timedelta(
        microseconds=remainder_ns // 1_000
    )


def _confirmed_through_ns(request: ProviderRequest) -> int:
    value = request.confirmed_through
    epoch = datetime(1970, 1, 1, tzinfo=_UTC)
    elapsed = value - epoch
    return (
        (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000
        + elapsed.microseconds * 1_000
    )


def _anchor_id(request: ProviderRequest, extremum: _ConfirmedExtremum) -> str:
    return deterministic_hash(
        "trendline_v2_confirmed_extrema_anchor",
        {
            "asset": request.asset,
            "timeframe": request.timeframe,
            "extrema_kind": extremum.kind.value,
            "source_timestamp": extremum.timestamp,
            "confirmation_timestamp": extremum.confirmation_time,
            "source_price": extremum.price,
            "provider_name": PROVIDER_NAME,
            "provider_version": PROVIDER_VERSION,
        },
    )


class ConfirmedExtremaPairProvider:
    """Small deterministic baseline for causal extrema-pair line discovery."""

    provider_name = PROVIDER_NAME
    provider_version = PROVIDER_VERSION

    def generate(self, request: ProviderRequest) -> ProviderResult:
        if not isinstance(request, ProviderRequest):
            raise ContractValidationError("confirmed extrema provider requires ProviderRequest")
        if not isinstance(request.provider_config, ConfirmedExtremaPairConfig):
            return self._abstain(
                request,
                ProviderReason.CONFIGURATION_ERROR,
                "confirmed_extrema_pair requires ConfirmedExtremaPairConfig",
            )
        try:
            return self._generate(request)
        except ContractValidationError as exc:
            return self._abstain(request, ProviderReason.INVALID_INPUT, str(exc))
        except Exception as exc:  # Unexpected provider defects remain explicit failures.
            return self._failed(request, ProviderReason.PROVIDER_FAILURE, type(exc).__name__)

    def _generate(self, request: ProviderRequest) -> ProviderResult:
        config = request.provider_config
        positions = self._history_positions(request, config)
        required_rows = config.left_confirmation_bars + config.right_confirmation_bars + 1
        if len(positions) < required_rows:
            return self._abstain(request, ProviderReason.INSUFFICIENT_INPUT)

        lows = self._confirmed_extrema(
            request,
            positions,
            kind=ExtremaKind.LOW,
            left=config.left_confirmation_bars,
            right=config.right_confirmation_bars,
        )
        highs = self._confirmed_extrema(
            request,
            positions,
            kind=ExtremaKind.HIGH,
            left=config.left_confirmation_bars,
            right=config.right_confirmation_bars,
        )
        role_extrema = (
            (LineRole.SUPPORT, lows),
            (LineRole.RESISTANCE, highs),
        )
        eligible = tuple(
            (role, extrema)
            for role, extrema in role_extrema
            if len(extrema) >= config.min_extrema_per_role
        )
        if not eligible:
            return self._abstain(request, ProviderReason.INSUFFICIENT_INPUT)

        hypothesis_count = sum(
            len(extrema) * (len(extrema) - 1) // 2 for _, extrema in eligible
        )
        if hypothesis_count > config.max_hypotheses:
            return self._abstain(request, ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED)

        records: dict[str, tuple[LineCandidate, ConfirmedExtremaPairEvidence]] = {}
        for role, extrema in eligible:
            for first, second in combinations(extrema, 2):
                record = self._candidate_record(request, role, first, second)
                if record is not None:
                    records.setdefault(record[0].candidate_id, record)
        if not records:
            return self._abstain(request, ProviderReason.NO_CANDIDATES)

        ordered = tuple(sorted(records.values(), key=self._record_key))
        if len(ordered) > config.max_output_candidates:
            return self._abstain(request, ProviderReason.OUTPUT_LIMIT_EXCEEDED)
        return ProviderResult(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            request=request,
            status=ProviderStatus.SUCCESS,
            candidates=tuple(candidate for candidate, _ in ordered),
            evidence=tuple(evidence for _, evidence in ordered),
            diagnostics=ProviderDiagnostics(
                candidate_count=len(ordered), input_row_count=request.input_data.row_count
            ),
        )

    @staticmethod
    def _history_positions(
        request: ProviderRequest, config: ConfirmedExtremaPairConfig
    ) -> tuple[int, ...]:
        confirmed_ns = _confirmed_through_ns(request)
        duration_ns = int(config.lookback_duration_seconds * 1_000_000_000)
        window_start_ns = confirmed_ns - duration_ns
        return tuple(
            position
            for position, timestamp in enumerate(request.input_data.timestamps)
            if window_start_ns <= timestamp <= confirmed_ns
        )

    @staticmethod
    def _confirmed_extrema(
        request: ProviderRequest,
        positions: tuple[int, ...],
        *,
        kind: ExtremaKind,
        left: int,
        right: int,
    ) -> tuple[_ConfirmedExtremum, ...]:
        values = request.input_data.high if kind is ExtremaKind.HIGH else request.input_data.low
        extrema: list[_ConfirmedExtremum] = []
        for relative_position in range(left, len(positions) - right):
            source_position = positions[relative_position]
            value = values[source_position]
            left_values = (
                values[positions[index]] for index in range(relative_position - left, relative_position)
            )
            right_values = (
                values[positions[index]]
                for index in range(relative_position + 1, relative_position + right + 1)
            )
            if kind is ExtremaKind.HIGH:
                valid = all(value > neighbor for neighbor in left_values) and all(
                    value >= neighbor for neighbor in right_values
                )
            else:
                valid = all(value < neighbor for neighbor in left_values) and all(
                    value <= neighbor for neighbor in right_values
                )
            if not valid:
                continue
            confirmation_position = positions[relative_position + right]
            extrema.append(
                _ConfirmedExtremum(
                    kind=kind,
                    source_position=source_position,
                    confirmation_position=confirmation_position,
                    timestamp=_datetime_from_ns(request.input_data.timestamps[source_position]),
                    confirmation_time=_datetime_from_ns(
                        request.input_data.timestamps[confirmation_position]
                    ),
                    price=value,
                )
            )
        return tuple(extrema)

    def _candidate_record(
        self,
        request: ProviderRequest,
        role: LineRole,
        first: _ConfirmedExtremum,
        second: _ConfirmedExtremum,
    ) -> tuple[LineCandidate, ConfirmedExtremaPairEvidence] | None:
        geometry = LineGeometry(
            start_time=first.timestamp,
            end_time=second.timestamp,
            start_price=first.price,
            end_price=second.price,
        )
        intermediate_count = second.source_position - first.source_position - 1
        for position in range(first.source_position + 1, second.source_position):
            timestamp = _datetime_from_ns(request.input_data.timestamps[position])
            line_value = geometry.value_at(timestamp)
            body_floor = min(request.input_data.open[position], request.input_data.close[position])
            body_ceiling = max(request.input_data.open[position], request.input_data.close[position])
            if (role is LineRole.SUPPORT and line_value > body_floor) or (
                role is LineRole.RESISTANCE and line_value < body_ceiling
            ):
                return None

        anchors = (
            AnchorRef(
                anchor_id=_anchor_id(request, first),
                pivot_time=first.timestamp,
                confirmation_time=first.confirmation_time,
                price=first.price,
            ),
            AnchorRef(
                anchor_id=_anchor_id(request, second),
                pivot_time=second.timestamp,
                confirmation_time=second.confirmation_time,
                price=second.price,
            ),
        )
        candidate = LineCandidate.create(
            asset=request.asset,
            timeframe=request.timeframe,
            role=role,
            geometry=geometry,
            anchors=anchors,
            evidence=CandidateEvidence(
                anchor_count=2,
                distinct_anchor_timestamps=2,
                anchor_span_seconds=(second.timestamp - first.timestamp).total_seconds(),
            ),
            observed_at=request.observed_at,
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
        )
        return candidate, ConfirmedExtremaPairEvidence(
            candidate_id=candidate.candidate_id,
            extrema_kind=first.kind,
            anchor_source_positions=(first.source_position, second.source_position),
            confirmation_positions=(
                first.confirmation_position,
                second.confirmation_position,
            ),
            validated_intermediate_count=intermediate_count,
            body_violation_count=0,
        )

    @staticmethod
    def _record_key(
        record: tuple[LineCandidate, ConfirmedExtremaPairEvidence]
    ) -> tuple:
        candidate, _ = record
        first, second = candidate.anchors
        return (
            candidate.role.value,
            first.pivot_time,
            second.pivot_time,
            first.anchor_id,
            second.anchor_id,
            candidate.candidate_id,
        )

    @staticmethod
    def _abstain(
        request: ProviderRequest, reason: ProviderReason, detail: str | None = None
    ) -> ProviderResult:
        return ProviderResult(
            provider_name=request.provider_config.provider_name,
            provider_version=request.provider_config.provider_version,
            request=request,
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            evidence=(),
            diagnostics=ProviderDiagnostics(
                candidate_count=0, input_row_count=request.input_data.row_count
            ),
            reason=reason,
            detail=detail,
        )

    @staticmethod
    def _failed(
        request: ProviderRequest, reason: ProviderReason, detail: str
    ) -> ProviderResult:
        return ProviderResult(
            provider_name=request.provider_config.provider_name,
            provider_version=request.provider_config.provider_version,
            request=request,
            status=ProviderStatus.FAILED,
            candidates=(),
            evidence=(),
            diagnostics=ProviderDiagnostics(
                candidate_count=0, input_row_count=request.input_data.row_count
            ),
            reason=reason,
            detail=detail,
        )


__all__ = ["ConfirmedExtremaPairProvider"]
