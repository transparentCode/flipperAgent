"""Shared constants for the regression module.

Centralised here to prevent silent divergence from copy-paste definitions.
"""

# MAD → σ conversion factor: 1 / Φ⁻¹(0.75) ≈ 1.4826
# Under Gaussian assumptions, σ = MAD × MAD_GAUSSIAN_SCALE.
# Used by Theil-Sen, WLS, and PercentileBands for band normalisation.
MAD_GAUSSIAN_SCALE = 1.4826
