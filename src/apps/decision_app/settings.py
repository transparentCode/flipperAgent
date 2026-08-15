"""Strict D9A decision configuration and canonical ingestion geometry bridge.

The decision application owns its graph configuration, while the ingestion
configuration remains the authority for market geometry and instrument
availability.  This module intentionally reads the latter as an external
typed contract and does not import ingestion application code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from apps.decision_app.domain.market_state import TimeframeGrid
from apps.decision_app.planning.planner import DecisionLaneSpec, ModelBindingSpec
from libs.common.config import ConfigManager
from libs.contracts.decision import FrozenMapping, deep_freeze

DECISION_CONFIG_FILE = "configs/decision/global.yaml"
DECISION_ASSET_CONFIG_DIRECTORY = "configs/decision/assets"
DECISION_CONFIG_NAMESPACE = "decision"
DECISION_ASSET_CONFIG_NAMESPACE = "decision.assets"
CANONICAL_INGESTION_CONFIG_FILE = "configs/ingestion/global.yaml"
CANONICAL_INGESTION_ASSET_CONFIG_DIRECTORY = "configs/ingestion/assets"
CANONICAL_INGESTION_CONFIG_NAMESPACE = "ingestion"
CANONICAL_INGESTION_ASSET_CONFIG_NAMESPACE = "ingestion.assets"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


class DecisionPolicySettings(BaseModel):
    """Static lane policy configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "version", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def freeze_parameters(self) -> DecisionPolicySettings:
        object.__setattr__(self, "parameters", deep_freeze(self.parameters))
        return self


class DecisionBindingSettings(BaseModel):
    """One explicit runtime binding in an asset lane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugin: str
    version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, str] = Field(default_factory=dict)

    @field_validator("plugin", "version", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def freeze_parameters_and_dependencies(self) -> DecisionBindingSettings:
        object.__setattr__(self, "parameters", deep_freeze(self.parameters))
        if any(not isinstance(value, str) for value in self.dependencies.values()):
            raise TypeError("binding dependencies must be binding IDs")
        object.__setattr__(
            self,
            "dependencies",
            FrozenMapping(dict(sorted(self.dependencies.items()))),
        )
        return self


class DecisionLaneSettings(BaseModel):
    """One static lane specification owned by decision configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_timeframe: str
    trigger_timeframe: str
    trigger_mode: str
    authority: str = "shadow"
    risk_profile_key: str | None = None
    policy: DecisionPolicySettings
    bindings: dict[str, DecisionBindingSettings]

    @field_validator(
        "decision_timeframe",
        "trigger_timeframe",
        "trigger_mode",
        "authority",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("risk_profile_key", mode="before")
    @classmethod
    def normalize_risk_key(cls, value: object) -> str | None:
        return None if value is None else _text(value, "risk_profile_key")

    @model_validator(mode="after")
    def freeze_bindings(self) -> DecisionLaneSettings:
        if not self.bindings:
            raise ValueError("lane must contain at least one binding")
        object.__setattr__(
            self,
            "bindings",
            FrozenMapping(dict(sorted(self.bindings.items()))),
        )
        return self

    @staticmethod
    def to_lane_spec(
        lane_id: str,
        asset: DecisionAssetSettings,
        lane: DecisionLaneSettings,
    ) -> DecisionLaneSpec:
        return DecisionLaneSpec(
            lane_id=lane_id,
            asset=asset.decision_asset,
            venue=asset.venue,
            instrument_id=asset.instrument_id,
            decision_timeframe=lane.decision_timeframe,
            trigger_timeframe=lane.trigger_timeframe,
            trigger_mode=lane.trigger_mode,
            policy_name=lane.policy.name,
            policy_version=lane.policy.version,
            policy_parameters=lane.policy.parameters,
            authority=lane.authority,  # type: ignore[arg-type]
            risk_profile_key=lane.risk_profile_key,
            bindings=tuple(
                ModelBindingSpec(
                    slot_name=slot,
                    plugin_name=binding.plugin,
                    plugin_version=binding.version,
                    parameters=binding.parameters,
                    dependencies=binding.dependencies,
                )
                for slot, binding in sorted(lane.bindings.items())
            ),
        )


class PriceRelaySettings(BaseModel):
    """Canonical-series price relay configuration for one decision asset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool = False
    timeframes: tuple[str, ...] = ()

    @field_validator("timeframes", mode="before")
    @classmethod
    def normalize_timeframes(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            raise TypeError("price_relay.timeframes must be a list of strings")
        return tuple(_text(item, "price_relay timeframe") for item in value)

    @model_validator(mode="after")
    def validate_timeframes(self) -> PriceRelaySettings:
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError("price_relay.timeframes must not contain duplicates")
        if self.enabled and not self.timeframes:
            raise ValueError("enabled price relay requires at least one timeframe")
        object.__setattr__(self, "timeframes", tuple(sorted(self.timeframes)))
        return self


class DecisionAssetSettings(BaseModel):
    """Explicit split between ingestion lifecycle and decision identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_asset: str
    decision_asset: str
    venue: str
    instrument_id: str
    enabled: StrictBool = True
    lanes: dict[str, DecisionLaneSettings]
    price_relay: PriceRelaySettings = Field(default_factory=PriceRelaySettings)

    @field_validator(
        "manifest_asset", "decision_asset", "venue", "instrument_id", mode="before"
    )
    @classmethod
    def normalize_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def freeze_lanes(self) -> DecisionAssetSettings:
        if not self.lanes and not self.price_relay.enabled:
            raise ValueError(
                "decision asset must contain a lane or an enabled price relay"
            )
        object.__setattr__(
            self,
            "lanes",
            FrozenMapping(dict(sorted(self.lanes.items()))),
        )
        return self

    def lane_specs(self) -> tuple[DecisionLaneSpec, ...]:
        return tuple(
            DecisionLaneSettings.to_lane_spec(
                f"{self.decision_asset}:{lane_id}",
                self,
                lane,
            )
            for lane_id, lane in sorted(self.lanes.items())
        )


class FeaturePolicySettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    allowed_features: tuple[str, ...] = ()

    @field_validator("name", "version", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)


class LiveInputSettings(BaseModel):
    """Bounded direct-cursor input settings for D9B."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_size: StrictInt = 10
    block_ms: StrictInt = 1000

    @model_validator(mode="after")
    def validate_bounds(self) -> LiveInputSettings:
        if self.batch_size <= 0:
            raise ValueError("live_input.batch_size must be positive")
        if self.block_ms < 0:
            raise ValueError("live_input.block_ms must be non-negative")
        return self


class SignalPublicationSettings(BaseModel):
    """Bounded explicit-ID signal publication settings for D9B."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stream_maxlen: StrictInt = 1000
    stream_approximate: StrictBool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> SignalPublicationSettings:
        if self.stream_maxlen <= 0:
            raise ValueError("signal_publication.stream_maxlen must be positive")
        return self


class PriceRelayPublicationSettings(BaseModel):
    """Bounded explicit-ID price publication settings for D9D."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stream_maxlen: StrictInt = 200
    stream_approximate: StrictBool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> PriceRelayPublicationSettings:
        if self.stream_maxlen <= 0:
            raise ValueError("price_relay.stream_maxlen must be positive")
        return self


class DecisionGlobalSettings(BaseModel):
    """Small global settings owned by the bounded decision phases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_policy: FeaturePolicySettings | None = None
    live_input: LiveInputSettings = Field(default_factory=LiveInputSettings)
    signal_publication: SignalPublicationSettings = Field(
        default_factory=SignalPublicationSettings
    )
    price_relay: PriceRelayPublicationSettings = Field(
        default_factory=PriceRelayPublicationSettings
    )


class DecisionConfig:
    """Validated decision config plus canonical ingestion identity metadata."""

    __slots__ = (
        "_initialized",
        "assets",
        "global_settings",
        "instruments",
        "timeframe_grid",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_initialized", False):
            raise AttributeError("DecisionConfig is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("DecisionConfig is immutable")

    def __init__(
        self,
        *,
        global_settings: DecisionGlobalSettings,
        assets: Mapping[str, DecisionAssetSettings],
        timeframe_grid: TimeframeGrid,
        instruments: Mapping[str, CanonicalInstrument],
    ) -> None:
        if not isinstance(global_settings, DecisionGlobalSettings):
            raise TypeError("global_settings must be DecisionGlobalSettings")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid")
        if not isinstance(assets, Mapping) or not assets:
            raise ValueError("decision config must contain assets")
        if not isinstance(instruments, Mapping) or not instruments:
            raise ValueError("canonical ingestion instruments are required")
        normalized_assets: dict[str, DecisionAssetSettings] = {}
        for key, asset in assets.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("decision asset keys must be non-empty strings")
            if not isinstance(asset, DecisionAssetSettings):
                raise TypeError("decision assets must be DecisionAssetSettings")
            if key != asset.manifest_asset:
                raise ValueError("decision asset key must match manifest_asset")
            asset_contract = next(
                (
                    instrument
                    for instrument in instruments.values()
                    if isinstance(instrument, CanonicalInstrument)
                    and instrument.manifest_asset == asset.manifest_asset
                    and instrument.instrument_id == asset.instrument_id
                ),
                None,
            )
            if asset_contract is None:
                raise ValueError(
                    "unknown ingestion instrument: "
                    f"{asset.manifest_asset}/{asset.instrument_id}"
                )
            asset_contract.validate_decision_asset(asset, timeframe_grid)
            normalized_assets[key] = asset
        object.__setattr__(self, "global_settings", global_settings)
        object.__setattr__(
            self,
            "assets",
            FrozenMapping(dict(sorted(normalized_assets.items()))),
        )
        object.__setattr__(self, "timeframe_grid", timeframe_grid)
        normalized_instruments = {key: value for key, value in instruments.items()}
        if any(
            not isinstance(key, str) or not key.strip()
            for key in normalized_instruments
        ) or any(
            not isinstance(value, CanonicalInstrument)
            for value in normalized_instruments.values()
        ):
            raise TypeError(
                "instruments must map non-empty keys to CanonicalInstrument"
            )
        object.__setattr__(
            self,
            "instruments",
            FrozenMapping(dict(sorted(normalized_instruments.items()))),
        )
        object.__setattr__(self, "_initialized", True)

    @property
    def active_assets(self) -> tuple[DecisionAssetSettings, ...]:
        return tuple(asset for asset in self.assets.values() if asset.enabled)

    def lane_specs(self) -> tuple[DecisionLaneSpec, ...]:
        return tuple(
            lane for asset in self.active_assets for lane in asset.lane_specs()
        )


class CanonicalInstrument:
    """Minimal external ingestion instrument contract used by D9A."""

    __slots__ = (
        "instrument_id",
        "manifest_asset",
        "provider_symbols",
        "timeframes",
        "venue",
    )

    def __init__(
        self,
        *,
        manifest_asset: str,
        instrument_id: str,
        venue: str,
        timeframes: tuple[str, ...],
        provider_symbols: Mapping[str, str] | None = None,
    ) -> None:
        self.manifest_asset = _text(manifest_asset, "manifest_asset")
        self.instrument_id = _text(instrument_id, "instrument_id")
        self.venue = _text(venue, "venue")
        self.timeframes = tuple(
            sorted({_text(item, "timeframe") for item in timeframes})
        )
        if not self.timeframes:
            raise ValueError("instrument timeframes must not be empty")
        if provider_symbols is None:
            normalized_symbols: dict[str, str] = {}
        elif not isinstance(provider_symbols, Mapping):
            raise TypeError("provider_symbols must be a mapping")
        else:
            normalized_symbols = {
                _text(key, "provider symbol key"): _text(value, "provider symbol")
                for key, value in provider_symbols.items()
            }
        self.provider_symbols = FrozenMapping(dict(sorted(normalized_symbols.items())))

    def validate_decision_asset(
        self,
        asset: DecisionAssetSettings,
        timeframe_grid: TimeframeGrid,
    ) -> None:
        if asset.instrument_id != self.instrument_id:
            raise ValueError(
                "decision instrument_id does not match ingestion instrument"
            )
        if asset.venue != self.venue:
            raise ValueError("decision venue does not match ingestion instrument")
        if asset.decision_asset == self.manifest_asset:
            raise ValueError("decision_asset must remain distinct from manifest_asset")
        canonical_symbol = self.provider_symbols.get("binance_native")
        if canonical_symbol is not None and asset.decision_asset != canonical_symbol:
            raise ValueError(
                "decision_asset does not match the canonical live provider symbol"
            )
        for lane in asset.lanes.values():
            for timeframe in (lane.decision_timeframe, lane.trigger_timeframe):
                if timeframe not in self.timeframes:
                    raise ValueError(f"unknown ingestion timeframe: {timeframe}")
                timeframe_grid.duration(timeframe)
            for binding in lane.bindings.values():
                for timeframe in binding.parameters.get("required_timeframes", ()):
                    if timeframe not in self.timeframes:
                        raise ValueError(
                            f"unknown required ingestion timeframe: {timeframe}"
                        )
        for timeframe in asset.price_relay.timeframes:
            if timeframe not in self.timeframes:
                raise ValueError(f"unknown price relay timeframe: {timeframe}")
            timeframe_grid.duration(timeframe)


def _parse_alignment_origin(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("ingestion calendar alignment_origin must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid ingestion alignment_origin") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("ingestion alignment_origin must be UTC")
    return parsed.astimezone(UTC)


def load_canonical_ingestion_contract(
    config_manager: ConfigManager,
) -> tuple[TimeframeGrid, Mapping[str, CanonicalInstrument]]:
    """Read only the canonical geometry/identity fields needed by decision_app."""

    if not isinstance(config_manager, ConfigManager):
        raise TypeError("config_manager must be ConfigManager")
    # Register the canonical external contract at this boundary rather than
    # importing ingestion application settings or assuming another caller has
    # already registered the files.
    config_manager.register_file(CANONICAL_INGESTION_CONFIG_FILE)
    config_manager.register_directory(
        CANONICAL_INGESTION_ASSET_CONFIG_DIRECTORY,
        namespace=CANONICAL_INGESTION_ASSET_CONFIG_NAMESPACE,
        pattern="*.yaml",
    )
    calendar = config_manager.get(f"{CANONICAL_INGESTION_CONFIG_NAMESPACE}.calendar")
    raw_timeframes = config_manager.get(
        f"{CANONICAL_INGESTION_CONFIG_NAMESPACE}.timeframes"
    )
    raw_assets = config_manager.get(CANONICAL_INGESTION_ASSET_CONFIG_NAMESPACE)
    if not isinstance(calendar, Mapping) or not isinstance(raw_timeframes, Mapping):
        raise TypeError("canonical ingestion calendar/timeframes are required")
    if not isinstance(raw_assets, Mapping):
        raise TypeError("canonical ingestion assets are required")
    if calendar.get("type") != "continuous" or calendar.get("timezone") != "UTC":
        raise ValueError("decision_app requires continuous UTC ingestion geometry")
    durations: dict[str, timedelta] = {}
    for timeframe, raw in raw_timeframes.items():
        if not isinstance(timeframe, str) or not isinstance(raw, Mapping):
            raise TypeError("ingestion timeframes must be mappings")
        seconds = raw.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError(f"invalid duration for ingestion timeframe {timeframe}")
        durations[timeframe] = timedelta(seconds=seconds)
    grid = TimeframeGrid(
        alignment_origin=_parse_alignment_origin(calendar.get("alignment_origin")),
        durations=durations,
    )
    instruments: dict[str, CanonicalInstrument] = {}
    for manifest_asset, raw_asset in raw_assets.items():
        manifest_asset = _text(manifest_asset, "manifest asset")
        if not isinstance(raw_asset, Mapping):
            raise TypeError("ingestion asset entries must be mappings")
        raw_instruments = raw_asset.get("instruments")
        if not isinstance(raw_instruments, Mapping):
            raise TypeError(f"ingestion asset {manifest_asset} has no instruments")
        for instrument_id, raw_instrument in raw_instruments.items():
            if not isinstance(raw_instrument, Mapping):
                raise TypeError("ingestion instrument entries must be mappings")
            timeframes = raw_instrument.get("timeframes")
            if not isinstance(timeframes, (list, tuple)):
                raise TypeError("ingestion instrument timeframes must be a list")
            instrument_key = (
                manifest_asset
                if manifest_asset not in instruments
                else f"{manifest_asset}:{instrument_id}"
            )
            instruments[instrument_key] = CanonicalInstrument(
                manifest_asset=manifest_asset,
                instrument_id=instrument_id,
                venue=_text(raw_instrument.get("venue"), "venue"),
                timeframes=tuple(timeframes),
                provider_symbols=raw_instrument.get("provider_symbols"),
            )
    return grid, dict(sorted(instruments.items()))


def load_decision_config(
    config_manager: ConfigManager,
    *,
    global_file: str | Path = DECISION_CONFIG_FILE,
    assets_directory: str | Path = DECISION_ASSET_CONFIG_DIRECTORY,
) -> DecisionConfig:
    """Register and strictly load the D9A decision config namespace."""

    if not isinstance(config_manager, ConfigManager):
        raise TypeError("config_manager must be ConfigManager")
    config_manager.register_file(global_file)
    config_manager.register_directory(
        assets_directory,
        namespace=DECISION_ASSET_CONFIG_NAMESPACE,
        pattern="*.yaml",
    )
    raw_global = config_manager.get("decision", {})
    raw_assets = config_manager.get(DECISION_ASSET_CONFIG_NAMESPACE, {})
    if not isinstance(raw_global, Mapping):
        raise TypeError("decision global config must be a mapping")
    if not isinstance(raw_assets, Mapping):
        raise TypeError("decision asset config must be a mapping")
    global_settings = DecisionGlobalSettings.model_validate(raw_global)
    assets = {
        key: DecisionAssetSettings.model_validate(value)
        for key, value in raw_assets.items()
    }
    grid, instruments = load_canonical_ingestion_contract(config_manager)
    return DecisionConfig(
        global_settings=global_settings,
        assets=assets,
        timeframe_grid=grid,
        instruments=instruments,
    )


__all__ = [
    "CANONICAL_INGESTION_ASSET_CONFIG_DIRECTORY",
    "CANONICAL_INGESTION_ASSET_CONFIG_NAMESPACE",
    "CANONICAL_INGESTION_CONFIG_FILE",
    "CANONICAL_INGESTION_CONFIG_NAMESPACE",
    "DECISION_ASSET_CONFIG_DIRECTORY",
    "DECISION_ASSET_CONFIG_NAMESPACE",
    "DECISION_CONFIG_FILE",
    "DECISION_CONFIG_NAMESPACE",
    "CanonicalInstrument",
    "DecisionAssetSettings",
    "DecisionBindingSettings",
    "DecisionConfig",
    "DecisionGlobalSettings",
    "DecisionLaneSettings",
    "DecisionPolicySettings",
    "FeaturePolicySettings",
    "LiveInputSettings",
    "PriceRelayPublicationSettings",
    "PriceRelaySettings",
    "SignalPublicationSettings",
    "load_canonical_ingestion_contract",
    "load_decision_config",
]
