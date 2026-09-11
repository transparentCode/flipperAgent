"""
Aggregation Module
==================
Feature aggregation strategies for combining regime signals.
"""

from .base import BaseAggregator
from .rule_based import FeatureAggregator, AggregatorConfig

__all__ = ['BaseAggregator', 'FeatureAggregator', 'AggregatorConfig']
