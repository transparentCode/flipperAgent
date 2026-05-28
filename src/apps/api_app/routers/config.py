"""Config API router — read all configs and apply partial updates to YAML files."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

router = APIRouter(prefix="/api/v1/configs", tags=["configs"])


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, Any]


class ConfigFileEntry(BaseModel):
    fileName: str
    filePath: str
    contents: dict[str, Any]


class AllConfigsResponse(BaseModel):
    configsMetaData: list[ConfigFileEntry]


@router.get(
    "",
    summary="Get all configs",
    response_model=AllConfigsResponse,
    description=(
        "Returns all loaded config files. Each entry contains "
        "'fileName' (use as the POST path param to update), "
        "'filePath' (absolute path on disk), and 'contents' (raw YAML structure)."
    ),
)
def get_all_configs() -> AllConfigsResponse:
    config_mgr = ConfigManager()
    return AllConfigsResponse(configsMetaData=config_mgr.get_all_file_states())


@router.post(
    "/{filename}",
    summary="Update a config file",
    description=(
        "Deep-merges *updates* into the specified YAML file on disk. "
        "The filename is the stem of the YAML file (e.g. 'base', 'features', 'models'). "
        "Only registered config files may be updated. "
        "All containers watching the shared config volume will reload automatically."
    ),
)
def update_config(
    filename: str = Path(
        ...,
        description="Filename stem of the YAML config to update (e.g. 'base', 'features').",
        pattern=r"^[a-zA-Z0-9_\-]+$",
    ),
    body: ConfigUpdateRequest = ...,
) -> dict[str, Any]:
    config_mgr = ConfigManager()
    try:
        config_mgr.update_yaml_file(filename, body.updates)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Failed to update config file '{filename}'", extra={"exception": str(exc)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to write config file.") from exc

    # Return the updated file state after reload
    updated = config_mgr.get_all_file_states().get(filename, {})
    return {"filename": filename, "updated": updated}
