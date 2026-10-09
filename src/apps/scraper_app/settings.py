"""Strict settings for the v2 collector and its dataset catalog.

The collector owns ``configs/scraper.yaml`` (namespace ``scraper``). Unknown
keys are rejected. The database URI is the only value taken from the
environment.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from apps.scraper_app.domain.datasets import (
    SIZING_MARGIN_BARS,
    DatasetSpec,
    Shape,
    interval_seconds,
)
from apps.scraper_app.domain.payloads import (
    KIND_HEATMAP,
    KIND_LIQ_MAP,
    KIND_MAX_PAIN,
    HeatmapExpect,
    PayloadSpec,
)
from libs.common.config import ConfigManager

SCRAPER_CONFIG_FILE = "configs/scraper.yaml"
SCRAPER_CONFIG_NAMESPACE = "scraper"
SCRAPER_POSTGRES_URI_ENV = "SCRAPER_POSTGRES_URI"
SCRAPER_PURGE_POSTGRES_URI_ENV = "SCRAPER_PURGE_POSTGRES_URI"
API_READ_TOKEN_ENV = "SCRAPER_API_READ_TOKEN"
API_READ_TOKEN_FILE_ENV = "SCRAPER_API_READ_TOKEN_FILE"


class SettingsError(RuntimeError):
    """Configuration or environment is unusable; the process must not start."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ServerSettings(_Strict):
    host: str = "0.0.0.0"
    port: StrictInt = Field(default=8005, ge=1, le=65535)


class TradingViewSettings(_Strict):
    ws_url: str
    origin: str
    connect_timeout_seconds: float = Field(gt=0)
    read_deadline_seconds: float = Field(gt=0)
    max_response_bytes: StrictInt = Field(gt=0)
    request_spacing_seconds: float = Field(ge=0)
    max_attempts_per_slot: StrictInt = Field(ge=1)
    retry_backoff_seconds: tuple[float, ...]
    min_bars_per_request: StrictInt = Field(ge=1)
    max_bars_per_request: StrictInt = Field(ge=1)

    @field_validator("retry_backoff_seconds")
    @classmethod
    def _backoff_positive(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(v < 0 for v in value):
            raise ValueError("retry_backoff_seconds must be non-negative")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> TradingViewSettings:
        if self.min_bars_per_request > self.max_bars_per_request:
            raise ValueError(
                "min_bars_per_request must not exceed max_bars_per_request"
            )
        if len(self.retry_backoff_seconds) < self.max_attempts_per_slot - 1:
            raise ValueError("retry_backoff_seconds needs one entry per retry")
        return self


class SlotSettings(_Strict):
    """Wall-clock slots shared by every collection lane."""

    slot_minutes: tuple[StrictInt, ...] = Field(min_length=1)
    slot_second: StrictInt = Field(ge=0, le=59)
    wake_check_seconds: float = Field(gt=0)

    @field_validator("slot_minutes")
    @classmethod
    def _minutes_valid(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(not 0 <= m <= 59 for m in value) or len(set(value)) != len(value):
            raise ValueError("slot_minutes must be unique values in 0..59")
        return tuple(sorted(value))


class ScheduleSettings(SlotSettings):
    late_bar_retries: StrictInt = Field(ge=0)
    late_bar_retry_seconds: float = Field(ge=0)


class DatabaseSettings(_Strict):
    connect_timeout_seconds: float = Field(gt=0)
    command_timeout_seconds: float = Field(gt=0)


class ReadinessSettings(_Strict):
    max_read_age_seconds: StrictInt = Field(gt=0)
    latest_bar_grace_seconds: StrictInt = Field(ge=0)
    recent_gap_window_seconds: StrictInt = Field(gt=0)
    max_clock_skew_seconds: StrictInt = Field(gt=0)
    probe_timeout_seconds: float = Field(gt=0)


class DatasetSettings(_Strict):
    id: str = Field(min_length=1)
    request_symbol: str = Field(min_length=1)
    canonical_symbol: str = Field(min_length=1)
    interval: Literal["1h", "4h", "1D"]
    shape: Literal["ohlcv", "ohlc"]
    contiguous: StrictBool
    non_negative: StrictBool
    finality_horizon_seconds: StrictInt = Field(ge=0)
    revision_watch_seconds: StrictInt = Field(ge=0)
    max_live_lag_seconds: StrictInt = Field(default=7800, ge=0)
    initial_bars: StrictInt = Field(default=5000, ge=1)

    def to_spec(self) -> DatasetSpec:
        return DatasetSpec(
            id=self.id,
            request_symbol=self.request_symbol,
            canonical_symbol=self.canonical_symbol,
            interval=self.interval,
            shape=Shape(self.shape),
            contiguous=self.contiguous,
            non_negative=self.non_negative,
            finality_horizon_seconds=self.finality_horizon_seconds,
            revision_watch_seconds=self.revision_watch_seconds,
            max_live_lag_seconds=self.max_live_lag_seconds,
            initial_bars=self.initial_bars,
        )


class HeatmapExpectSettings(_Strict):
    exchange: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    interval_seconds: StrictInt | None = Field(default=None, gt=0)
    columns: StrictInt | None = Field(default=None, ge=1)


class CoinGlassDatasetSettings(_Strict):
    id: str = Field(min_length=1)
    kind: Literal["liq_heatmap", "max_pain", "liq_map"]
    endpoint: str = Field(min_length=2)
    args: dict[str, Any] = Field(default_factory=dict)
    requires_login: StrictBool = False
    expect: HeatmapExpectSettings | None = None
    coins: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _kind_fields(self) -> CoinGlassDatasetSettings:
        if not self.endpoint.startswith("/"):
            raise ValueError("endpoint must start with '/'")
        if self.kind == KIND_HEATMAP and (
            self.expect is None
            or self.coins
            or self.expect.interval_seconds is None
            or self.expect.columns is None
        ):
            raise ValueError(
                "a liq_heatmap needs 'expect' with interval_seconds and columns, "
                "and takes no 'coins'"
            )
        if self.kind == KIND_LIQ_MAP and (
            self.expect is None
            or self.coins
            or self.expect.interval_seconds is not None
            or self.expect.columns is not None
        ):
            raise ValueError(
                "a liq_map needs 'expect' with exchange and instrument only, "
                "and takes no 'coins'"
            )
        if self.kind == KIND_MAX_PAIN and (
            self.expect is not None
            or not self.coins
            or len(set(self.coins)) != len(self.coins)
        ):
            raise ValueError("a max_pain needs unique 'coins' and takes no 'expect'")
        return self

    def to_spec(self) -> PayloadSpec:
        expect = self.expect
        return PayloadSpec(
            id=self.id,
            kind=self.kind,
            endpoint=self.endpoint,
            args=dict(self.args),
            requires_login=self.requires_login,
            expect=None
            if expect is None
            else HeatmapExpect(
                exchange=expect.exchange,
                instrument=expect.instrument,
                interval_seconds=expect.interval_seconds or 0,
                columns=expect.columns or 0,
            ),
            coins=tuple(self.coins),
        )


class CoinGlassReadinessSettings(_Strict):
    max_read_age_seconds: StrictInt = Field(gt=0)


class CoinGlassSettings(SlotSettings):
    """Optional second lane: CoinGlass through a headless engine over CDP."""

    engine_url: str = Field(min_length=1)
    host_page_url: str = Field(min_length=1)
    connect_timeout_seconds: float = Field(gt=0)
    command_timeout_seconds: float = Field(gt=0)
    navigation_timeout_seconds: float = Field(gt=0)
    helper_timeout_seconds: float = Field(gt=0)
    cycle_deadline_seconds: float = Field(gt=0)
    call_spacing_seconds: float = Field(ge=0)
    # Whole-cycle retries for a failure before the first helper call.
    cycle_retries: StrictInt = Field(default=0, ge=0)
    cycle_retry_delay_seconds: float = Field(default=20, ge=0)
    max_payload_bytes: StrictInt = Field(gt=0)
    max_provider_age_seconds: float = Field(gt=0)
    cookies_path: str | None = None
    readiness: CoinGlassReadinessSettings
    datasets: tuple[CoinGlassDatasetSettings, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> CoinGlassSettings:
        ids = [d.id for d in self.datasets]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate coinglass dataset ids: {duplicates}")
        return self

    def payload_specs(self) -> tuple[PayloadSpec, ...]:
        return tuple(d.to_spec() for d in self.datasets)


class RetentionSettings(SlotSettings):
    """Purge of stored data older than a per-provider number of days.

    ``None`` keeps everything of that provider.
    """

    enabled: StrictBool = True
    batch_rows: StrictInt = Field(gt=0)
    tradingview_days: StrictInt | None = Field(default=None, ge=1)
    coinglass_days: StrictInt | None = Field(default=None, ge=1)
    readiness_max_age_seconds: StrictInt = Field(gt=0)


class ApiSettings(_Strict):
    """Read-only agent API under ``/v2``. The token comes from the environment."""

    enabled: StrictBool = True
    default_limit: StrictInt = Field(gt=0)
    max_limit: StrictInt = Field(gt=0)
    max_payload_list: StrictInt = Field(gt=0)
    pool_max_size: StrictInt = Field(ge=1)
    query_timeout_seconds: float = Field(gt=0)
    as_of_settle_seconds: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _limits(self) -> ApiSettings:
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit must not exceed max_limit")
        return self


# A heatmap read carries 24 h of history, so two days keep every payload that a
# later read could still overlap.
HEATMAP_MIN_RETENTION_DAYS = 2


class ScraperSettings(_Strict):
    server: ServerSettings = ServerSettings()
    database: DatabaseSettings
    tradingview: TradingViewSettings
    schedule: ScheduleSettings
    readiness: ReadinessSettings
    datasets: tuple[DatasetSettings, ...] = Field(min_length=1)
    coinglass: CoinGlassSettings | None = None
    retention: RetentionSettings | None = None
    api: ApiSettings | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> ScraperSettings:
        ids = [d.id for d in self.datasets]
        if self.coinglass is not None:
            ids += [d.id for d in self.coinglass.datasets]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate dataset ids: {duplicates}")
        return self

    @model_validator(mode="after")
    def _initial_bars_within_limit(self) -> ScraperSettings:
        limit = self.tradingview.max_bars_per_request
        too_big = [d.id for d in self.datasets if d.initial_bars > limit]
        if too_big:
            raise ValueError(f"initial_bars exceeds max_bars_per_request: {too_big}")
        return self

    @model_validator(mode="after")
    def _watch_window(self) -> ScraperSettings:
        limit = self.tradingview.max_bars_per_request
        short = [
            d.id
            for d in self.datasets
            if d.revision_watch_seconds < d.finality_horizon_seconds
        ]
        if short:
            raise ValueError(
                f"revision_watch_seconds below finality_horizon_seconds: {short}"
            )
        # A request must never be silently shorter than the watch window.
        long = [
            d.id
            for d in self.datasets
            if math.ceil(d.revision_watch_seconds / interval_seconds(d.interval))
            + SIZING_MARGIN_BARS
            > limit
        ]
        if long:
            raise ValueError(
                f"revision_watch_seconds needs more than max_bars_per_request: {long}"
            )
        return self

    @model_validator(mode="after")
    def _retention_covers_the_watch_window(self) -> ScraperSettings:
        retention = self.retention
        if retention is None:
            return self
        days = retention.tradingview_days
        if days is not None:
            # Otherwise every read would re-insert purged bars as new observations.
            short = [
                d.id
                for d in self.datasets
                if days * 86400
                < d.revision_watch_seconds + 2 * interval_seconds(d.interval)
            ]
            if short:
                raise ValueError(
                    "tradingview_days is shorter than revision_watch_seconds + "
                    f"2 intervals: {short}"
                )
        cg_days = retention.coinglass_days
        if (
            cg_days is not None
            and cg_days < HEATMAP_MIN_RETENTION_DAYS
            and self.coinglass is not None
            and any(d.kind == KIND_HEATMAP for d in self.coinglass.datasets)
        ):
            raise ValueError(
                f"coinglass_days must be at least {HEATMAP_MIN_RETENTION_DAYS} "
                "while heatmap datasets are configured"
            )
        return self

    def dataset_specs(self) -> tuple[DatasetSpec, ...]:
        return tuple(d.to_spec() for d in self.datasets)

    def payload_specs(self) -> tuple[PayloadSpec, ...]:
        return () if self.coinglass is None else self.coinglass.payload_specs()


def parse_settings(raw: Mapping[str, object]) -> ScraperSettings:
    """Validate the mapping found under the ``scraper`` namespace."""
    return ScraperSettings.model_validate(raw)


def load_settings(config_manager: ConfigManager) -> ScraperSettings:
    config_manager.register_file(SCRAPER_CONFIG_FILE)
    raw = config_manager.get(SCRAPER_CONFIG_NAMESPACE)
    if not isinstance(raw, Mapping):
        raise SettingsError("scraper configuration must be a mapping")
    return parse_settings(raw)


def database_uri(environ: Mapping[str, str] | None = None) -> str:
    """The collector's own database URI; fails fast when unset."""
    env = os.environ if environ is None else environ
    uri = env.get(SCRAPER_POSTGRES_URI_ENV, "").strip()
    if not uri:
        raise SettingsError(f"{SCRAPER_POSTGRES_URI_ENV} is not set")
    return uri


def purge_database_uri(environ: Mapping[str, str] | None = None) -> str | None:
    """The purge role's URI; ``None`` when unset (env only, never YAML)."""
    env = os.environ if environ is None else environ
    return env.get(SCRAPER_PURGE_POSTGRES_URI_ENV, "").strip() or None


__all__ = [
    "API_READ_TOKEN_ENV",
    "API_READ_TOKEN_FILE_ENV",
    "HEATMAP_MIN_RETENTION_DAYS",
    "SCRAPER_CONFIG_FILE",
    "SCRAPER_CONFIG_NAMESPACE",
    "SCRAPER_POSTGRES_URI_ENV",
    "SCRAPER_PURGE_POSTGRES_URI_ENV",
    "ApiSettings",
    "CoinGlassDatasetSettings",
    "CoinGlassReadinessSettings",
    "CoinGlassSettings",
    "DatabaseSettings",
    "DatasetSettings",
    "HeatmapExpectSettings",
    "ReadinessSettings",
    "RetentionSettings",
    "ScheduleSettings",
    "ScraperSettings",
    "ServerSettings",
    "SettingsError",
    "SlotSettings",
    "TradingViewSettings",
    "database_uri",
    "load_settings",
    "parse_settings",
    "purge_database_uri",
]
