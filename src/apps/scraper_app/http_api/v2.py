"""Read-only agent API under ``/v2``: catalog, bars and stored payloads.

Every route authenticates, validates, then makes its store calls through
``guarded`` (a small concurrency gate plus store-error mapping). Nothing writes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from apps.scraper_app.http_api.auth import TokenSource, make_auth_dependency
from apps.scraper_app.http_api.catalog import CatalogEntry
from apps.scraper_app.http_api.rules import (
    ORDERS,
    ApiError,
    bars_window,
    check_as_of,
    format_decimal,
    invalid,
    next_after_page,
    parse_choice,
    parse_flag,
    parse_int,
    parse_timestamp,
    resolve_bars_reference,
    settled,
    staleness,
    stamp,
)
from apps.scraper_app.settings import ApiSettings
from apps.scraper_app.storage.repository import ScraperRepository

BUSY_WAIT_SECONDS = 2.0
_DEADLINE_FACTOR = 8


@dataclass(slots=True)
class ApiDependencies:
    repository: ScraperRepository
    catalog: dict[str, CatalogEntry]
    settings: ApiSettings
    tokens: TokenSource
    disabled: Callable[[], frozenset[str]] = lambda: frozenset()
    gate: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.gate = asyncio.Semaphore(self.settings.pool_max_size)


async def guarded[T](deps: ApiDependencies, work: Callable[[], Awaitable[T]]) -> T:
    try:
        await asyncio.wait_for(deps.gate.acquire(), BUSY_WAIT_SECONDS)
    except TimeoutError:
        raise ApiError(503, "busy", "the read API is at capacity; retry") from None
    try:
        async with asyncio.timeout(
            deps.settings.query_timeout_seconds * _DEADLINE_FACTOR
        ):
            return await work()
    except (TimeoutError, asyncpg.QueryCanceledError):
        raise ApiError(
            503, "store_timeout", "the store did not answer in time"
        ) from None
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
        raise ApiError(503, "store_unavailable", "the store is unavailable") from None
    finally:
        deps.gate.release()


def json_response(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status)


def _entry(deps: ApiDependencies, dataset_id: str) -> CatalogEntry:
    entry = deps.catalog.get(dataset_id)
    if entry is None:
        raise ApiError(404, "unknown_dataset", f"unknown dataset {dataset_id!r}")
    return entry


def _bars_entry(deps: ApiDependencies, dataset_id: str) -> CatalogEntry:
    entry = _entry(deps, dataset_id)
    if not entry.is_bars:
        raise invalid(f"{dataset_id} is not a bar dataset", "wrong_kind")
    return entry


def _payload_entry(deps: ApiDependencies, dataset_id: str) -> CatalogEntry:
    entry = _entry(deps, dataset_id)
    if entry.is_bars:
        raise invalid(f"{dataset_id} is not a payload dataset", "wrong_kind")
    if entry.id in deps.disabled():
        raise ApiError(
            503,
            "dataset_disabled",
            f"{dataset_id} is disabled until cookies are present",
        )
    return entry


def _timestamp(request: Request, name: str) -> datetime | None:
    raw = request.query_params.get(name)
    return None if raw is None else parse_timestamp(name, raw)


def _raise_if_stale(
    entry: CatalogEntry, reference: datetime, finished_at: datetime | None, allow: bool
):
    result = staleness(reference, finished_at, entry.max_age_seconds)
    if result.stale and not allow:
        raise ApiError(
            503,
            "stale",
            f"{entry.id} has no recent enough successful read",
            age_seconds=result.age_seconds,
            max_age_seconds=entry.max_age_seconds,
            last_ok_read_at=stamp(finished_at),
        )
    return result


def build_v2_router(deps: ApiDependencies) -> APIRouter:
    router = APIRouter(
        prefix="/v2", dependencies=[Depends(make_auth_dependency(deps.tokens))]
    )
    cfg = deps.settings
    repo = deps.repository

    def limits() -> dict[str, int]:
        return {
            "default_limit": cfg.default_limit,
            "max_limit": cfg.max_limit,
            "max_payload_list": cfg.max_payload_list,
            "as_of_settle_seconds": cfg.as_of_settle_seconds,
        }

    async def describe(entry: CatalogEntry) -> dict[str, Any]:
        head = await repo.dataset_head(entry.id)
        latest = head.latest_ok_read
        out = entry.static_fields()
        out["disabled"] = entry.id in deps.disabled()
        out["vintage_available_from"] = stamp(head.first_ok_read_finished_at)
        out["last_ok_read_at"] = None if latest is None else stamp(latest.finished_at)
        if entry.is_bars:
            out["first"] = stamp(head.first_bar_open)
            out["last"] = stamp(head.last_bar_open)
            out["revisions_after_horizon"] = await repo.revisions_after_horizon(
                entry.id
            )
        else:
            out["first"] = stamp(head.first_ok_read_finished_at)
            out["last"] = None if latest is None else stamp(latest.finished_at)
        return out

    @router.get("/datasets")
    async def datasets() -> JSONResponse:
        async def work():
            return {
                "server_time": stamp(await repo.server_time()),
                "limits": limits(),
                "datasets": [await describe(e) for e in deps.catalog.values()],
            }

        return json_response(await guarded(deps, work))

    @router.get("/datasets/{dataset_id}")
    async def dataset(dataset_id: str) -> JSONResponse:
        entry = _entry(deps, dataset_id)

        async def work():
            return {
                "server_time": stamp(await repo.server_time()),
                "limits": limits(),
                **await describe(entry),
            }

        return json_response(await guarded(deps, work))

    @router.get("/datasets/{dataset_id}/bars")
    async def bars(dataset_id: str, request: Request) -> JSONResponse:
        entry = _bars_entry(deps, dataset_id)
        spec = entry.spec
        assert spec is not None
        q = request.query_params
        mode = parse_choice(
            "mode",
            q.get("mode"),
            default="final",
            choices=("final", "as_of", "current"),
        )
        as_of = _timestamp(request, "as_of")
        start, end = _timestamp(request, "start"), _timestamp(request, "end")
        limit = parse_int(
            "limit",
            q.get("limit"),
            default=cfg.default_limit,
            low=1,
            high=cfg.max_limit,
        )
        order = parse_choice("order", q.get("order"), default="desc", choices=ORDERS)
        allow_stale = parse_flag("allow_stale", q.get("allow_stale"))

        async def work():
            now = await repo.server_time()
            head = await repo.dataset_head(dataset_id)
            ref = resolve_bars_reference(
                mode,
                as_of,
                now=now,
                settle_seconds=cfg.as_of_settle_seconds,
                vintage=head.first_ok_read_finished_at,
            )
            window_start, window_end = bars_window(
                start,
                end,
                reference=ref.time,
                interval_seconds=spec.interval_seconds,
                max_limit=cfg.max_limit,
            )
            at_head = (
                head
                if ref.as_of is None
                else await repo.dataset_head(dataset_id, at=ref.as_of)
            )
            last = at_head.latest_ok_read
            result = _raise_if_stale(
                entry, ref.time, None if last is None else last.finished_at, allow_stale
            )
            rows = await repo.fetch_bars(
                dataset_id,
                mode="final" if ref.as_of is None else "as_of",
                as_of=ref.as_of,
                start=window_start,
                end=window_end,
                newest_first=order == "desc",
                limit=limit,
            )
            following = None
            if rows:
                nxt = next_after_page(
                    order=order,
                    count=len(rows),
                    limit=limit,
                    start=window_start,
                    end=window_end,
                    first_open=rows[0].bar_open,
                    last_open=rows[-1].bar_open,
                )
                if nxt is not None:
                    following = {
                        "mode": "final" if ref.as_of is None else "as_of",
                        "as_of": stamp(ref.as_of),
                        "start": stamp(nxt[0]),
                        "end": stamp(nxt[1]),
                        "order": order,
                        "limit": limit,
                    }
            return {
                "dataset_id": dataset_id,
                "mode": ref.mode,
                "as_of": stamp(ref.as_of),
                "order": order,
                "window": {"start": stamp(window_start), "end": stamp(window_end)},
                "server_time": stamp(now),
                "last_ok_read": None
                if last is None
                else {
                    "finished_at": stamp(last.finished_at),
                    "covered_from": stamp(last.covered_from),
                    "covered_to": stamp(last.covered_to),
                },
                "age_seconds": result.age_seconds,
                "stale": result.stale,
                "next": following,
                "bars": [
                    {
                        "bar_open": stamp(b.bar_open),
                        "bar_close": stamp(b.bar_close),
                        "open": format_decimal(b.open),
                        "high": format_decimal(b.high),
                        "low": format_decimal(b.low),
                        "close": format_decimal(b.close),
                        "volume": format_decimal(b.volume),
                        "finality": "final"
                        if (ref.as_of is None or b.is_final)
                        else "provisional",
                        "revision_count": b.revision_count,
                        "observed_at": stamp(b.observed_at),
                        "first_observed_at": stamp(b.first_observed_at),
                        "backfilled": b.backfilled,
                    }
                    for b in rows
                ],
            }

        return json_response(await guarded(deps, work))

    def payload_meta(record, now: datetime, entry: CatalogEntry) -> dict[str, Any]:
        return {
            "dataset_id": record.dataset_id,
            "observation_id": record.read_id,
            "observed_at": stamp(record.observed_at),
            "provider_time": stamp(record.provider_time),
            "content_hash": record.content_hash,
            "raw_bytes": record.raw_bytes,
        }

    def with_data(meta: dict[str, Any], text: str) -> Response:
        # The stored canonical text goes in verbatim: no float round trip.
        head = json.dumps(meta, separators=(",", ":"))
        body = head[:-1] + ',"data":' + text + "}"
        return Response(body, media_type="application/json")

    @router.get("/datasets/{dataset_id}/payload")
    async def payload(dataset_id: str, request: Request) -> Response:
        entry = _payload_entry(deps, dataset_id)
        as_of = _timestamp(request, "as_of")
        allow_stale = parse_flag("allow_stale", request.query_params.get("allow_stale"))

        async def work():
            now = await repo.server_time()
            head = await repo.dataset_head(dataset_id)
            if as_of is not None:
                check_as_of(
                    as_of,
                    now=now,
                    settle_seconds=cfg.as_of_settle_seconds,
                    vintage=head.first_ok_read_finished_at,
                )
            reference = as_of or settled(now, cfg.as_of_settle_seconds)
            at_head = await repo.dataset_head(dataset_id, at=reference)
            last = at_head.latest_ok_read
            result = _raise_if_stale(
                entry,
                reference,
                None if last is None else last.finished_at,
                allow_stale,
            )
            record = await repo.latest_payload(dataset_id, at=reference)
            if record is None:
                raise ApiError(
                    404,
                    "no_data",
                    "no payload at or before the reference",
                    as_of=stamp(reference),
                )
            meta = payload_meta(record, now, entry)
            meta.update(
                as_of=stamp(reference),
                server_time=stamp(now),
                vintage_available_from=stamp(head.first_ok_read_finished_at),
                age_seconds=result.age_seconds,
                stale=result.stale,
            )
            return with_data(meta, record.text())

        return await guarded(deps, work)

    @router.get("/datasets/{dataset_id}/payloads")
    async def payloads(dataset_id: str, request: Request) -> JSONResponse:
        _payload_entry(deps, dataset_id)
        q = request.query_params
        start, end = _timestamp(request, "start"), _timestamp(request, "end")
        limit = parse_int(
            "limit",
            q.get("limit"),
            default=min(cfg.default_limit, cfg.max_payload_list),
            low=1,
            high=cfg.max_payload_list,
        )

        async def work():
            now = await repo.server_time()
            latest = settled(now, cfg.as_of_settle_seconds)
            if end is not None and end > latest:
                raise invalid(
                    "end is later than now minus the settle interval",
                    "as_of_too_recent",
                    latest_as_of=stamp(latest),
                )
            window_end = latest if end is None else end
            if start is not None and start >= window_end:
                raise invalid("start must be earlier than end")
            rows = await repo.list_payloads(
                dataset_id, start=start, end=window_end, limit=limit
            )
            following = None
            if len(rows) == limit and (start is None or rows[-1].observed_at > start):
                following = {
                    "start": stamp(start),
                    "end": stamp(rows[-1].observed_at),
                    "limit": limit,
                }
            return {
                "dataset_id": dataset_id,
                "window": {"start": stamp(start), "end": stamp(window_end)},
                "server_time": stamp(now),
                "next": following,
                "payloads": [
                    {
                        "observation_id": r.read_id,
                        "observed_at": stamp(r.observed_at),
                        "provider_time": stamp(r.provider_time),
                        "content_hash": r.content_hash,
                        "raw_bytes": r.raw_bytes,
                    }
                    for r in rows
                ],
            }

        return json_response(await guarded(deps, work))

    @router.get("/datasets/{dataset_id}/payloads/{observation_id}")
    async def payload_by_id(dataset_id: str, observation_id: int) -> Response:
        entry = _payload_entry(deps, dataset_id)

        async def work():
            now = await repo.server_time()
            record = await repo.payload_by_id(dataset_id, observation_id)
            if record is None:
                raise ApiError(
                    404,
                    "unknown_observation",
                    f"no payload {observation_id} in {dataset_id}",
                )
            age = (now - record.observed_at).total_seconds()
            meta = payload_meta(record, now, entry)
            meta.update(
                server_time=stamp(now),
                age_seconds=age,
                stale=age > entry.max_age_seconds,
            )
            return with_data(meta, record.text())

        return await guarded(deps, work)

    return router


__all__ = ["ApiDependencies", "build_v2_router", "guarded"]
