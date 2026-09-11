"""Harmless local subprocess tests; no Docker or launchd operations."""

import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HELPER = Path(__file__).with_name("bounded_command.py")


class BoundedCommandTests(unittest.TestCase):
    def test_stop_captures_before_down_and_keeps_failure_evidence(self):
        script = HELPER.with_name("launchd").joinpath("stop-run3.sh").read_text()
        self.assertLess(
            script.index("--max-file-bytes"), script.index("down --remove-orphans")
        )
        self.assertIn(
            "db broker ingestion decision otel-collector prometheus grafana", script
        )
        self.assertIn("if (( RUN3_LOG_FAILED )); then", script)
        self.assertIn('exit 1\nfi\n"$RUN3_PYTHON"', script)
        self.assertIn("$RUN3_SERVICE.status", script)
        self.assertNotIn("down --volumes", script)

    def command(self, code, *options):
        return [
            sys.executable,
            "-B",
            str(HELPER),
            "--timeout",
            "2",
            *options,
            "--",
            sys.executable,
            "-B",
            "-c",
            code,
        ]

    def test_expired_deadline_does_not_start(self):
        result = subprocess.run(
            self.command("raise SystemExit(7)", "--deadline", "1"),
            timeout=3,
            check=False,
        )
        self.assertEqual(result.returncode, 124)

    def test_child_exit_propagated(self):
        result = subprocess.run(
            self.command("raise SystemExit(7)"), timeout=3, check=False
        )
        self.assertEqual(result.returncode, 7)

    def test_timeout_is_finite(self):
        started = time.monotonic()
        result = subprocess.run(
            self.command("import time; time.sleep(30)", "--timeout", "0.1"),
            timeout=3,
            check=False,
        )
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 2)

    def test_streamed_file_bound(self):
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                self.command(
                    "import os; os.write(1, b'x'*100000)", "--max-file-bytes", "4096"
                ),
                stdout=output,
                stderr=output,
                timeout=3,
                check=False,
            )
            self.assertLessEqual(output.tell(), 4096)
            # A short write may return zero; the collector also checks size.
            self.assertIsInstance(result.returncode, int)

    def test_signal_removes_cli_and_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pids"
            code = (
                "import os,subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                f"open({str(path)!r},'w').write(str(os.getpid())+' '+str(p.pid)); "
                "time.sleep(30)"
            )
            process = subprocess.Popen(self.command(code))
            try:
                deadline = time.monotonic() + 1
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(path.exists())
                pids = [int(value) for value in path.read_text().split()]
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=2), 143)
                for pid in pids:
                    # An adopted zombie is dead, not a surviving subprocess.
                    result = subprocess.run(
                        ["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    self.assertTrue(
                        not result.stdout.strip()
                        or result.stdout.strip().startswith("Z")
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
