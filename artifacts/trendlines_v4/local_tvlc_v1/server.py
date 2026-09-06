from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from libs.models.trendlines_v4 import TrendlineBar, analyze_trendlines

ROOT = Path(__file__).resolve().parent
VENDOR = Path(
    "/Users/kajukatli/projects/flipperAgent/src/libs/models/sr_v2/research_viewer/"
    "web/node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs"
)
DATASETS = {
    "BTCUSDT": Path(
        "/Users/kajukatli/projects/flipperAgent/src/libs/regime/optimization/results/"
        "BTCUSDT_1h_2022-01-01_2026-03-01.csv"
    ),
    "ETHUSDT": Path(
        "/Users/kajukatli/projects/flipperAgent/src/libs/models/trendlines/optimization/results/"
        "ETHUSDT_1h_2023-01-01_2026-03-01.csv"
    ),
    "SOLUSDT": Path(
        "/Users/kajukatli/projects/flipperAgent/src/libs/models/trendlines/optimization/results/"
        "SOLUSDT_1h_2023-01-01_2026-03-01.csv"
    ),
    "HYPEUSDT": Path(
        "/Users/kajukatli/projects/flipperAgent/src/libs/models/trendlines/optimization/results/"
        "HYPEUSDT_1h_2022-01-01_2026-03-01.csv"
    ),
}


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _bars(path: Path, timeframe: str) -> tuple[TrendlineBar, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if timeframe == "1h":
        selected = rows[-300:]
        return tuple(
            TrendlineBar(
                closed_at=_parse_utc(row["close_time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            for row in selected
        )
    if timeframe != "4h":
        raise ValueError("timeframe must be 1h or 4h")

    buckets: dict[datetime, list[dict[str, str]]] = {}
    for row in rows:
        opened_at = _parse_utc(row["open_time"])
        bucket_start = opened_at.replace(
            hour=(opened_at.hour // 4) * 4,
            minute=0,
            second=0,
            microsecond=0,
        )
        buckets.setdefault(bucket_start, []).append(row)

    aggregated: list[TrendlineBar] = []
    for bucket_start in sorted(buckets):
        group = buckets[bucket_start]
        if len(group) != 4:
            continue
        opens = [_parse_utc(row["open_time"]) for row in group]
        expected_hours = [bucket_start.hour + offset for offset in range(4)]
        if [value.hour for value in opens] != expected_hours:
            continue
        aggregated.append(
            TrendlineBar(
                closed_at=_parse_utc(group[-1]["close_time"]),
                open=float(group[0]["open"]),
                high=max(float(row["high"]) for row in group),
                low=min(float(row["low"]) for row in group),
                close=float(group[-1]["close"]),
            )
        )
    return tuple(aggregated[-300:])


def _payload(asset: str, timeframe: str) -> bytes:
    path = DATASETS[asset]
    bars = _bars(path, timeframe)
    snapshot = analyze_trendlines(bars)
    lines: list[dict[str, object]] = []
    same_geometry_roles: list[dict[str, object]] = []
    for side_name in ("support", "resistance"):
        side = getattr(snapshot, side_name)
        if side.same_geometry and side.structural is not None:
            same_geometry_roles.append(
                {
                    "side": side_name,
                    "projected_price": side.structural.projected_price_at_market_as_of,
                }
            )
        for role in ("structural", "current_valid"):
            geometry = getattr(side, role)
            if geometry is None:
                continue
            if role == "current_valid" and side.same_geometry:
                continue
            lines.append(
                {
                    "side": side_name,
                    "role": role,
                    "start_time": int(geometry.start_anchor_at.timestamp()),
                    "start_price": geometry.start_anchor_price,
                    "end_anchor_time": int(geometry.end_anchor_at.timestamp()),
                    "end_anchor_price": geometry.end_anchor_price,
                    "current_time": int(snapshot.market_as_of.timestamp()),
                    "projected_price": geometry.projected_price_at_market_as_of,
                    "crossed": geometry.post_anchor_body_crossed,
                    "cross_count": geometry.post_anchor_body_cross_count,
                    "projection_positive": geometry.projection_positive,
                    "same_geometry": side.same_geometry,
                }
            )
    body = {
        "schema_version": "trendlines_v4_local_tvlc_v1",
        "asset": asset,
        "timeframe": timeframe,
        "source": str(path),
        "source_timeframe": "1h",
        "aggregation": "native" if timeframe == "1h" else "UTC-aligned 4x1h OHLC",
        "history_bar_count": snapshot.history_bar_count,
        "pivot_window": snapshot.pivot_window,
        "market_as_of": snapshot.market_as_of.isoformat(),
        "candles": [
            {
                "time": int(bar.closed_at.timestamp()),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
            }
            for bar in bars
        ],
        "lines": lines,
        "same_geometry_roles": same_geometry_roles,
    }
    return json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self._send((ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/vendor/lightweight-charts.mjs":
            self._send(VENDOR.read_bytes(), "text/javascript; charset=utf-8")
            return
        if parsed.path == "/data.json":
            query = parse_qs(parsed.query)
            asset = query.get("asset", ["BTCUSDT"])[0].upper()
            timeframe = query.get("tf", ["1h"])[0].lower()
            if asset not in DATASETS:
                self.send_error(400, f"unsupported asset; choose one of {', '.join(DATASETS)}")
                return
            if timeframe not in {"1h", "4h"}:
                self.send_error(400, "unsupported timeframe; choose 1h or 4h")
                return
            try:
                body = _payload(asset, timeframe)
            except Exception as exc:  # local disposable viewer boundary
                self.send_error(500, str(exc))
                return
            self._send(body, "application/json; charset=utf-8")
            return
        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_error(405)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("loopback host required")
    if not VENDOR.is_file():
        raise SystemExit(f"missing local Lightweight Charts module: {VENDOR}")
    for asset, path in DATASETS.items():
        if not path.is_file():
            raise SystemExit(f"missing dataset for {asset}: {path}")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Trendlines V4 TVLC viewer: http://{args.host}:{server.server_port}/", flush=True)
    print("Assets: BTCUSDT, ETHUSDT, SOLUSDT, HYPEUSDT via ?asset=...", flush=True)
    print("Timeframes: 1h or UTC-aligned 4h via ?tf=...", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
