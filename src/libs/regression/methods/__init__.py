from .base import RegressionMethod, MethodRegistry

# Import plugins so @MethodRegistry.register decorators execute
from . import theil_sen, wls  # noqa: F401

__all__ = ["RegressionMethod", "MethodRegistry"]
