"""KernelSpec dataclass and KERNEL_REGISTRY for price-action kernels."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KernelSpec:
    """Declarative metadata for a single price-action kernel."""

    name: str
    weight_key: str  # maps to hyperparameter schema key, e.g. "w_fvg"
    category: str  # "reversal" | "continuation" | "institutional"
    needs_swings: bool  # True if kernel uses swing high/low state
    param_keys: tuple[str, ...]  # hyperparameter keys this kernel uses


KERNEL_REGISTRY: dict[str, KernelSpec] = {}


def register_kernel(spec: KernelSpec) -> None:
    """Register a kernel. Called at module import time."""
    KERNEL_REGISTRY[spec.name] = spec
