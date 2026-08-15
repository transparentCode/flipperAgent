from libs.models.momentum.config import MomentumConfig
from libs.models.momentum.core import (
    MomentumObservation,
    MomentumResult,
    evaluate_momentum,
)


def __getattr__(name: str) -> object:
    """Load legacy Momentum adapters only when their public names are used."""
    if name == "MomentumModel":
        from libs.models.momentum.model import MomentumModel

        globals()[name] = MomentumModel
        return MomentumModel
    if name == "MomentumV2":
        from libs.models.momentum.strategy_v2 import MomentumV2

        globals()[name] = MomentumV2
        return MomentumV2
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MomentumConfig",
    "MomentumModel",
    "MomentumObservation",
    "MomentumResult",
    "MomentumV2",
    "evaluate_momentum",
]
