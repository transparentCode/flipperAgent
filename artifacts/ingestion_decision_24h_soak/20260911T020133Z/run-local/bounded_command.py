"""Finite CLI execution with streamed output and owned descendant cleanup."""

from __future__ import annotations

import argparse
import os
import resource
import signal
import subprocess
import time


def run(command: list[str], timeout: float, *, deadline: float | None = None) -> int:
    budget = min(timeout, deadline - time.time()) if deadline is not None else timeout
    if budget <= 0:
        return 124
    child = None
    interrupted = 0

    def stop(signum, _frame):
        nonlocal interrupted
        interrupted = signum

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        if interrupted:
            return 128 + interrupted
        # The helper remains in the guard's group. It forwards guard/launchd
        # termination to this owned CLI group before the guard's kill grace.
        child = subprocess.Popen(command, start_new_session=True)
        expires = time.monotonic() + budget
        while child.poll() is None and not interrupted and time.monotonic() < expires:
            time.sleep(min(0.05, max(0, expires - time.monotonic())))
        if interrupted:
            return 128 + interrupted
        return child.returncode if child.returncode is not None else 124
    finally:
        if child is not None:
            # Also remove descendants whose leader already exited.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(0.2)
            child.poll()  # Reap an exited leader before probing/signalling its group.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--max-file-bytes", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not 0 < args.timeout < float("inf"):
        parser.error("finite positive timeout and command required")
    if args.max_file_bytes is not None:
        if args.max_file_bytes <= 0:
            parser.error("positive file bound required")
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (args.max_file_bytes, args.max_file_bytes)
        )
    return run(command, args.timeout, deadline=args.deadline)


if __name__ == "__main__":
    raise SystemExit(main())
