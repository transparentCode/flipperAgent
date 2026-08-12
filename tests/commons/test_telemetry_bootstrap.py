from __future__ import annotations

import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from libs.common.telemetry import bootstrap
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

                logging.getLogger(
                    "opentelemetry.exporter.otlp.proto.grpc.exporter"
                ).warning("collector unavailable")

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
                any(
                    getattr(handler, "_flipper_otel_internal", False)
                    for handler in logger.handlers
                )
            )

    def test_shutdown_detaches_handlers_unregisters_atexit_and_is_idempotent(
        self,
    ) -> None:
        trace_provider = MagicMock()
        meter_provider = MagicMock()
        logger_provider = MagicMock()
        log_handler = MagicMock()
        log_handler._logger_provider = logger_provider
        namespace_logger = logging.getLogger("telemetry-test")
        namespace_logger.addHandler(log_handler)
        fake_thread = MagicMock()
        trace_atexit = trace_provider._atexit_handler
        meter_atexit = meter_provider._atexit_handler
        logger_atexit = logger_provider._at_exit_handler

        bootstrap._otel_log_handler = log_handler
        bootstrap._telemetry_shutdown_started = False
        try:
            with (
                patch.object(
                    bootstrap.trace,
                    "get_tracer_provider",
                    return_value=trace_provider,
                ),
                patch.object(
                    bootstrap.metrics,
                    "get_meter_provider",
                    return_value=meter_provider,
                ),
                patch.object(bootstrap.atexit, "unregister") as unregister,
                patch.object(
                    bootstrap.threading,
                    "Thread",
                    return_value=fake_thread,
                ) as thread_factory,
            ):
                bootstrap.shutdown_telemetry_nonblocking("telemetry-test")
                bootstrap.shutdown_telemetry_nonblocking("telemetry-test")

            namespace_logger.removeHandler(log_handler)
            log_handler.close.assert_called_once()
            unregister.assert_any_call(trace_atexit)
            unregister.assert_any_call(meter_atexit)
            unregister.assert_any_call(logger_atexit)
            fake_thread.start.assert_called_once()
            assert thread_factory.call_args is not None
            assert thread_factory.call_args.kwargs["daemon"] is True
        finally:
            namespace_logger.removeHandler(log_handler)
            bootstrap._otel_log_handler = None
            bootstrap._telemetry_shutdown_started = False

    def test_shutdown_does_not_wait_for_unavailable_collector(self) -> None:
        trace_provider = MagicMock()
        meter_provider = MagicMock()
        fake_thread = MagicMock()
        bootstrap._otel_log_handler = None
        bootstrap._telemetry_shutdown_started = False
        try:
            with (
                patch.object(
                    bootstrap.trace,
                    "get_tracer_provider",
                    return_value=trace_provider,
                ),
                patch.object(
                    bootstrap.metrics,
                    "get_meter_provider",
                    return_value=meter_provider,
                ),
                patch.object(bootstrap.threading, "Thread", return_value=fake_thread),
            ):
                bootstrap.shutdown_telemetry_nonblocking()

            fake_thread.start.assert_called_once()
            trace_provider.shutdown.assert_not_called()
            meter_provider.shutdown.assert_not_called()
        finally:
            bootstrap._telemetry_shutdown_started = False

    def test_shutdown_closes_otlp_channels_before_background_provider_shutdown(
        self,
    ) -> None:
        trace_provider = MagicMock()
        meter_provider = MagicMock()
        fake_thread = MagicMock()
        channel = MagicMock()
        exporter = MagicMock(_channel=channel)
        bootstrap._otel_log_handler = None
        bootstrap._telemetry_exporters = (exporter,)
        bootstrap._telemetry_shutdown_started = False
        try:
            with (
                patch.object(
                    bootstrap.trace,
                    "get_tracer_provider",
                    return_value=trace_provider,
                ),
                patch.object(
                    bootstrap.metrics,
                    "get_meter_provider",
                    return_value=meter_provider,
                ),
                patch.object(bootstrap.atexit, "unregister"),
                patch.object(
                    bootstrap.threading,
                    "Thread",
                    return_value=fake_thread,
                ),
            ):
                bootstrap.shutdown_telemetry_nonblocking()

            channel.close.assert_called_once()
            fake_thread.start.assert_called_once()
        finally:
            bootstrap._telemetry_exporters = ()
            bootstrap._telemetry_shutdown_started = False
