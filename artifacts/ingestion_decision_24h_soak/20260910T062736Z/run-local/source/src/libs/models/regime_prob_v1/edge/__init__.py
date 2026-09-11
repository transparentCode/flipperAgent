"""Offline edge-label and calibration utilities for RegimeProbV1."""

from libs.models.regime_prob_v1.edge.calibration_report import (
    build_empirical_calibration_report,
    render_empirical_calibration_markdown,
)
from libs.models.regime_prob_v1.edge.empirical_calibrator import (
    EmpiricalCalibratorModel,
    PlaybookCalibrationResult,
    fit_empirical_calibrator,
    fit_playbook_empirical_calibrator,
)
from libs.models.regime_prob_v1.edge.labels import (
    PurgedFourWaySplit,
    PurgedFourWaySplitConfig,
    build_regime_prob_edge_labels,
    playbook_label_column,
    playbook_score_column,
)

__all__ = [
    "EmpiricalCalibratorModel",
    "PlaybookCalibrationResult",
    "PurgedFourWaySplit",
    "PurgedFourWaySplitConfig",
    "build_empirical_calibration_report",
    "build_regime_prob_edge_labels",
    "fit_empirical_calibrator",
    "fit_playbook_empirical_calibrator",
    "playbook_label_column",
    "playbook_score_column",
    "render_empirical_calibration_markdown",
]
