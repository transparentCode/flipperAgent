# Ensure all concrete models are imported so they self-register.
import libs.models.mean_reversion  # noqa: F401
import libs.models.trend_following  # noqa: F401
import libs.models.momentum  # noqa: F401
import libs.models.squeeze_breakout  # noqa: F401
import libs.models.regime_pullback  # noqa: F401
import libs.models.divergence_edge  # noqa: F401
import libs.models.regime_relative_value  # noqa: F401
