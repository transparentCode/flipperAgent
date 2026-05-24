from __future__ import annotations

import io
import logging
import tempfile
import unittest
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from flipper_agent.commons.logging import (
    bind_logger,
    clear_current_trace_id,
    configure_logging,
    get_logger,
    set_current_trace_id,
)
from flipper_agent.commons.paths import default_log_file


class LoggerUtilsTests(unittest.TestCase):
    def _configure_console_stream(self) -> io.StringIO:
        namespace_logger = configure_logging(level="INFO")
        stream = io.StringIO()

        for handler in namespace_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setStream(stream)

        return stream

    def _flush_namespace_handlers(self) -> None:
        logger = logging.getLogger("flipper_agent")
        for handler in logger.handlers:
            handler.flush()

    def tearDown(self) -> None:
        clear_current_trace_id()
        logger = logging.getLogger("flipper_agent")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_get_logger_uses_flipper_agent_namespace(self) -> None:
        logger = get_logger("commons.worker")
        self.assertEqual(logger.name, "flipper_agent.commons.worker")

    def test_explicit_trace_id_and_system_component_are_rendered_in_console_logs(self) -> None:
        stream = self._configure_console_stream()
        set_current_trace_id("trace-from-context")

        logger = bind_logger(
            "commons.jobs",
            traceId="trace-explicit",
            run_id="run-123",
            systemComponent="loader",
            attempt=2,
        )
        logger.info("started")

        output = stream.getvalue()
        self.assertIn("started", output)
        self.assertIn("trace_id=trace-explicit", output)
        self.assertNotIn("trace_id=trace-from-context", output)
        self.assertIn("run_id=run-123", output)
        self.assertIn("system_component=loader", output)
        self.assertIn("attempt=2", output)

    def test_context_trace_id_is_rendered_when_not_bound(self) -> None:
        stream = self._configure_console_stream()
        set_current_trace_id("trace-from-context")

        logger = get_logger("commons.jobs")
        logger.info("started-from-context")

        output = stream.getvalue()
        self.assertIn("started-from-context", output)
        self.assertIn("trace_id=trace-from-context", output)

    def test_file_logging_writes_to_configured_path_with_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "app.log"
            configure_logging(level="INFO", enable_file_logging=True, log_file=log_file)
            set_current_trace_id("trace-file")

            logger = bind_logger("commons.jobs", system_component="writer")
            logger.info("written-to-file")
            self._flush_namespace_handlers()

            self.assertTrue(log_file.exists())
            file_output = log_file.read_text()
            
            import json
            parsed = json.loads(file_output.strip())
            self.assertEqual(parsed["message"], "written-to-file")
            self.assertEqual(parsed["trace_id"], "trace-file")
            self.assertEqual(parsed["system_component"], "writer")

    def test_file_logging_rotates_and_retains_configured_backups(self) -> None:
        import re
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "app.log"
            namespace_logger = configure_logging(
                level="INFO",
                enable_file_logging=True,
                log_file=log_file,
                file_backup_count=1,
            )

            file_handler = next(
                handler
                for handler in namespace_logger.handlers
                if isinstance(handler, TimedRotatingFileHandler)
            )
            self.assertEqual(file_handler.when, "MIDNIGHT")
            self.assertEqual(file_handler.backupCount, 1)

            logger = get_logger("commons.jobs")
            logger.info("line-1")

            # Simulate midnight rotation
            file_handler.doRollover()

            self._flush_namespace_handlers()

            self.assertTrue(log_file.exists())
            
            rotated_files = [
                f for f in log_file.parent.iterdir()
                if re.match(r"app\.log\.\d{4}-\d{2}-\d{2}$", f.name)
            ]
            self.assertTrue(len(rotated_files) >= 1)

    def test_default_log_file_points_to_top_level_logs_directory(self) -> None:
        log_file = default_log_file()
        self.assertEqual(log_file.name, "app.log")
        self.assertEqual(log_file.parent.name, "logs")


if __name__ == "__main__":
    unittest.main()