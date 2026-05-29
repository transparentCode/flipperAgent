from .base import EnsembleStrategy, EnsembleRegistry

# Import plugins so @EnsembleRegistry.register decorators execute
from . import confidence_weighted, simple_weighted  # noqa: F401

__all__ = ["EnsembleStrategy", "EnsembleRegistry"]
