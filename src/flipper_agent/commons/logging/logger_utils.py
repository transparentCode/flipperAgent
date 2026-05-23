"""Shared logging bootstrap and namespace helpers.

flipperAgent keeps logging configuration code-first in this module instead of a
separate logging.conf file so the shared runtime surface stays small and easy to
test.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from flipper_agent.commons.env import get_bool_env, get_env
from flipper_agent.commons.exceptions import LoggingConfigurationError
from flipper_agent.commons.paths import default_log_file
from flipper_agent.commons.typing import LogContext, PathLike


class SystemComponent(str, Enum):
    """Enumeration of known system components for standardized logging."""
    CORE_INFRASTRUCTURE = "CORE_INFRASTRUCTURE"
    DATA_INGESTION_ENGINE = "DATA_INGESTION_ENGINE"
    STRATEGY_ENGINE = "STRATEGY_ENGINE"
    SIGNAL_GENERATOR = "SIGNAL_GENERATOR"
    TRADE_EXECUTION = "TRADE_EXECUTION"
    MARKET_DATA = "MARKET_DATA"


DEFAULT_LOGGER_NAMESPACE: Final[str] = "flipper_agent"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOG_FILE_MAX_BYTES: Final[int] = 30 * 1024 * 1024  # 30 MB
DEFAULT_LOG_FILE_BACKUP_COUNT: Final[int] = 10  # Used as an absolute upper bound for size-based scaling
DEFAULT_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "trace_id",
    "run_id",
    "job_name",
    "system_component",
    "source",
    "dataset",
    "symbol",
    "interval",
    "window",
    "attempt",
)
_CONTEXT_FIELD_ALIASES: Final[dict[str, str]] = {
    "traceId": "trace_id",
    "systemComponent": "system_component",
    "component": "system_component",
}
_current_trace_id: ContextVar[str | None] = ContextVar("flipper_agent_trace_id", default=None)


def set_current_trace_id(trace_id: str | None) -> None:
    """Set the trace id for the current execution context."""

    _current_trace_id.set(trace_id)

def get_current_trace_id() -> str:
    """Return the trace id for the current execution context, generating one if needed."""
    trace_id = _current_trace_id.get()
    if not trace_id:
        trace_id = uuid.uuid4().hex
        _current_trace_id.set(trace_id)
    return trace_id


def clear_current_trace_id() -> None:
    """Clear the trace id for the current execution context."""

    _current_trace_id.set(None)


def _normalize_context(context: Mapping[str, object] | None) -> dict[str, object]:
    raw_context = {key: value for key, value in dict(context or {}).items() if value is not None}
    normalized_context = {
        key: value for key, value in raw_context.items() if key not in _CONTEXT_FIELD_ALIASES
    }

    for alias_key, canonical_key in _CONTEXT_FIELD_ALIASES.items():
        if canonical_key in normalized_context:
            continue

        alias_value = raw_context.get(alias_key)
        if alias_value not in (None, ""):
            normalized_context[canonical_key] = alias_value

    trace_id = normalized_context.get("trace_id")
    if trace_id in (None, ""):
        current_trace_id = get_current_trace_id()
        if current_trace_id not in (None, ""):
            normalized_context["trace_id"] = current_trace_id

    return normalized_context


class ContextLoggerAdapter(logging.LoggerAdapter):
    """Small adapter for binding stable context fields to a logger."""

    def process(self, msg: object, kwargs: dict[str, object]) -> tuple[object, dict[str, object]]:
        merged_extra = dict(self.extra)
        incoming_extra = kwargs.get("extra")
        if isinstance(incoming_extra, Mapping):
            merged_extra.update(incoming_extra)
        kwargs["extra"] = _normalize_context(merged_extra)
        return msg, kwargs

    def bind(self, **context: object) -> "ContextLoggerAdapter":
        merged_context = dict(self.extra)
        merged_context.update({key: value for key, value in context.items() if value is not None})
        return ContextLoggerAdapter(self.logger, _normalize_context(merged_context))


def _get_record_context_field(record: logging.LogRecord, field_name: str) -> object:
    record_value = getattr(record, field_name, None)
    if record_value not in (None, ""):
        return record_value

    for alias_key, canonical_key in _CONTEXT_FIELD_ALIASES.items():
        if canonical_key != field_name:
            continue

        alias_value = getattr(record, alias_key, None)
        if alias_value not in (None, ""):
            return alias_value

    if field_name == "trace_id":
        return get_current_trace_id()

    return None


class _LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context_parts: list[str] = []
        for field_name in DEFAULT_CONTEXT_FIELDS:
            field_value = _get_record_context_field(record, field_name)
            if field_value in (None, ""):
                continue

            setattr(record, field_name, field_value)
            context_parts.append(f"{field_name}={field_value}")

        record.context = f" | {' '.join(context_parts)}" if context_parts else ""
        return True


def _normalize_logger_name(name: str | None) -> str:
    if not name or name == DEFAULT_LOGGER_NAMESPACE:
        return DEFAULT_LOGGER_NAMESPACE
    if name.startswith(f"{DEFAULT_LOGGER_NAMESPACE}."):
        return name
    return f"{DEFAULT_LOGGER_NAMESPACE}.{name.lstrip('.')}"


def _normalize_log_level(level: int | str) -> int:
    if isinstance(level, int):
        return level

    normalized = level.strip().upper()
    resolved = logging.getLevelName(normalized)
    if isinstance(resolved, int):
        return resolved

    raise LoggingConfigurationError(f"Unsupported log level: {level}")


class ColorFormatter(logging.Formatter):
    """Console formatter with ANSI colors based on log level."""
    
    COLORS: Final[dict[int, str]] = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[1;31m" # Bold Red
    }
    RESET: Final[str] = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        formatted = super().format(record)
        return f"{color}{formatted}{self.RESET}"


class JsonFormatter(logging.Formatter):
    """JSON formatter that includes standard log record fields and context."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        for field in DEFAULT_CONTEXT_FIELDS:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)
                
        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)


def _build_formatter(format_type: str) -> logging.Formatter:
    base_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s%(context)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    
    if format_type == "json":
        return JsonFormatter(datefmt=date_fmt)
    elif format_type == "color":
        return ColorFormatter(fmt=base_fmt, datefmt=date_fmt)
    else:
        return logging.Formatter(fmt=base_fmt, datefmt=date_fmt)


def _build_console_handler(level: int, format_type: str) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(_build_formatter(format_type))
    handler.addFilter(_LogContextFilter())
    return handler


def _cleanup_old_logs(log_file: Path, max_age_days: int = 3) -> None:
    """Purge rotated log files older than max_age_days."""
    if not log_file.parent.exists():
        return
    
    current_time = time.time()
    max_age_seconds = max_age_days * 24 * 60 * 60
    
    # Check all files matching the log pattern (e.g. app.log, app.log.1, etc.)
    for path in log_file.parent.glob(log_file.name + "*"):
        if path.is_file():
            file_age = current_time - path.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    path.unlink()
                except OSError:
                    pass

def _build_file_handler(
    level: int,
    log_file: Path,
    format_type: str,
    *,
    file_max_bytes: int,
    file_backup_count: int,
) -> logging.Handler:
    handler = RotatingFileHandler(log_file, maxBytes=file_max_bytes, backupCount=file_backup_count)
    handler.setLevel(level)
    handler.setFormatter(_build_formatter(format_type))
    handler.addFilter(_LogContextFilter())
    return handler


def _validate_file_logging_settings(file_max_bytes: int, file_backup_count: int) -> None:
    if file_max_bytes < 1:
        raise LoggingConfigurationError("file_max_bytes must be a positive integer.")
    if file_backup_count < 0:
        raise LoggingConfigurationError("file_backup_count must be zero or greater.")


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_logging(
    *,
    level: int | str | None = None,
    enable_file_logging: bool | None = None,
    log_file: PathLike | None = None,
    file_max_bytes: int = DEFAULT_LOG_FILE_MAX_BYTES,
    file_backup_count: int = DEFAULT_LOG_FILE_BACKUP_COUNT,
    namespace: str = DEFAULT_LOGGER_NAMESPACE,
) -> logging.Logger:
    """Configure the shared namespace logger for console and optional file output."""

    resolved_level = _normalize_log_level(level or get_env("FLIPPER_AGENT_LOG_LEVEL", DEFAULT_LOG_LEVEL) or DEFAULT_LOG_LEVEL)
    console_format = get_env("FLIPPER_AGENT_CONSOLE_FORMAT", "color") or "color"
    file_format = get_env("FLIPPER_AGENT_FILE_FORMAT", "json") or "json"

    try:
        file_logging_enabled = (
            enable_file_logging
            if enable_file_logging is not None
            else get_bool_env("FLIPPER_AGENT_LOG_TO_FILE", default=False)
        )
    except ValueError as error:
        raise LoggingConfigurationError(str(error)) from error

    logger = logging.getLogger(namespace)
    logger.setLevel(resolved_level)
    logger.propagate = False
    _clear_handlers(logger)

    logger.addHandler(_build_console_handler(resolved_level, console_format))

    if file_logging_enabled:
        _validate_file_logging_settings(file_max_bytes, file_backup_count)
        resolved_log_file = Path(log_file) if log_file is not None else default_log_file(create_parent=True)
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_old_logs(resolved_log_file, max_age_days=3)
        logger.addHandler(
            _build_file_handler(
                resolved_level,
                resolved_log_file,
                file_format,
                file_max_bytes=file_max_bytes,
                file_backup_count=file_backup_count,
            )
        )

    return logger


def get_logger(name: str | None = None, *, context: LogContext | None = None) -> logging.Logger | ContextLoggerAdapter:
    logger = logging.getLogger(_normalize_logger_name(name))
    if context:
        return ContextLoggerAdapter(logger, _normalize_context(dict(context)))
    return logger


def bind_logger(
    logger: logging.Logger | ContextLoggerAdapter | str | None = None,
    **context: object,
) -> ContextLoggerAdapter:
    if isinstance(logger, ContextLoggerAdapter):
        return logger.bind(**context)

    base_logger = get_logger(logger) if isinstance(logger, str) or logger is None else logger
    return ContextLoggerAdapter(base_logger, _normalize_context(context))
