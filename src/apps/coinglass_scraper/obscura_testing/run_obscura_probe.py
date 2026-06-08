"""Run a one-shot CoinGlass heatmap probe against an Obscura CDP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import suppress

from apps.coinglass_scraper.obscura_testing.cdp_interceptor import (
    ObscuraCDPHeatmapInterceptor,
    build_obscura_launch_command,
)


def _json_version_url(endpoint_url: str) -> str:
    return endpoint_url.rstrip("/") + "/json/version"


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


async def _run_probe(args: argparse.Namespace) -> dict[str, object]:
    interceptor = ObscuraCDPHeatmapInterceptor(
        endpoint_url=args.endpoint_url,
        cookies_path=args.cookies_path,
    )
    result = await interceptor.fetch_heatmap(
        coin=args.coin,
        market_type=args.market_type,
        exchange=args.exchange,
        symbol=args.symbol,
        short_name=args.short_name,
    )
    if result is None:
        return {"ok": False, "result": None}

    payload = result["payload"]
    return {
        "ok": True,
        "shape": result.get("shape"),
        "response_url": result.get("response_url"),
        "page_url": result.get("page_url"),
        "captured_at_ms": result.get("captured_at_ms"),
        "payload_summary": {
            "payload_keys": sorted(list(payload.keys())) if isinstance(payload, dict) else None,
            "liq_len": len(payload.get("liq", [])) if isinstance(payload, dict) else None,
            "prices_len": len(payload.get("prices", [])) if isinstance(payload, dict) else None,
            "y_len": len(payload.get("y", [])) if isinstance(payload, dict) else None,
            "liq0": payload.get("liq", [None])[0] if isinstance(payload, dict) else None,
            "price0": payload.get("prices", [None])[0] if isinstance(payload, dict) else None,
            "y0": payload.get("y", [None])[0] if isinstance(payload, dict) else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-url", default="http://127.0.0.1:9222")
    parser.add_argument("--cookies-path", default="secrets/coinglass_cookies.json")
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--market-type", default="pair")
    parser.add_argument("--exchange", default="Binance")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--short-name", default="SOL")
    parser.add_argument("--launch-command", default=None)
    parser.add_argument("--startup-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--print-default-launch-command", action="store_true")
    args = parser.parse_args()

    if args.print_default_launch_command:
        print(build_obscura_launch_command())
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
