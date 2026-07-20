"""Named, behavior-preserving configuration profiles. No filesystem access."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .contracts import TrendlineFamilyConfig


LEGACY_V1_PROFILE_ID = "legacy_v1"
LEGACY_V1_PROFILE_VERSION = "1"


def legacy_v1_profile() -> dict[str, Any]:
    """Return complete accepted implicit defaults as immutable-profile input."""

    config = TrendlineFamilyConfig()
    return {
        "profile_id": LEGACY_V1_PROFILE_ID,
        "profile_version": LEGACY_V1_PROFILE_VERSION,
        "version": LEGACY_V1_PROFILE_VERSION,
        "model": asdict(config.model),
        "defaults": {
            name: asdict(getattr(config, name))
            for name in (
                "candidate",
                "matching",
                "lifecycle",
                "interaction",
                "events",
                "rails",
                "mtf",
                "ranking",
                "repository",
                "runtime",
            )
        },
        "timeframes": {},
        "assets": {},
    }


__all__ = ["LEGACY_V1_PROFILE_ID", "LEGACY_V1_PROFILE_VERSION", "legacy_v1_profile"]
