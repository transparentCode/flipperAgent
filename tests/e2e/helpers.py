from __future__ import annotations

import os
import shlex
import shutil
import subprocess


def docker_compose_command() -> list[str]:
    override = os.getenv("E2E_DOCKER_COMPOSE_COMMAND")
    if override:
        return shlex.split(override)
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    raise RuntimeError("Docker Compose CLI not found for E2E tests")


def run_docker_compose(
    *args: str,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*docker_compose_command(), *args],
        check=check,
        capture_output=capture_output,
        text=text,
    )
