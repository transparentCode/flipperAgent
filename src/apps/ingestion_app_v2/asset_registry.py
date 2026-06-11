"""Compatibility facade for the v2 control-plane slice."""

from apps.ingestion_app_v2.control_plane import (
    IngestionAssetCatalog,
    IngestionAssetRegistryRepository,
    IngestionControlPublisher,
    IngestionControlService,
)

__all__ = [
    "IngestionAssetCatalog",
    "IngestionAssetRegistryRepository",
    "IngestionControlPublisher",
    "IngestionControlService",
]

