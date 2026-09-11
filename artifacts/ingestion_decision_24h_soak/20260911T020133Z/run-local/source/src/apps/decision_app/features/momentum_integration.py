"""Explicit, certification-locked Momentum integration for Decision.

This module is the small app-owned boundary between Decision configuration and
the already-approved Momentum plugin.  It owns route/profile validation and the
shared RSI/MACD definitions; the model plugin continues to receive only its
model-owned configuration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from apps.decision_app.domain.identity import sha256_fingerprint
from apps.decision_app.features.momentum import calculate_macd, calculate_rsi
from apps.decision_app.features.planning import (
    FeatureHistoryRequirement,
    SharedFeatureDefinition,
)
from libs.contracts.decision import CausalBarView
from libs.models.momentum.adapters.decision_plugin import (
    MOMENTUM_MODEL_SPEC,
    MomentumDecisionPlugin,
)
from libs.models.momentum.config import MomentumConfig

MOMENTUM_M3_ARTIFACT_SHA256 = (
    "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
)

MOMENTUM_RSI_FEATURE_NAME = "RSI"
MOMENTUM_MACD_FEATURE_NAME = "MACD"
MOMENTUM_FEATURE_VERSION = "1"

_MODEL_KEYS = frozenset(
    {
        "rsi_long_threshold",
        "rsi_short_threshold",
        "require_macd_positive",
        "histogram_min_abs",
    }
)
_RSI_KEYS = frozenset({"period", "history_bars"})
_MACD_KEYS = frozenset({"fast_period", "slow_period", "signal_period", "history_bars"})
_CERTIFICATION_KEYS = frozenset(
    {"asset", "decision_timeframe", "m3_artifact_sha256", "route_profile_sha256"}
)

# These are identity locks derived from the merged M3 artifact's selected route
# parameters and certified horizons.  They are not a second runtime parameter
# source; the binding envelope remains the configuration source of truth.
MOMENTUM_ROUTE_PROFILE_LOCKS = MappingProxyType(
    {
        "BTCUSDT/1h": "edb9f009b74877c39dcf620ea3786797379c76b135e18642e8e0d68d6a1a9c88",
        "BTCUSDT/4h": "145a9ad00fccf1ed23599fa85d28e988c952095985620e7411f5d9019479ceb2",
        "ETHUSDT/4h": "0124642bf1a9f91ca01042375583f4aacc534f14af497329a2a6721c6d3ecdb3",
    }
)


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _require_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    *,
    field_name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{field_name} keys must match exactly; missing={missing}, extra={extra}"
        )


@dataclass(frozen=True, slots=True)
class MomentumFeatureProfile:
    """One certified causal RSI/MACD history profile."""

    rsi_period: int
    rsi_history_bars: int
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    macd_history_bars: int

    def __post_init__(self) -> None:
        for field_name in (
            "rsi_period",
            "rsi_history_bars",
            "macd_fast_period",
            "macd_slow_period",
            "macd_signal_period",
            "macd_history_bars",
        ):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        if self.macd_fast_period > self.macd_slow_period:
            raise ValueError("macd_fast_period must not exceed macd_slow_period")

    def to_mapping(self) -> dict[str, dict[str, int]]:
        return {
            "rsi": {
                "period": self.rsi_period,
                "history_bars": self.rsi_history_bars,
            },
            "macd": {
                "fast_period": self.macd_fast_period,
                "slow_period": self.macd_slow_period,
                "signal_period": self.macd_signal_period,
                "history_bars": self.macd_history_bars,
            },
        }


@dataclass(frozen=True, slots=True)
class MomentumBindingEnvelope:
    """Validated immutable app-owned Momentum binding parameters."""

    asset: str
    decision_timeframe: str
    model_config: MomentumConfig
    feature_profile: MomentumFeatureProfile
    m3_artifact_sha256: str
    route_profile_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.asset, field_name="Momentum route asset")
        _require_text(
            self.decision_timeframe,
            field_name="Momentum route decision_timeframe",
        )
        if not isinstance(self.model_config, MomentumConfig):
            raise TypeError("model_config must be MomentumConfig")
        if not isinstance(self.feature_profile, MomentumFeatureProfile):
            raise TypeError("feature_profile must be MomentumFeatureProfile")
        if self.m3_artifact_sha256 != MOMENTUM_M3_ARTIFACT_SHA256:
            raise ValueError("Momentum binding uses an unapproved M3 artifact")
        _require_text(self.route_profile_sha256, field_name="route_profile_sha256")

    @property
    def route_key(self) -> str:
        return f"{self.asset}/{self.decision_timeframe}"

    def profile_payload(self) -> Mapping[str, Any]:
        return {
            "asset": self.asset,
            "decision_timeframe": self.decision_timeframe,
            "model": self.model_config.to_mapping(),
            "feature_profile": self.feature_profile.to_mapping(),
        }


def momentum_route_profile_digest(
    *,
    asset: str,
    decision_timeframe: str,
    model_config: MomentumConfig,
    feature_profile: MomentumFeatureProfile,
) -> str:
    """Compute the stable identity of one route's certified profile."""

    if not isinstance(model_config, MomentumConfig):
        raise TypeError("model_config must be MomentumConfig")
    if not isinstance(feature_profile, MomentumFeatureProfile):
        raise TypeError("feature_profile must be MomentumFeatureProfile")
    return sha256_fingerprint(
        {
            "asset": _require_text(asset, field_name="asset"),
            "decision_timeframe": _require_text(
                decision_timeframe,
                field_name="decision_timeframe",
            ),
            "model": model_config.to_mapping(),
            "feature_profile": feature_profile.to_mapping(),
        }
    )


def parse_momentum_binding_parameters(
    parameters: Mapping[str, Any],
    *,
    expected_asset: str | None = None,
    expected_decision_timeframe: str | None = None,
) -> MomentumBindingEnvelope:
    """Parse and certification-check one strict Decision binding envelope."""

    if not isinstance(parameters, Mapping):
        raise TypeError("Momentum binding parameters must be a mapping")
    _require_exact_keys(
        parameters,
        frozenset({"model", "feature_profile", "certification"}),
        field_name="Momentum binding parameters",
    )
    model_values = parameters["model"]
    profile_values = parameters["feature_profile"]
    certification = parameters["certification"]
    if not isinstance(model_values, Mapping):
        raise TypeError("Momentum model parameters must be a mapping")
    if not isinstance(profile_values, Mapping):
        raise TypeError("Momentum feature_profile must be a mapping")
    if not isinstance(certification, Mapping):
        raise TypeError("Momentum certification must be a mapping")
    _require_exact_keys(model_values, _MODEL_KEYS, field_name="Momentum model")
    _require_exact_keys(
        profile_values,
        frozenset({"rsi", "macd"}),
        field_name="Momentum feature_profile",
    )
    _require_exact_keys(
        certification,
        _CERTIFICATION_KEYS,
        field_name="Momentum certification",
    )

    rsi_values = profile_values["rsi"]
    macd_values = profile_values["macd"]
    if not isinstance(rsi_values, Mapping) or not isinstance(macd_values, Mapping):
        raise TypeError("Momentum RSI/MACD profiles must be mappings")
    _require_exact_keys(rsi_values, _RSI_KEYS, field_name="Momentum RSI profile")
    _require_exact_keys(macd_values, _MACD_KEYS, field_name="Momentum MACD profile")

    asset = _require_text(
        certification["asset"],
        field_name="Momentum certification asset",
    )
    decision_timeframe = _require_text(
        certification["decision_timeframe"],
        field_name="Momentum certification decision_timeframe",
    )
    if expected_asset is not None and asset != expected_asset:
        raise ValueError("Momentum certification asset does not match lane")
    if (
        expected_decision_timeframe is not None
        and decision_timeframe != expected_decision_timeframe
    ):
        raise ValueError("Momentum certification timeframe does not match lane")

    model_config = MomentumConfig.from_mapping(model_values)
    feature_profile = MomentumFeatureProfile(
        rsi_period=_require_positive_int(rsi_values["period"], field_name="rsi period"),
        rsi_history_bars=_require_positive_int(
            rsi_values["history_bars"], field_name="rsi history_bars"
        ),
        macd_fast_period=_require_positive_int(
            macd_values["fast_period"], field_name="macd fast_period"
        ),
        macd_slow_period=_require_positive_int(
            macd_values["slow_period"], field_name="macd slow_period"
        ),
        macd_signal_period=_require_positive_int(
            macd_values["signal_period"], field_name="macd signal_period"
        ),
        macd_history_bars=_require_positive_int(
            macd_values["history_bars"], field_name="macd history_bars"
        ),
    )
    m3_artifact_sha256 = _require_text(
        certification["m3_artifact_sha256"],
        field_name="m3_artifact_sha256",
    )
    route_profile_sha256 = _require_text(
        certification["route_profile_sha256"],
        field_name="route_profile_sha256",
    )
    if m3_artifact_sha256 != MOMENTUM_M3_ARTIFACT_SHA256:
        raise ValueError("Momentum binding uses an unapproved M3 artifact")
    computed_digest = momentum_route_profile_digest(
        asset=asset,
        decision_timeframe=decision_timeframe,
        model_config=model_config,
        feature_profile=feature_profile,
    )
    if route_profile_sha256 != computed_digest:
        raise ValueError("Momentum route profile digest does not match parameters")
    expected_digest = MOMENTUM_ROUTE_PROFILE_LOCKS.get(f"{asset}/{decision_timeframe}")
    if expected_digest is None:
        raise ValueError(
            f"unsupported certified Momentum route: {asset}/{decision_timeframe}"
        )
    if route_profile_sha256 != expected_digest:
        raise ValueError("Momentum route profile is not M3-certified")
    return MomentumBindingEnvelope(
        asset=asset,
        decision_timeframe=decision_timeframe,
        model_config=model_config,
        feature_profile=feature_profile,
        m3_artifact_sha256=m3_artifact_sha256,
        route_profile_sha256=route_profile_sha256,
    )


def momentum_runtime_factory(
    parameters: Mapping[str, object],
) -> MomentumDecisionPlugin:
    """Create the reviewed plugin after validating the complete envelope."""

    envelope = parse_momentum_binding_parameters(parameters)
    return MomentumDecisionPlugin(envelope.model_config)


def _route_profiles(
    profiles: Mapping[str, MomentumBindingEnvelope],
) -> Mapping[str, MomentumBindingEnvelope]:
    if not isinstance(profiles, Mapping) or not profiles:
        raise ValueError("at least one Momentum route profile is required")
    normalized: dict[str, MomentumBindingEnvelope] = {}
    for route_key, envelope in profiles.items():
        if not isinstance(envelope, MomentumBindingEnvelope):
            raise TypeError("Momentum route profiles must contain envelopes")
        if route_key != envelope.route_key:
            raise ValueError("Momentum route profile key must match envelope route")
        if route_key in normalized:
            raise ValueError(f"duplicate Momentum route profile: {route_key}")
        normalized[route_key] = envelope
    return MappingProxyType(dict(sorted(normalized.items())))


def build_momentum_feature_definitions(
    profiles: Mapping[str, MomentumBindingEnvelope],
) -> tuple[SharedFeatureDefinition, SharedFeatureDefinition]:
    """Build exactly one shared RSI@1 and MACD@1 definition for active routes."""

    routes = _route_profiles(profiles)
    max_rsi_history = max(
        envelope.feature_profile.rsi_history_bars for envelope in routes.values()
    )
    max_macd_history = max(
        envelope.feature_profile.macd_history_bars for envelope in routes.values()
    )

    def _context_profile(context: Any) -> MomentumBindingEnvelope:
        route_key = f"{context.asset}/{context.decision_timeframe}"
        try:
            return routes[route_key]
        except KeyError as exc:
            raise ValueError(f"no certified Momentum route for {route_key}") from exc

    def _closes(context: Any, count: int) -> tuple[float, ...]:
        bars = context.histories.get(context.decision_timeframe)
        if not isinstance(bars, Sequence) or len(bars) < count:
            raise ValueError(f"Momentum feature requires {count} closed decision bars")
        selected = tuple(bars[-count:])
        if any(
            not isinstance(bar, CausalBarView) or not bar.closed for bar in selected
        ):
            raise ValueError("Momentum feature history must contain closed bars")
        return tuple(float(bar.close) for bar in selected)

    def calculate_route_rsi(context: Any) -> float:
        profile = _context_profile(context).feature_profile
        return calculate_rsi(
            _closes(context, profile.rsi_history_bars),
            period=profile.rsi_period,
        )

    def calculate_route_macd(context: Any) -> Mapping[str, float]:
        profile = _context_profile(context).feature_profile
        result = calculate_macd(
            _closes(context, profile.macd_history_bars),
            fast_period=profile.macd_fast_period,
            slow_period=profile.macd_slow_period,
            signal_period=profile.macd_signal_period,
        )
        return {
            "line": result.line,
            "signal": result.signal,
            "histogram": result.histogram,
        }

    return (
        SharedFeatureDefinition(
            name=MOMENTUM_RSI_FEATURE_NAME,
            version=MOMENTUM_FEATURE_VERSION,
            calculator=calculate_route_rsi,
            history_requirements=(
                FeatureHistoryRequirement(source="decision", bars=max_rsi_history),
            ),
        ),
        SharedFeatureDefinition(
            name=MOMENTUM_MACD_FEATURE_NAME,
            version=MOMENTUM_FEATURE_VERSION,
            calculator=calculate_route_macd,
            history_requirements=(
                FeatureHistoryRequirement(source="decision", bars=max_macd_history),
            ),
        ),
    )


__all__ = [
    "MOMENTUM_FEATURE_VERSION",
    "MOMENTUM_M3_ARTIFACT_SHA256",
    "MOMENTUM_MACD_FEATURE_NAME",
    "MOMENTUM_MODEL_SPEC",
    "MOMENTUM_ROUTE_PROFILE_LOCKS",
    "MOMENTUM_RSI_FEATURE_NAME",
    "MomentumBindingEnvelope",
    "MomentumFeatureProfile",
    "build_momentum_feature_definitions",
    "momentum_route_profile_digest",
    "momentum_runtime_factory",
    "parse_momentum_binding_parameters",
]
