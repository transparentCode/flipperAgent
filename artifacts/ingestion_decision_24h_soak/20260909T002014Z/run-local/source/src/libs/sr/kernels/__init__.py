"""
S/R v2 Kernels
==============
Stateless detection primitives for the kernel-ensemble pipeline.
"""

from importlib import import_module, reload

from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import KernelRegistry, register_kernel

_KERNEL_MODULES = (
    ("pivot_hl", "app.sr.kernels.pivot_hl"),
    ("volume_poc", "app.sr.kernels.volume_poc"),
    ("anchored_vwap", "app.sr.kernels.anchored_vwap"),
    ("tpo_value_area", "app.sr.kernels.tpo_value_area"),
    ("round_number", "app.sr.kernels.round_number"),
    ("order_block", "app.sr.kernels.order_block"),
    ("fair_value_gap", "app.sr.kernels.fair_value_gap"),
    ("session_gap", "app.sr.kernels.session_gap"),
    ("fractal_channel", "app.sr.kernels.fractal_channel"),
    ("regression_band", "app.sr.kernels.regression_band"),
    ("liquidity_sweep", "app.sr.kernels.liquidity_sweep"),
)


def ensure_kernel_registry_populated() -> None:
    """Import concrete kernel modules so decorator registrations run."""
    for kernel_name, module_name in _KERNEL_MODULES:
        if KernelRegistry.has(kernel_name):
            continue

        module = import_module(module_name)
        if not KernelRegistry.has(kernel_name):
            reload(module)

__all__ = [
    "BaseSRKernel",
    "KernelConfig",
    "KernelRegistry",
    "register_kernel",
    "ensure_kernel_registry_populated",
]
