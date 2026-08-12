"""Typed configuration contracts for the ingestion foundation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from libs.common.config import ConfigManager

INGESTION_CONFIG_FILE = "configs/ingestion/global.yaml"
INGESTION_ASSET_CONFIG_DIRECTORY = "configs/ingestion/assets"
INGESTION_CONFIG_NAMESPACE = "ingestion"
INGESTION_ASSET_CONFIG_NAMESPACE = "ingestion.assets"


def _text(value: object, field_name: str, *, uppercase: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")  # noqa: TRY004
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized.upper() if uppercase else normalized


def _unique_text_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")  # noqa: TRY004
    normalized = tuple(_text(item, field_name) for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


class CalendarSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    timezone: str
    alignment_origin: datetime

    @field_validator("type", "timezone", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: ValidationInfo) -> str:
        return _text(value, info.field_name)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value != "continuous":
            raise ValueError("calendar type must be 'continuous'")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if value != "UTC":
            raise ValueError("calendar timezone must be 'UTC'")
        return value

    @field_validator("alignment_origin", mode="before")
    @classmethod
    def validate_alignment_origin(cls, value: object) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(
                    "alignment_origin must be a valid ISO-8601 timestamp"
                ) from exc
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise TypeError(
                "alignment_origin must be an explicit datetime or ISO-8601 string"
            )

        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("alignment_origin must be timezone-aware UTC")
        return parsed.astimezone(UTC)

    @field_serializer("alignment_origin")
    def serialize_alignment_origin(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class TimeframeSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_seconds: StrictInt = Field(gt=0)


class RecoverySettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrency: StrictInt = Field(gt=0)
    page_limit: StrictInt = Field(gt=0)
    max_attempts_per_provider: StrictInt = Field(gt=0)
    retry_backoff_seconds: StrictInt = Field(ge=0)
    rest_finalization_grace_seconds: StrictInt = Field(ge=0)


class WebSocketSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stream_url: str
    queue_maxsize: StrictInt = Field(gt=0)

    @field_validator("stream_url", mode="before")
    @classmethod
    def validate_stream_url(cls, value: object) -> str:
        normalized = _text(value, "stream_url")
        if not normalized.startswith("wss://"):
            raise ValueError("stream_url must use wss://")
        return normalized


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reconnect_backoff_seconds: StrictInt = Field(ge=0)


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str
    port: StrictInt = Field(ge=1, le=65_535)

    @field_validator("host", mode="before")
    @classmethod
    def normalize_host(cls, value: object) -> str:
        return _text(value, "host")


class PublicationSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_size: StrictInt = Field(gt=0)
    idle_sleep_seconds: StrictInt = Field(gt=0)
    error_backoff_seconds: StrictInt = Field(gt=0)
    stream_maxlen: StrictInt = Field(gt=0)
    stream_approximate: StrictBool


class RetentionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candle_days: StrictInt = Field(gt=0)
    published_outbox_days: StrictInt = Field(gt=0)
    cleanup_interval_seconds: StrictInt = Field(gt=0)
    error_backoff_seconds: StrictInt = Field(ge=0)
    outbox_delete_batch_size: StrictInt = Field(gt=0)
    outbox_max_batches_per_run: StrictInt = Field(gt=0)


class ProviderSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool
    exchange_id: str | None = None

    @field_validator("exchange_id")
    @classmethod
    def normalize_exchange_id(cls, value: str | None) -> str | None:
        return None if value is None else _text(value, "exchange_id")


class InstrumentSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: str
    market_type: str
    base_asset: str
    quote_asset: str
    settlement_asset: str
    live_provider: str
    historical_providers: tuple[str, ...]
    provider_symbols: Mapping[str, str]
    timeframes: tuple[str, ...]

    @field_validator("venue", "market_type", "live_provider", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: ValidationInfo) -> str:
        return _text(value, info.field_name)

    @field_validator("base_asset", "quote_asset", "settlement_asset", mode="before")
    @classmethod
    def normalize_asset_code(cls, value: object, info: ValidationInfo) -> str:
        return _text(value, info.field_name, uppercase=True)

    @field_validator("historical_providers", "timeframes", mode="before")
    @classmethod
    def normalize_unique_sequence(
        cls, value: object, info: ValidationInfo
    ) -> tuple[str, ...]:
        return _unique_text_sequence(value, info.field_name)

    @field_validator("provider_symbols", mode="before")
    @classmethod
    def normalize_provider_symbols(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError("provider_symbols must be a mapping")  # noqa: TRY004
        normalized: dict[str, str] = {}
        for provider, symbol in value.items():
            provider_name = _text(provider, "provider symbol provider")
            if provider_name in normalized:
                raise ValueError(
                    "provider_symbols must not contain duplicate providers"
                )
            normalized[provider_name] = _text(
                symbol, f"provider symbol for {provider_name}"
            )
        return normalized

    @field_validator("provider_symbols")
    @classmethod
    def freeze_provider_symbols(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @field_serializer("provider_symbols")
    def serialize_provider_symbols(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class AssetSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: str
    enabled: StrictBool
    owns_manifest_lifecycle: StrictBool = False
    instruments: Mapping[str, InstrumentSettings]

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str:
        return _text(value, "asset", uppercase=True)

    @field_validator("instruments", mode="before")
    @classmethod
    def normalize_instrument_keys(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("instruments must contain at least one instrument")
        normalized: dict[str, Any] = {}
        for instrument_id, instrument in value.items():
            key = _text(instrument_id, "instrument id")
            if key in normalized:
                raise ValueError(f"duplicate instrument id: {key}")
            normalized[key] = instrument
        return normalized

    @field_validator("instruments")
    @classmethod
    def freeze_instruments(
        cls, value: Mapping[str, InstrumentSettings]
    ) -> Mapping[str, InstrumentSettings]:
        return MappingProxyType(dict(value))

    @field_serializer("instruments")
    def serialize_instruments(
        self, value: Mapping[str, InstrumentSettings]
    ) -> dict[str, InstrumentSettings]:
        return dict(value)


class IngestionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_timeframe: str
    calendar: CalendarSettings
    recovery: RecoverySettings
    websocket: WebSocketSettings
    runtime: RuntimeSettings
    server: ServerSettings
    publication: PublicationSettings
    retention: RetentionSettings
    timeframes: Mapping[str, TimeframeSettings]
    providers: Mapping[str, ProviderSettings]
    assets: Mapping[str, AssetSettings]

    @field_validator("base_timeframe", mode="before")
    @classmethod
    def normalize_base_timeframe(cls, value: object) -> str:
        return _text(value, "base_timeframe")

    @field_validator("timeframes", "providers", "assets", mode="before")
    @classmethod
    def normalize_mapping_keys(
        cls, value: object, info: ValidationInfo
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{info.field_name} must be a mapping")  # noqa: TRY004
        normalized: dict[str, Any] = {}
        uppercase = info.field_name == "assets"
        for raw_key, raw_value in value.items():
            key = _text(raw_key, f"{info.field_name} id", uppercase=uppercase)
            if key in normalized:
                raise ValueError(f"duplicate {info.field_name} id: {key}")
            normalized[key] = raw_value
        if info.field_name in {"timeframes", "providers"} and not normalized:
            raise ValueError(f"{info.field_name} must contain at least one entry")
        return normalized

    @field_validator("timeframes", "providers", "assets")
    @classmethod
    def freeze_mappings(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return MappingProxyType(dict(value))

    @field_serializer("timeframes", "providers", "assets")
    def serialize_mappings(
        self,
        value: Mapping[str, TimeframeSettings | ProviderSettings | AssetSettings],
    ) -> dict[str, TimeframeSettings | ProviderSettings | AssetSettings]:
        return dict(value)

    @model_validator(mode="after")
    def validate_references(self) -> IngestionSettings:
        if self.base_timeframe not in self.timeframes:
            raise ValueError(
                f"base_timeframe '{self.base_timeframe}' is not configured in timeframes"
            )

        for asset_name, asset_settings in self.assets.items():
            if asset_name != asset_settings.asset:
                raise ValueError(
                    f"asset filename stem '{asset_name}' does not match declared asset "
                    f"'{asset_settings.asset}'"
                )
            for instrument_id, instrument in asset_settings.instruments.items():
                if instrument.base_asset != asset_settings.asset:
                    raise ValueError(
                        f"instrument '{instrument_id}' base_asset '{instrument.base_asset}' "
                        f"does not match asset '{asset_settings.asset}'"
                    )

                referenced_providers = {
                    instrument.live_provider,
                    *instrument.historical_providers,
                }
                for provider_id in referenced_providers:
                    provider = self.providers.get(provider_id)
                    if provider is None:
                        raise ValueError(
                            f"instrument '{instrument_id}' references unknown provider '{provider_id}'"
                        )
                    if provider_id == instrument.live_provider and not provider.enabled:
                        raise ValueError(
                            f"live provider '{provider_id}' for instrument '{instrument_id}' is disabled"
                        )
                    if provider_id not in instrument.provider_symbols:
                        raise ValueError(
                            f"instrument '{instrument_id}' is missing a symbol for provider '{provider_id}'"
                        )

                for timeframe in instrument.timeframes:
                    if timeframe not in self.timeframes:
                        raise ValueError(
                            f"instrument '{instrument_id}' references unknown timeframe '{timeframe}'"
                        )
                if self.base_timeframe not in instrument.timeframes:
                    raise ValueError(
                        f"instrument '{instrument_id}' does not include base timeframe "
                        f"'{self.base_timeframe}'"
                    )
        return self


def _load_settings_from_registered_config(
    config_manager: ConfigManager,
    *,
    config_file: str,
    asset_directory: str,
    config_namespace: str,
    asset_namespace: str,
) -> IngestionSettings:
    config_manager.register_file(config_file)
    config_manager.register_directory(
        asset_directory,
        namespace=asset_namespace,
        pattern="*.yaml",
    )

    raw_config = config_manager.get(config_namespace)
    if not isinstance(raw_config, dict):
        raise ValueError(  # noqa: TRY004
            f"{config_namespace} global configuration must be a mapping"
        )
    return IngestionSettings.model_validate(raw_config)


def load_ingestion_settings(config_manager: ConfigManager) -> IngestionSettings:
    """Register and validate the canonical ingestion configuration."""
    return _load_settings_from_registered_config(
        config_manager,
        config_file=INGESTION_CONFIG_FILE,
        asset_directory=INGESTION_ASSET_CONFIG_DIRECTORY,
        config_namespace=INGESTION_CONFIG_NAMESPACE,
        asset_namespace=INGESTION_ASSET_CONFIG_NAMESPACE,
    )


__all__ = [
    "INGESTION_ASSET_CONFIG_DIRECTORY",
    "INGESTION_ASSET_CONFIG_NAMESPACE",
    "INGESTION_CONFIG_FILE",
    "INGESTION_CONFIG_NAMESPACE",
    "AssetSettings",
    "CalendarSettings",
    "IngestionSettings",
    "InstrumentSettings",
    "ProviderSettings",
    "PublicationSettings",
    "RecoverySettings",
    "RetentionSettings",
    "RuntimeSettings",
    "ServerSettings",
    "TimeframeSettings",
    "WebSocketSettings",
    "load_ingestion_settings",
]
