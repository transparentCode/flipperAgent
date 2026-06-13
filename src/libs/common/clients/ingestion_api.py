from __future__ import annotations

from typing import Any

import aiohttp

from apps.scraper_app.core.models import ScrapeJobRecord, ScrapeRequest, ScrapeResult
from libs.common.config import ConfigManager


class IngestionApiClientError(RuntimeError):
    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def build_ingestion_api_base_url(config_manager: ConfigManager) -> str:
    configured_base_url = config_manager.get("api.base_url", None)
    if configured_base_url:
        return str(configured_base_url).rstrip("/")

    host = str(config_manager.get("api.host", "127.0.0.1")).strip()
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = int(config_manager.get("api.port", 8080))
    return f"http://{host}:{port}"


class IngestionApiClient:
    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.base_url = base_url or build_ingestion_api_base_url(self.config_manager)
        self.timeout_seconds = int(
            timeout_seconds or self.config_manager.get("api.timeout_seconds", 30)
        )

    async def scraper_fetch(self, request: ScrapeRequest) -> ScrapeResult:
        payload = await self._request_json(
            "POST",
            "/ingestion/scraper/fetch",
            json_payload=request.model_dump(mode="json"),
        )
        return ScrapeResult.model_validate(payload)

    async def create_scraper_job(self, request: ScrapeRequest) -> ScrapeJobRecord:
        payload = await self._request_json(
            "POST",
            "/ingestion/scraper/jobs",
            json_payload=request.model_dump(mode="json"),
        )
        return ScrapeJobRecord.model_validate(payload)

    async def get_scraper_job(
        self,
        job_id: str,
        *,
        include_result: bool = True,
    ) -> ScrapeJobRecord:
        payload = await self._request_json(
            "GET",
            f"/ingestion/scraper/jobs/{job_id}",
            params={"include_result": str(include_result).lower()},
        )
        return ScrapeJobRecord.model_validate(payload)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json_payload,
                ) as response:
                    try:
                        payload = await response.json(content_type=None)
                    except Exception:
                        payload = {}

                    if response.status >= 400:
                        detail = payload.get("detail") if isinstance(payload, dict) else None
                        raise IngestionApiClientError(
                            status_code=response.status,
                            detail=str(detail or response.reason or "Ingestion API request failed."),
                        )

                    if not isinstance(payload, dict):
                        raise IngestionApiClientError(
                            status_code=502,
                            detail="Ingestion API returned an unexpected response payload.",
                        )
                    return payload
        except IngestionApiClientError:
            raise
        except TimeoutError as exc:
            raise IngestionApiClientError(
                status_code=504,
                detail="Ingestion API request timed out.",
            ) from exc
        except aiohttp.ClientError as exc:
            raise IngestionApiClientError(
                status_code=502,
                detail="Ingestion API unavailable.",
            ) from exc
