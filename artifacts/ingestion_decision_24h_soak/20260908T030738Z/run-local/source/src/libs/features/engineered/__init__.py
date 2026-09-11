"""Engineered features — composite features computed from raw indicator outputs."""

# Import features modules to trigger @register decorators
from libs.features.engineered import features as _features  # noqa: F401
from libs.features.engineered import cross_sectional as _cross_sectional  # noqa: F401
