from __future__ import annotations

import io
import logging
import tempfile
import unittest
from pathlib import Path

from libs.common.telemetry.bootstrap import (
    _OTEL_INTERNAL_LOGGER_NAMES,
    _configure_otel_internal_logging,
)


class TelemetryBootstrapTests(unittest.TestCase):
    def tearDown(self) -> None:
        _configure_otel_internal_logging({"enabled": False})
        for logger_name in _OTEL_INTERNAL_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            logger.propagate = True
            logger.setLevel(logging.NOTSET)

    def test_otel_internal_logs_are_routed_to_dedicated_file(self) -> None:
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        original_level = root_logger.level
        root_stream = io.StringIO()
        root_handler = logging.StreamHandler(root_stream)
        root_logger.handlers = [root_handler]
        root_logger.setLevel(logging.WARNING)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                log_file = Path(temp_dir) / "otel-internal.log"
                _configure_otel_internal_logging(
                    {
                        "enabled": True,
                        "file": str(log_file),
                        "level": "WARNING",
                    }
                )

                logging.getLogger("opentelemetry.exporter.otlp.proto.grpc.exporter").warning(
                    "collector unavailable"
                )

                self.assertEqual(root_stream.getvalue(), "")
                self.assertTrue(log_file.exists())
                self.assertIn("collector unavailable", log_file.read_text())
        finally:
            root_logger.handlers = original_handlers
            root_logger.setLevel(original_level)

    def test_otel_internal_log_routing_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "otel-internal.log"
            _configure_otel_internal_logging(
                {
                    "enabled": True,
                    "file": str(log_file),
                }
            )
            _configure_otel_internal_logging({"enabled": False})

            logger = logging.getLogger("opentelemetry")
            self.assertTrue(logger.propagate)
            self.assertFalse(
                any(getattr(handler, "_flipper_otel_internal", False) for handler in logger.handlers)
            )

