from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
ASSET_SOURCE = "./configs/ingestion/assets"
ASSET_TARGET = "/app/configs/ingestion/assets"
CONFIG_SOURCE = "./configs"
CONFIG_TARGET = "/app/configs"


def _mount_triplet(volume: Any) -> tuple[str, str, str | None]:
    if isinstance(volume, str):
        parts = volume.split(":")
        if len(parts) not in (2, 3):
            raise AssertionError(f"unsupported Compose short volume syntax: {volume!r}")
        source, target = parts[:2]
        mode = parts[2] if len(parts) == 3 else None
        return source, target, mode

    if isinstance(volume, dict):
        source = volume.get("source")
        target = volume.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise TypeError(f"invalid Compose long volume syntax: {volume!r}")
        mode = volume.get("mode")
        if mode is not None and not isinstance(mode, str):
            raise TypeError(f"invalid Compose volume mode: {volume!r}")
        if mode is None:
            if volume.get("read_only") is True:
                mode = "ro"
            elif volume.get("read_only") is False:
                mode = "rw"
        return source, target, mode

    raise TypeError(f"unsupported Compose volume entry: {volume!r}")


def _is_config_target(target: str) -> bool:
    return target == CONFIG_TARGET or target.startswith(f"{CONFIG_TARGET}/")


def test_ingestion_config_mount_is_narrow_and_structurally_writable() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    ingestion = compose["services"]["ingestion"]

    assert ingestion["read_only"] is True
    assert (REPOSITORY_ROOT / "configs/ingestion/assets").is_dir()

    config_mounts = [
        mount
        for mount in (_mount_triplet(volume) for volume in ingestion["volumes"])
        if _is_config_target(mount[1])
    ]

    assert config_mounts.count((CONFIG_SOURCE, CONFIG_TARGET, "ro")) == 1
    assert config_mounts.count((ASSET_SOURCE, ASSET_TARGET, "rw")) == 1

    assert [mount for mount in config_mounts if mount[1] == ASSET_TARGET] == [
        (ASSET_SOURCE, ASSET_TARGET, "rw")
    ]

    writable_targets = {target for _, target, mode in config_mounts if mode != "ro"}
    assert writable_targets == {ASSET_TARGET}

    for source, target, mode in config_mounts:
        if target != ASSET_TARGET:
            assert mode == "ro", (source, target, mode)
