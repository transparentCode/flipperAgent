"""Whole-payload datasets (CoinGlass): spec, gate, canonical form. Pure functions.

Everything the page returns is untrusted text. It is size-capped before it is
parsed, parsed with ``Decimal`` for non-integers (``NaN`` and ``Infinity`` are
rejected), gated, and stored in one canonical form: sorted keys, no
whitespace, numbers through ``canonical_decimal``. The content hash is the
SHA-256 of that text.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.bars import canonical_decimal
from apps.scraper_app.domain.errors import ScraperError

KIND_HEATMAP = "liq_heatmap"
KIND_MAX_PAIN = "max_pain"
KIND_LIQ_MAP = "liq_map"
PAYLOAD_FORMAT = "json+gzip;v1"

# Fixed projection applied in the page before a max pain payload crosses the
# socket (most of the 741 rows and many fields are never used).
MAX_PAIN_FIELDS = (
    "symbol",
    "price",
    "maxLongLiquidationPrice",
    "maxLongLiquidationLevel",
    "maxShortLiquidationPrice",
    "maxShortLiquidationLevel",
    "longRisk",
    "shortRisk",
    "longs",
    "shorts",
)

_HEATMAP_ROW_FIELDS = 6
_LIQ_MAP_ROW_FIELDS = 4
_MAX_EXPONENT = 1000
_MAX_DEPTH = 64
_MAX_COLUMN_LOOKBACK_SECONDS = 2 * 86400
_DETAIL_LIMIT = 200


@dataclass(frozen=True, slots=True)
class HeatmapExpect:
    exchange: str
    instrument: str
    # Heatmap only; a liq_map expects exchange and instrument alone.
    interval_seconds: int = 0
    columns: int = 0


@dataclass(frozen=True, slots=True)
class PayloadSpec:
    """One configured CoinGlass dataset."""

    id: str
    kind: str
    endpoint: str
    args: Mapping[str, Any] = field(default_factory=dict)
    requires_login: bool = False
    expect: HeatmapExpect | None = None
    coins: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcceptedPayload:
    """A payload that passed the gate, in canonical form."""

    text: str
    content_hash: str
    provider_time: datetime | None
    covered_from: datetime
    covered_to: datetime
    bars_seen: int
    holes: int = 0
    interval_seconds: int | None = None

    @property
    def raw_bytes(self) -> int:
        return len(self.text.encode("utf-8"))


def _bad(detail: str) -> ScraperError:
    return ScraperError(errors.PAYLOAD_INVALID, detail[:_DETAIL_LIMIT])


def _reject_constant(name: str) -> object:
    raise ScraperError(errors.PAYLOAD_INVALID, f"non-finite literal {name}")


def parse_payload_text(text: str, *, max_bytes: int) -> object:
    """Size cap first, then an exact parse (non-integers become ``Decimal``)."""
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _bad("payload is not valid text") from exc
    if size > max_bytes:
        raise ScraperError(
            errors.PAYLOAD_TOO_LARGE, f"{size} bytes exceeds {max_bytes}"
        )
    try:
        return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except ScraperError:
        raise
    except (ValueError, RecursionError) as exc:
        raise _bad(f"payload is not valid JSON: {type(exc).__name__}") from exc


def _number_text(value: int | Decimal) -> str:
    if isinstance(value, int):
        return str(value)
    if not value.is_finite() or abs(value.adjusted()) > _MAX_EXPONENT:
        raise _bad("number outside the accepted range")
    return canonical_decimal(value)


def canonical_json(value: object, _depth: int = 0) -> str:
    """Sorted keys, no whitespace, plain exponent-free numbers."""
    if _depth > _MAX_DEPTH:
        raise _bad("payload nesting too deep")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, Decimal)):
        return _number_text(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v, _depth + 1) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(k, ensure_ascii=True)
                + ":"
                + canonical_json(value[k], _depth + 1)
                for k in sorted(value)
            )
            + "}"
        )
    raise _bad(f"unsupported value type {type(value).__name__}")


def canonical_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encode_payload(text: str) -> bytes:
    """Deterministic gzip (``mtime=0``) of the canonical text."""
    return gzip.compress(text.encode("utf-8"), compresslevel=6, mtime=0)


def decode_payload(blob: bytes) -> str:
    return gzip.decompress(blob).decode("utf-8")


def _is_number(value: object) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _numeric(value: object) -> Decimal | None:
    """A number, or a string holding one; ``None`` when it is neither."""
    if _is_number(value):
        return Decimal(value)  # type: ignore[arg-type]
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    return None


def _check_envelope(envelope: object) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise _bad("payload is not an object")
    code = envelope.get("code")
    if str(code) == "0" and envelope.get("success") is True:
        return envelope
    detail = f"code={str(code)[:20]} msg={str(envelope.get('msg'))[:80]}"
    if str(code) == "40000":
        raise ScraperError(errors.NOT_AUTHORIZED, detail)
    raise ScraperError(errors.PROVIDER_REFUSED, detail)


def _ms_to_utc(ms: int) -> datetime:
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise _bad("updateTime out of range") from exc


def _s_to_utc(seconds: int) -> datetime:
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise _bad("column time out of range") from exc


def _gate_heatmap(
    spec: PayloadSpec,
    envelope: dict[str, Any],
    *,
    returned_at: datetime,
    max_age_seconds: float,
) -> tuple[datetime, datetime, datetime, int, int]:
    expect = spec.expect
    if expect is None:
        raise ValueError("heatmap spec without expectations")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise _bad("heatmap data is not an object")
    instrument = data.get("instrument")
    if not isinstance(instrument, dict) or (
        instrument.get("exName"),
        instrument.get("instrumentId"),
    ) != (expect.exchange, expect.instrument):
        raise ScraperError(
            errors.IDENTITY_MISMATCH,
            f"expected {expect.exchange}/{expect.instrument}",
        )
    prices, y, liq = data.get("prices"), data.get("y"), data.get("liq")
    if not isinstance(prices, list) or not prices:
        raise _bad("prices missing or empty")
    if len(prices) > expect.columns:
        raise _bad(f"{len(prices)} columns exceeds {expect.columns}")
    times: list[int] = []
    for row in prices:
        if not isinstance(row, list) or len(row) != _HEATMAP_ROW_FIELDS:
            raise _bad("price row is not six fields")
        if not _is_int(row[0]):
            raise _bad("price row time is not an integer")
        if any(_numeric(v) is None for v in row[1:]):
            raise _bad("price row has a non-numeric field")
        times.append(row[0])
    step = expect.interval_seconds
    if any(t % step for t in times):
        raise _bad("column time not aligned to the interval")
    if any(b <= a for a, b in pairwise(times)):
        raise _bad("column times not strictly ascending")
    holes = sum((b - a) // step - 1 for a, b in pairwise(times))

    if not isinstance(y, list) or not y:
        raise _bad("price grid y missing or empty")
    if not all(_is_number(v) for v in y):
        raise _bad("price grid y has a non-numeric value")
    if any(v <= 0 for v in y):
        raise ScraperError(errors.DOMAIN_VIOLATION, "price grid y not positive")
    if any(b <= a for a, b in pairwise(y)):
        raise _bad("price grid y not strictly ascending")

    if not isinstance(liq, list):
        raise _bad("liq missing")
    columns, levels = len(prices), len(y)
    for cell in liq:
        if not isinstance(cell, list) or len(cell) != 3:
            raise _bad("liq cell is not a triple")
        x, level, value = cell
        if not (_is_int(x) and _is_int(level)):
            raise _bad("liq index is not an integer")
        if not (0 <= x < columns and 0 <= level < levels):
            raise _bad("liq index out of range")
        if not _is_number(value):
            raise _bad("liq value is not a number")
        if value < 0:
            raise ScraperError(errors.DOMAIN_VIOLATION, "negative liq value")

    update = data.get("updateTime")
    if not _is_int(update):
        raise _bad("updateTime missing")
    provider_time = _ms_to_utc(update)
    age = (returned_at - provider_time).total_seconds()
    if age > max_age_seconds:
        raise ScraperError(
            errors.STALE_PAYLOAD,
            f"updateTime is {age:.0f}s old (max {max_age_seconds:g})",
        )
    if -age > max_age_seconds:
        raise _bad(f"updateTime is {-age:.0f}s ahead of the local clock")
    update_s = update // 1000
    if (
        times[0] < update_s - _MAX_COLUMN_LOOKBACK_SECONDS
        or times[-1] > update_s + step
    ):
        raise _bad("column times outside the provider update window")
    return (
        provider_time,
        _s_to_utc(times[0]),
        _s_to_utc(times[-1]),
        len(times),
        holes,
    )


def _gate_max_pain(spec: PayloadSpec, envelope: dict[str, Any]) -> int:
    data = envelope.get("data")
    if not isinstance(data, list):
        raise _bad("max pain data is not a list")
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in data:
        if isinstance(row, dict) and isinstance(row.get("symbol"), str):
            by_symbol.setdefault(row["symbol"], []).append(row)
    kept: list[dict[str, Any]] = []
    for coin in spec.coins:
        rows = by_symbol.get(coin, [])
        if not rows:
            raise ScraperError(errors.COIN_MISSING, f"{coin} not in the payload")
        if len(rows) > 1:
            raise _bad(f"{coin} present {len(rows)} times")
        row = rows[0]
        price = row.get("price")
        if not _is_number(price):
            raise _bad(f"{coin} price is not a number")
        if price <= 0:
            raise ScraperError(errors.DOMAIN_VIOLATION, f"{coin} price not positive")
        kept.append(row)
    envelope["data"] = kept
    return len(kept)


def _check_instrument(expect: HeatmapExpect, data: dict[str, Any]) -> None:
    instrument = data.get("instrument")
    if not isinstance(instrument, dict) or (
        instrument.get("exName"),
        instrument.get("instrumentId"),
    ) != (expect.exchange, expect.instrument):
        raise ScraperError(
            errors.IDENTITY_MISMATCH,
            f"expected {expect.exchange}/{expect.instrument}",
        )


def _gate_liq_map(spec: PayloadSpec, envelope: dict[str, Any]) -> int:
    """Current-state liquidation levels: ``{instrument, lastPrice, liqMapV2}``."""
    if spec.expect is None:
        raise ValueError("liq_map spec without expectations")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise _bad("liq map data is not an object")
    _check_instrument(spec.expect, data)
    last = data.get("lastPrice")
    if not _is_number(last):
        raise _bad("lastPrice is not a number")
    if last <= 0:
        raise ScraperError(errors.DOMAIN_VIOLATION, "lastPrice not positive")
    levels = data.get("liqMapV2")
    if not isinstance(levels, dict) or not levels:
        raise _bad("liqMapV2 missing or empty")
    for key, rows in levels.items():
        try:
            bucket = Decimal(key)
        except InvalidOperation:
            raise _bad("liqMapV2 key is not a number") from None
        if not bucket.is_finite():
            raise _bad("liqMapV2 key is not finite")
        if bucket <= 0:
            raise ScraperError(errors.DOMAIN_VIOLATION, "liqMapV2 key not positive")
        if not isinstance(rows, list) or not rows:
            raise _bad("liqMapV2 bucket has no rows")
        for row in rows:
            if not isinstance(row, list) or len(row) != _LIQ_MAP_ROW_FIELDS:
                raise _bad("liqMapV2 row is not four fields")
            price, value, leverage, tier = row
            if not (_is_number(price) and _is_number(value)):
                raise _bad("liqMapV2 price or value is not a number")
            if price <= 0:
                raise ScraperError(errors.DOMAIN_VIOLATION, "row price not positive")
            if value < 0:
                raise ScraperError(errors.DOMAIN_VIOLATION, "negative row value")
            if not _is_int(leverage) or leverage <= 0:
                raise _bad("leverage is not a positive integer")
            if not isinstance(tier, str) or not tier:
                raise _bad("tier is not a non-empty string")
    return len(levels)


def gate_payload(
    spec: PayloadSpec,
    text: str,
    *,
    returned_at: datetime,
    max_payload_bytes: int,
    max_age_seconds: float,
) -> AcceptedPayload:
    """Parse, gate and canonicalise one payload, or raise ``ScraperError``."""
    envelope = _check_envelope(parse_payload_text(text, max_bytes=max_payload_bytes))
    if spec.kind == KIND_HEATMAP:
        provider_time, first, last, columns, holes = _gate_heatmap(
            spec, envelope, returned_at=returned_at, max_age_seconds=max_age_seconds
        )
        canonical = canonical_json(envelope)
        return AcceptedPayload(
            text=canonical,
            content_hash=canonical_hash(canonical),
            provider_time=provider_time,
            covered_from=first,
            covered_to=last,
            bars_seen=columns,
            holes=holes,
            interval_seconds=spec.expect.interval_seconds if spec.expect else None,
        )
    if spec.kind == KIND_MAX_PAIN:
        count = _gate_max_pain(spec, envelope)
        canonical = canonical_json(envelope)
        return AcceptedPayload(
            text=canonical,
            content_hash=canonical_hash(canonical),
            provider_time=None,
            covered_from=returned_at,
            covered_to=returned_at,
            bars_seen=count,
        )
    if spec.kind == KIND_LIQ_MAP:
        buckets = _gate_liq_map(spec, envelope)
        canonical = canonical_json(envelope)
        return AcceptedPayload(
            text=canonical,
            content_hash=canonical_hash(canonical),
            provider_time=None,
            covered_from=returned_at,
            covered_to=returned_at,
            bars_seen=buckets,
        )
    raise ValueError(f"unknown payload kind: {spec.kind!r}")


__all__ = [
    "KIND_HEATMAP",
    "KIND_LIQ_MAP",
    "KIND_MAX_PAIN",
    "MAX_PAIN_FIELDS",
    "PAYLOAD_FORMAT",
    "AcceptedPayload",
    "HeatmapExpect",
    "PayloadSpec",
    "canonical_hash",
    "canonical_json",
    "decode_payload",
    "encode_payload",
    "gate_payload",
    "parse_payload_text",
]
