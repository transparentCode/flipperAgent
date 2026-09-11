"""Shared lifecycle command vocabulary retained by ingestion."""

from __future__ import annotations

from enum import Enum


class IngestionCommandType(str, Enum):
    UPSERT_ASSET = "UPSERT_ASSET"
    UPDATE_ASSET = "UPDATE_ASSET"
    PAUSE_ASSET = "PAUSE_ASSET"
    STOP_ASSET = "STOP_ASSET"
    RESUME_ASSET = "RESUME_ASSET"
    REMOVE_ASSET = "REMOVE_ASSET"


__all__ = [
    "IngestionCommandType",
]
