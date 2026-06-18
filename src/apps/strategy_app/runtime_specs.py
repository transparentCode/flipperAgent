"""Helpers for resolving additive model runtime specs from config."""

from __future__ import annotations

from libs.contracts.model_runtime import resolve_model_runtime_spec

RUNTIME_KEY = "runtime"


__all__ = ["RUNTIME_KEY", "resolve_model_runtime_spec"]
