"""
S/R v2 Regime Gate
==================
Central regime availability / stability checker.

The entire S/R pipeline goes through ``RegimeGate`` to access regime
labels — no component accesses the regime provider directly.  When
the gate returns ``None``, all consumers fall back to regime-agnostic
behaviour (see §2G).

Usage::

    gate = RegimeGate(provider=my_regime_source, config=regime_config)

    regime = gate.get_regime_or_none("BTCUSDT", "1h")
    if regime is not None:
        # use regime-conditional logic
    else:
        # fully functional fallback — no regime dependency
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regime provider protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class RegimeProvider(Protocol):
    """
    Protocol for regime label sources.

    Any implementation accepted — the S/R module does not depend on
    the concrete regime module.  Returning ``None`` from
    ``get_regime`` triggers fallback behaviour in all consumers.
    """

    def get_regime(self, asset: str, timeframe: str) -> Optional[str]:
        """Return current regime state string, or None if unavailable."""
        ...

    def get_regime_confidence(self, asset: str, timeframe: str) -> float:
        """Return confidence in current label [0, 1]."""
        ...


# ---------------------------------------------------------------------------
# Regime gate
# ---------------------------------------------------------------------------

class RegimeGate:
    """
    Central gate deciding whether to use regime labels or fall back.

    Checks:
    1. Provider is configured (is_available)
    2. Confidence >= min_confidence
    3. Label entropy over trailing window <= max_entropy

    All thresholds come from the ``sr.regime`` config section.
    """

    def __init__(
        self,
        provider: Optional[RegimeProvider] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._provider = provider
        cfg = config or {}
        self._min_confidence: float = cfg.get("min_confidence", 0.5)
        self._max_entropy: float = cfg.get("max_entropy", 1.2)
        self._stability_window: int = cfg.get("stability_window_bars", 50)
        self._ema_alpha: float = cfg.get("confidence_ema_alpha", 0.2)
        self._fallback_state: Optional[str] = cfg.get("fallback_state", None)

        # Per (asset, tf) label history for entropy estimation
        self._label_history: Dict[str, deque] = {}
        # Per (asset, tf) smoothed confidence
        self._confidence_ema: Dict[str, float] = {}
        # Cap tracked (asset, tf) combos to prevent unbounded growth
        self._max_tracked_keys: int = cfg.get("max_tracked_keys", 500)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """Whether a regime provider is configured at all."""
        return self._provider is not None

    def get_regime_or_none(
        self, asset: str, timeframe: str,
    ) -> Optional[str]:
        """
        Return regime state only if all stability checks pass.

        Returns ``fallback_state`` (default None) otherwise, triggering fallback.
        """
        if self._provider is None:
            logger.debug("Regime provider unavailable; using fallback state %s", self._fallback_state)
            return self._fallback_state

        confidence = self._get_smoothed_confidence(asset, timeframe)
        if confidence < self._min_confidence:
            logger.debug(
                "Regime gated (smoothed confidence %.2f < %.2f) for %s/%s",
                confidence, self._min_confidence, asset, timeframe,
            )
            return self._fallback_state

        state = self._provider.get_regime(asset, timeframe)
        if state is None:
            return self._fallback_state

        # Track label and check entropy
        history_key = f"{asset}:{timeframe}"
        self._record_label(history_key, state)

        entropy = self._label_entropy(history_key)
        if entropy > self._max_entropy:
            logger.debug(
                "Regime gated (high entropy %.2f > %.2f) for %s/%s",
                entropy, self._max_entropy, asset, timeframe,
            )
            return self._fallback_state

        debounced_state = self._get_debounced_label(history_key)
        return debounced_state if debounced_state is not None else state

    def get_confidence(self, asset: str, timeframe: str) -> float:
        """Return smoothed regime confidence, or 0.0 if provider is absent."""
        return self._get_smoothed_confidence(asset, timeframe)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_smoothed_confidence(self, asset: str, timeframe: str) -> float:
        if self._provider is None:
            return 0.0
            
        raw_conf = self._provider.get_regime_confidence(asset, timeframe)
        key = f"{asset}:{timeframe}"
        
        if key not in self._confidence_ema:
            self._confidence_ema[key] = raw_conf
        else:
            self._confidence_ema[key] = (self._ema_alpha * raw_conf) + ((1 - self._ema_alpha) * self._confidence_ema[key])
            
        return self._confidence_ema[key]

    def _record_label(self, key: str, label: str) -> None:
        """Append label to rolling history window."""
        if key not in self._label_history:
            # Evict oldest tracked key if at capacity
            if len(self._label_history) >= self._max_tracked_keys:
                oldest_key = next(iter(self._label_history))
                del self._label_history[oldest_key]
                self._confidence_ema.pop(oldest_key, None)
            self._label_history[key] = deque(maxlen=self._stability_window)
        self._label_history[key].append(label)

    def _get_debounced_label(self, key: str) -> Optional[str]:
        """Return the most frequent label in the rolling window."""
        history = self._label_history.get(key)
        if not history:
            return None
            
        counts: Dict[str, int] = {}
        for label in history:
            counts[label] = counts.get(label, 0) + 1
            
        return max(counts.items(), key=lambda x: x[1])[0]

    def _label_entropy(self, key: str) -> float:
        """
        Shannon entropy of label distribution over the trailing window.

        Lower entropy = more stable labels = more trustworthy regime.
        """
        history = self._label_history.get(key)
        if not history or len(history) < 2:
            return 0.0

        n = len(history)
        counts: Dict[str, int] = {}
        for label in history:
            counts[label] = counts.get(label, 0) + 1

        entropy = 0.0
        for count in counts.values():
            p = count / n
            if p > 0:
                entropy -= p * math.log2(p)

        return entropy
