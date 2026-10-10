"""The in-page lookup of the site's own request helper, and its result types.

The helper is found by the *source text* of module factories: modules whose
factory contains the endpoint followed by a quote; exactly one must match, and
exactly one function export of it. Anything else fails closed. The page returns
``JSON.stringify(payload)`` so numbers are parsed exactly on our side.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.domain.payloads import KIND_MAX_PAIN, MAX_PAIN_FIELDS, PayloadSpec

_LOOKUP_JS = r"""
(async (p) => {
  const store = globalThis.webpackChunk_N_E;
  if (!Array.isArray(store)) return {error: "no_chunk_store"};
  let req; store.push([["probe-" + Math.random()], {}, (r) => { req = r; }]);
  if (!req || !req.m) return {error: "no_registry"};
  const src = (f) => { try { return Function.prototype.toString.call(f); } catch { return ""; } };
  const has = (s) => ['"', "'", "`"].some((q) => s.includes(p.endpoint + q));
  const ids = Object.keys(req.m).filter((id) => has(src(req.m[id])));
  if (ids.length !== 1) return {error: "module_count", count: ids.length};
  let exp; try { exp = req(ids[0]); } catch (e) { return {error: "module_load"}; }
  const hits = Object.entries(exp).filter(([n, f]) => typeof f === "function" && has(src(f)));
  if (hits.length !== 1) return {error: "export_count", count: hits.length};
  const [name, helper] = hits[0];
  const timer = new Promise((_, rej) => setTimeout(() => rej(new Error("helper_timeout")), p.timeoutMs));
  let payload;
  try { payload = await Promise.race([helper(p.args), timer]); }
  catch (e) { return {error: String((e && e.message) || e).slice(0, 120), module: ids[0], export: name}; }
  if (p.project && payload && Array.isArray(payload.data)) {
    payload = Object.assign({}, payload, {data: payload.data
      .filter((r) => p.project.coins.includes(r.symbol))
      .map((r) => Object.fromEntries(p.project.fields.filter((k) => k in r).map((k) => [k, r[k]])))});
  }
  const text = JSON.stringify(payload);
  const meta = {module: ids[0], export: name, sourceLength: src(helper).length};
  if (typeof text !== "string") return Object.assign({error: "payload_undefined"}, meta);
  if (text.length > p.maxChars) return Object.assign({error: "payload_too_large", length: text.length}, meta);
  return Object.assign({text}, meta);
})(__PARAMS__)
"""

READY_JS = (
    "Array.isArray(globalThis.webpackChunk_N_E) && document.readyState === 'complete'"
)

_MISSING = {
    "no_chunk_store",
    "no_registry",
    "module_count",
    "export_count",
    "module_load",
}


@dataclass(frozen=True, slots=True)
class HelperRequest:
    dataset_id: str
    endpoint: str
    args: Mapping[str, Any]
    coins: tuple[str, ...] = ()
    project: bool = False

    @classmethod
    def for_spec(cls, spec: PayloadSpec) -> HelperRequest:
        return cls(
            dataset_id=spec.id,
            endpoint=spec.endpoint,
            args=spec.args,
            coins=spec.coins,
            project=spec.kind == KIND_MAX_PAIN,
        )


@dataclass(frozen=True, slots=True)
class HelperResult:
    text: str
    module: str
    export: str
    source_length: int
    returned_at: datetime

    def meta(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "export": self.export,
            "source_length": self.source_length,
            "payload_bytes": len(self.text.encode("utf-8", "replace")),
        }


class HelperError(ScraperError):
    """A helper call failed; ``meta`` holds what is known about the helper."""

    def __init__(
        self, code: str, detail: str, meta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(code, detail)
        self.meta = meta or {}


def build_expression(
    request: HelperRequest, *, timeout_seconds: float, max_chars: int
) -> str:
    params: dict[str, Any] = {
        "endpoint": request.endpoint,
        "args": dict(request.args),
        "timeoutMs": int(timeout_seconds * 1000),
        "maxChars": max_chars,
        "project": (
            {"coins": list(request.coins), "fields": list(MAX_PAIN_FIELDS)}
            if request.project
            else None
        ),
    }
    return _LOOKUP_JS.replace("__PARAMS__", json.dumps(params, ensure_ascii=True))


def _source_length(value: object) -> int | None:
    """Page-supplied; kept only when it is a plain integer."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def interpret_result(value: object, *, returned_at: datetime) -> HelperResult:
    """Turn the page's answer into a result or a typed error."""
    if not isinstance(value, dict):
        raise ScraperError(errors.ENGINE_ERROR, "the page returned no object")
    meta = {
        "module": str(value.get("module", ""))[:40],
        "export": str(value.get("export", ""))[:40],
        "source_length": _source_length(value.get("sourceLength")),
    }
    meta = {k: v for k, v in meta.items() if v not in ("", None)}
    error = value.get("error")
    if error is not None:
        label = str(error)
        if label in _MISSING:
            raise HelperError(errors.HELPER_MISSING, label, meta)
        if label == "helper_timeout":
            raise HelperError(errors.HELPER_TIMEOUT, "in-page timer expired", meta)
        if label == "payload_too_large":
            raise HelperError(
                errors.PAYLOAD_TOO_LARGE, f"{value.get('length')} chars", meta
            )
        if label == "payload_undefined":
            raise HelperError(errors.PAYLOAD_INVALID, "helper returned nothing", meta)
        raise HelperError(errors.ENGINE_ERROR, f"helper raised: {label[:100]}", meta)
    text = value.get("text")
    if not isinstance(text, str):
        raise HelperError(errors.ENGINE_ERROR, "helper result has no text", meta)
    length = _source_length(value.get("sourceLength"))
    return HelperResult(
        text=text,
        module=str(value.get("module", ""))[:40],
        export=str(value.get("export", ""))[:40],
        source_length=length or 0,
        returned_at=returned_at,
    )


__all__ = [
    "READY_JS",
    "HelperError",
    "HelperRequest",
    "HelperResult",
    "build_expression",
    "interpret_result",
]
