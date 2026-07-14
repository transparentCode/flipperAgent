"""
S/R v2 Ensemble — Package init.
"""

from app.sr.ensemble.base import BaseEnsembleStrategy
from app.sr.ensemble.registry import EnsembleRegistry, register_ensemble

__all__ = ["BaseEnsembleStrategy", "EnsembleRegistry", "register_ensemble"]
