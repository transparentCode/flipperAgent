"""Static dataset catalog of the read API, built from the validated settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.scraper_app.domain.datasets import DatasetSpec
from apps.scraper_app.settings import ScraperSettings

PROVIDER_TRADINGVIEW = "tradingview"
PROVIDER_COINGLASS = "coinglass"
KIND_BARS = "bars"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    provider: str
    kind: str
    max_age_seconds: int
    requires_login: bool
    retention_days: int | None
    cadence: dict[str, Any]
    identity: dict[str, Any]
    spec: DatasetSpec | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_bars(self) -> bool:
        return self.kind == KIND_BARS

    def static_fields(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "kind": self.kind,
            **self.identity,
            "cadence": self.cadence,
            **self.extra,
            "retention_days": self.retention_days,
            "max_age_seconds": self.max_age_seconds,
            "requires_login": self.requires_login,
        }


def build_catalog(settings: ScraperSettings) -> dict[str, CatalogEntry]:
    retention = (
        settings.retention
        if settings.retention and settings.retention.enabled
        else None
    )
    entries: dict[str, CatalogEntry] = {}
    schedule = settings.schedule
    for dataset in settings.datasets:
        spec = dataset.to_spec()
        entries[spec.id] = CatalogEntry(
            id=spec.id,
            provider=PROVIDER_TRADINGVIEW,
            kind=KIND_BARS,
            max_age_seconds=settings.readiness.max_read_age_seconds,
            requires_login=False,
            retention_days=None if retention is None else retention.tradingview_days,
            cadence={
                "slot_minutes": list(schedule.slot_minutes),
                "slot_second": schedule.slot_second,
                "interval_seconds": spec.interval_seconds,
            },
            identity={
                "canonical_symbol": spec.canonical_symbol,
                "interval": spec.interval,
            },
            spec=spec,
            extra={
                "finality_horizon_seconds": spec.finality_horizon_seconds,
                "revision_watch_seconds": spec.revision_watch_seconds,
            },
        )
    cg = settings.coinglass
    if cg is not None:
        for dataset in cg.datasets:
            identity: dict[str, Any] = {}
            cadence: dict[str, Any] = {
                "slot_minutes": list(cg.slot_minutes),
                "slot_second": cg.slot_second,
            }
            if dataset.expect is not None:
                identity = {
                    "exchange": dataset.expect.exchange,
                    "instrument": dataset.expect.instrument,
                }
                if dataset.expect.interval_seconds is not None:
                    cadence["interval_seconds"] = dataset.expect.interval_seconds
            if dataset.coins:
                identity["coins"] = list(dataset.coins)
            entries[dataset.id] = CatalogEntry(
                id=dataset.id,
                provider=PROVIDER_COINGLASS,
                kind=dataset.kind,
                max_age_seconds=cg.readiness.max_read_age_seconds,
                requires_login=dataset.requires_login,
                retention_days=None if retention is None else retention.coinglass_days,
                cadence=cadence,
                identity=identity,
            )
    return entries


__all__ = [
    "KIND_BARS",
    "PROVIDER_COINGLASS",
    "PROVIDER_TRADINGVIEW",
    "CatalogEntry",
    "build_catalog",
]
