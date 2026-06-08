"""Benchmark CoinGlass extraction across Chromium and a Lightpanda CDP browser."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

import psutil

from apps.coinglass_scraper.interceptor import CoinGlassHeatmapInterceptor
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


def _sample_process_tree_rss_bytes(root_pid: int) -> int:
    try:
        root = psutil.Process(root_pid)
    except psutil.Error:
        return 0

    total = 0
    processes = [root]
    with suppress(psutil.Error):
        processes.extend(root.children(recursive=True))
    for process in processes:
        with suppress(psutil.Error):
            total += process.memory_info().rss
    return total


async def _extract_with_interceptor(
    interceptor: CoinGlassHeatmapInterceptor,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    return await interceptor.fetch_heatmap(
        coin=args.coin,
        market_type=args.market_type,
        exchange=args.exchange,
        symbol=args.symbol,
        short_name=args.short_name,
    )


async def _run_case(
    label: str,
    interceptor: CoinGlassHeatmapInterceptor,
    args: argparse.Namespace,
    rss_root_pid: int,
) -> dict[str, Any]:
    peak_rss = 0
    stop_sampling = False

    async def sample_rss() -> None:
        nonlocal peak_rss
        while not stop_sampling:
            peak_rss = max(peak_rss, _sample_process_tree_rss_bytes(rss_root_pid))
            await asyncio.sleep(0.05)

    started = time.perf_counter()
    sampler = asyncio.create_task(sample_rss())
    try:
        result = await asyncio.wait_for(
            _extract_with_interceptor(interceptor, args),
            timeout=args.case_timeout_seconds,
        )
    finally:
        stop_sampling = True
        await sampler

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    if result is None:
        return {
            "case": label,
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "peak_rss_mb": round(peak_rss / (1024 * 1024), 2),
            "reason": "no_result",
        }

    payload = result["payload"]
    return {
        "case": label,
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "peak_rss_mb": round(peak_rss / (1024 * 1024), 2),
        "shape": result.get("shape"),
        "response_url": result.get("response_url"),
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


async def _run_benchmarks(args: argparse.Namespace) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    chromium_interceptor = CoinGlassHeatmapInterceptor(cookies_path=args.cookies_path)
    results.append(
        await _run_case(
            "chromium_patchright",
            chromium_interceptor,
            args,
            rss_root_pid=psutil.Process().pid,
        )
    )

    if not args.skip_lightpanda:
        process: subprocess.Popen[str] | None = None
        try:
            if args.lightpanda_launch_command:
                process = subprocess.Popen(args.lightpanda_launch_command, shell=True)
                _wait_for_cdp(args.lightpanda_endpoint_url, args.startup_timeout_seconds)

            lightpanda_interceptor = LightpandaCDPHeatmapInterceptor(
                endpoint_url=args.lightpanda_endpoint_url,
                cookies_path=args.cookies_path,
            )
            results.append(
                await _run_case(
                    "lightpanda_cdp",
                    lightpanda_interceptor,
                    args,
                    rss_root_pid=process.pid if process is not None else psutil.Process().pid,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "case": "lightpanda_cdp",
                    "ok": False,
                    "reason": repr(exc),
                }
            )
        finally:
            if process is not None:
                process.terminate()
                with suppress(Exception):
                    process.wait(timeout=5)

    return {
        "checked_at_epoch_ms": int(time.time() * 1000),
        "coin": args.coin,
        "exchange": args.exchange,
        "symbol": args.symbol,
        "lightpanda_endpoint_url": args.lightpanda_endpoint_url,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cookies-path", default="secrets/coinglass_cookies.json")
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--market-type", default="pair")
    parser.add_argument("--exchange", default="Binance")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--short-name", default="SOL")
    parser.add_argument("--case-timeout-seconds", type=float, default=25.0)
    parser.add_argument("--startup-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--lightpanda-endpoint-url", default="ws://127.0.0.1:9222")
    parser.add_argument("--lightpanda-launch-command", default=None)
    parser.add_argument("--skip-lightpanda", action="store_true")
    parser.add_argument("--print-default-lightpanda-command", action="store_true")
    parser.add_argument("--lightpanda-binary-path", default="lightpanda")
    parser.add_argument("--output-path", default=None)
    args = parser.parse_args()

    if args.print_default_lightpanda_command:
        print(
            build_lightpanda_launch_command(
                binary_path=args.lightpanda_binary_path,
            )
        )
        return

    report = asyncio.run(_run_benchmarks(args))
    output = json.dumps(report, indent=2)
    print(output)

    if args.output_path:
        Path(args.output_path).write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
