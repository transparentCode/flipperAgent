"""Explicit candidate selection contracts and policies."""

from .contracts import (
    CandidateSelectionDecision,
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    SelectionDiagnostics,
    SelectionStatus,
    candidate_set_identity,
)
from .latest_predecessor import select_latest_valid_predecessors

__all__ = [
    "CandidateSelectionDecision",
    "CandidateSelectionSnapshot",
    "LatestValidPredecessorPolicy",
    "SelectionDiagnostics",
    "SelectionStatus",
    "candidate_set_identity",
    "select_latest_valid_predecessors",
]
