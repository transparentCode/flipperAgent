"""One-shot probe for a Lightpanda-backed CoinGlass CDP interceptor."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import suppress

from apps.coinglass_scraper.lightpanda_testing.cdp_interceptor import (
    LightpandaCDPHeatmapInterceptor,
    build_lightpanda_launch_command,
)


def _json_version_url(endpoint_url: str) -> str:
    normalized = endpoint_url.rstrip("/")
    if normalized.startswith("ws://"):
        normalized = "http://" + normalized.removeprefix("ws://")
    elif normalized.startswith("wss://"):
        normalized = "https://" + normalized.removeprefix("wss://")
    return normalized + "/json/version"


def _wait_for_cdp(endpoint_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(_json_version_url(endpoint_url), timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"CDP endpoint not ready: {endpoint_url}") from last_error


async def _run_probe(args: argparse.Namespace) -> dict[str, object] | None:
    interceptor = LightpandaCDPHeatmapInterceptor(
        endpoint_url=args.endpoint_url,
        cookies_path=args.cookies_path,
    )
    return await interceptor.fetch_heatmap(
        coin=args.coin,
        market_type=args.market_type,
        exchange=args.exchange,
        symbol=args.symbol,
        short_name=args.short_name,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-url", default="ws://127.0.0.1:9222")
    parser.add_argument("--launch-command", default=None)
    parser.add_argument("--startup-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--cookies-path", default="secrets/coinglass_cookies.json")
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--market-type", default="pair")
    parser.add_argument("--exchange", default="Binance")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--short-name", default="SOL")
    parser.add_argument("--print-default-launch-command", action="store_true")
    args = parser.parse_args()

    if args.print_default_launch_command:
        print(build_lightpanda_launch_command())
        return

    process: subprocess.Popen[str] | None = None
    try:
        if args.launch_command:
            process = subprocess.Popen(args.launch_command, shell=True)
            _wait_for_cdp(args.endpoint_url, args.startup_timeout_seconds)

        result = asyncio.run(_run_probe(args))
        print(json.dumps(result, indent=2))
    finally:
        if process is not None:
            process.terminate()
            with suppress(Exception):
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
