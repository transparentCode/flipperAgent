"""SR-V1.11 lifecycle resolution utility."""

from .config import LifecycleUtilityConfig, load_lifecycle_utility_config
from .contracts import (
    LifecycleUtilityDisposition,
    LifecycleUtilityStudy,
    ResolutionEvent,
    ResolutionOutcome,
)
from .runner import compute_study, run_study

__all__ = [
    "LifecycleUtilityConfig", "LifecycleUtilityDisposition", "LifecycleUtilityStudy",
    "ResolutionEvent", "ResolutionOutcome", "compute_study", "load_lifecycle_utility_config",
    "run_study",
]
