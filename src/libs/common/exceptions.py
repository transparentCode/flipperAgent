"""Shared exception types for flipperAgent."""

from typing import Any


class FlipperAgentError(Exception):
    """Base exception for flipperAgent."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}
        from libs.common.logging.logger_utils import get_current_trace_id
        self.trace_id = get_current_trace_id()

    def __str__(self) -> str:
        return f"{self.message} (Trace ID: {self.trace_id})"


class ConfigurationError(FlipperAgentError):
    """Raised when shared runtime configuration is invalid."""


class LoggingConfigurationError(ConfigurationError):
    """Raised when process logging cannot be configured."""


class DataIngestionError(FlipperAgentError):
    """Raised when data ingestion engine fails to fetch or process market data."""


class DatabaseError(FlipperAgentError):
    """Raised when database interactions fail."""


class RetryableNetworkError(FlipperAgentError):
    """Raised when a network operation fails but may succeed upon retry."""


class StrategyExecutionError(FlipperAgentError):
    """Raised when a trading strategy encounters an execution error."""
