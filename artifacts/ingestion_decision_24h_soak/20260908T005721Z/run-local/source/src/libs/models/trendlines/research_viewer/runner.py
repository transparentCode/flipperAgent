"""Generic guarded runner for the mature trendlines TVLC viewer."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

from libs.models.trendlines.workflows.research.binance import BinanceTrendlineResearchLoader
from libs.models.trendlines.config.loader import load_trendlines_config
from libs.models.trendlines.research_viewer.bundle import (
    validate_viewer_bundle,
    write_viewer_bundle,
)
from libs.models.trendlines.research_viewer.contracts import (
    TrendlineViewerContractError,
    TrendlineViewerSpec,
    require_sha256,
)
from libs.models.trendlines.research_viewer.payload import (
    build_trendlines_viewer_payload,
)
from libs.models.trendlines.research_viewer.server import make_server
from libs.models.trendlines.workflows.research import (
    TrendlineEvidenceSelection,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    TrendlineReplayWindow,
    build_research_evidence_bundle,
    prepare_trendline_research,
    run_causal_replay,
)


UTC = timezone.utc
FETCH_ENVIRONMENT_VARIABLE = "TRENDLINES_ALLOW_RESEARCH_VIEWER_FETCH"
VIEWER_RUN_SCHEMA_VERSION = "trendlines_research_viewer_run_v1"
DEFAULT_DISPLAY_BARS = 250
DEFAULT_PORT = 8766
MINIMUM_VIEWER_BARS = 20

TIMEFRAME_INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "2h": 7_200,
    "4h": 14_400,
    "6h": 21_600,
    "8h": 28_800,
    "12h": 43_200,
    "1d": 86_400,
    "3d": 259_200,
    "1w": 604_800,
}
_ASSET = re.compile(r"^[A-Z0-9_]+$")
_OUTPUT_MEMBERS = frozenset({"viewer_bundle", "run_report.json"})
_BUNDLE_MEMBERS = frozenset({"chart_payload.json", "manifest.json"})
_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "asset",
        "timeframe",
        "source_type",
        "start",
        "end",
        "prepared_row_count",
        "selected_position",
        "display_bar_count",
        "dataset_id",
        "research_configuration_id",
        "preparation_id",
        "replay_id",
        "evidence_bundle_id",
        "viewer_payload_id",
        "viewer_bundle_id",
        "provider_calls",
        "page_count",
        "git_commit",
        "git_branch",
        "manual_serve_command",
    }
)


class ViewerRunnerError(ValueError):
    """Raised when runner input, execution, or output is invalid."""


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ViewerRunnerError("value is not canonical JSON data") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    from hashlib import sha256

    return sha256(value).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(_canonical_json_bytes(dict(value)))


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ViewerRunnerError(f"{path.name} must be a regular non-symlink file")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ViewerRunnerError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ViewerRunnerError(f"non-finite JSON constant in {path.name}: {value}")

    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ViewerRunnerError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ViewerRunnerError(f"{path.name} must contain an object")
    if raw != _canonical_json_bytes(value):
        raise ViewerRunnerError(f"{path.name} is not canonical JSON")
    return value, raw


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: datetime | str, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ViewerRunnerError(f"{field_name} must be ISO-8601 UTC") from exc
    else:
        raise ViewerRunnerError(f"{field_name} must be ISO-8601 UTC")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ViewerRunnerError(f"{field_name} must be timezone-aware UTC")
    if parsed.microsecond:
        raise ViewerRunnerError(f"{field_name} must use whole-second UTC timestamps")
    return parsed.astimezone(UTC)


def validate_asset(asset: str) -> str:
    if (
        not isinstance(asset, str)
        or not 2 <= len(asset) <= 40
        or asset != asset.upper()
        or _ASSET.fullmatch(asset) is None
        or not any("A" <= character <= "Z" for character in asset)
        or asset.startswith("_")
        or asset.endswith("_")
        or "__" in asset
    ):
        raise ViewerRunnerError(
            "asset must be a 2-40 character uppercase Binance symbol using "
            "A-Z, 0-9 and single underscores"
        )
    return asset


def timeframe_interval_seconds(timeframe: str) -> int:
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAME_INTERVAL_SECONDS:
        supported = ", ".join(TIMEFRAME_INTERVAL_SECONDS)
        raise ViewerRunnerError(
            f"timeframe must be a supported fixed-duration Binance interval: {supported}"
        )
    return TIMEFRAME_INTERVAL_SECONDS[timeframe]


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ViewerRunnerError(f"{field_name} must be a positive integer")
    return value


def _git_identity() -> tuple[str, str]:
    repository_root = Path(__file__).resolve().parents[5]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown", "unknown"
    return commit or "unknown", branch or "unknown"


def _provider_accounting(loader: Any, *, timeframe: str) -> tuple[int, int]:
    calls = getattr(loader, "provider_calls", None)
    if calls is None:
        calls = getattr(loader, "calls", None)
    if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
        raise ViewerRunnerError("loader must expose non-negative provider_calls")
    page_counts = getattr(loader, "page_counts", None)
    if not isinstance(page_counts, Mapping):
        raise ViewerRunnerError("loader must expose page_counts")
    if timeframe not in page_counts:
        raise ViewerRunnerError("loader page_counts must cover selected timeframe")
    values = tuple(page_counts.values())
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ViewerRunnerError("loader page_counts must contain non-negative integers")
    return calls, sum(values)


def _manual_serve_command(bundle_path: Path) -> str:
    bundle_text = shlex.quote(str(bundle_path))
    return (
        "PYTHONPATH=src:$PWD .venv/bin/python -m "
        "libs.models.trendlines.research_viewer.server "
        f"--bundle {bundle_text} --port {DEFAULT_PORT}"
    )


def _report(
    *,
    prepared: Any,
    replay: Any,
    evidence: Any,
    payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    timeframe: str,
    start: datetime,
    end: datetime,
    prepared_row_count: int,
    provider_calls: int,
    page_count: int,
    output_bundle: Path,
) -> dict[str, Any]:
    commit, branch = _git_identity()
    report = {
        "schema_version": VIEWER_RUN_SCHEMA_VERSION,
        "asset": prepared.spec.asset,
        "timeframe": timeframe,
        "source_type": "binance",
        "start": _iso(start),
        "end": _iso(end),
        "prepared_row_count": prepared_row_count,
        "selected_position": payload["selected_position"],
        "display_bar_count": len(payload["candles"]),
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
        "replay_id": replay.replay_id,
        "evidence_bundle_id": evidence.bundle_id,
        "viewer_payload_id": payload["payload_id"],
        "viewer_bundle_id": manifest["bundle_id"],
        "provider_calls": provider_calls,
        "page_count": page_count,
        "git_commit": commit,
        "git_branch": branch,
        "manual_serve_command": _manual_serve_command(output_bundle),
    }
    return report


def _validate_report(
    report: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    if set(report) != _REPORT_KEYS:
        raise ViewerRunnerError("run_report keys mismatch")
    if report["schema_version"] != VIEWER_RUN_SCHEMA_VERSION:
        raise ViewerRunnerError("unsupported run report schema")
    asset = validate_asset(report["asset"])
    timeframe = report["timeframe"]
    timeframe_interval_seconds(timeframe)
    start = parse_utc_timestamp(report["start"], field_name="run report start")
    end = parse_utc_timestamp(report["end"], field_name="run report end")
    if start >= end:
        raise ViewerRunnerError("run report start must precede end")
    if report["start"] != _iso(start) or report["end"] != _iso(end):
        raise ViewerRunnerError("run report timestamps are not canonical UTC")
    row_count = report["prepared_row_count"]
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < MINIMUM_VIEWER_BARS:
        raise ViewerRunnerError("run report prepared row count is invalid")
    selected = report["selected_position"]
    if isinstance(selected, bool) or not isinstance(selected, int) or selected != row_count - 1:
        raise ViewerRunnerError("run report selected position is invalid")
    display_count = report["display_bar_count"]
    if isinstance(display_count, bool) or not isinstance(display_count, int) or display_count < 1:
        raise ViewerRunnerError("run report display bar count is invalid")
    if report["source_type"] != "binance":
        raise ViewerRunnerError("run report source type is invalid")
    for field_name in (
        "dataset_id",
        "research_configuration_id",
        "preparation_id",
        "replay_id",
        "evidence_bundle_id",
        "viewer_payload_id",
        "viewer_bundle_id",
    ):
        require_sha256(report[field_name], f"run_report.{field_name}")
    for field_name in ("provider_calls", "page_count"):
        value = report[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ViewerRunnerError(f"run report {field_name} is invalid")
    if not isinstance(report["git_commit"], str) or not report["git_commit"]:
        raise ViewerRunnerError("run report git_commit is invalid")
    if not isinstance(report["git_branch"], str) or not report["git_branch"]:
        raise ViewerRunnerError("run report git_branch is invalid")
    if not isinstance(report["manual_serve_command"], str) or "--port 8766" not in report["manual_serve_command"]:
        raise ViewerRunnerError("run report manual serve command is invalid")

    if payload["asset"] != asset or payload["timeframe"] != timeframe:
        raise ViewerRunnerError("run report market identity differs from payload")
    if payload["selected_position"] != selected:
        raise ViewerRunnerError("run report selected position differs from payload")
    if display_count != len(payload["candles"]):
        raise ViewerRunnerError("run report display bar count differs from payload")
    for field_name in (
        "dataset_id",
        "research_configuration_id",
        "replay_id",
        "evidence_bundle_id",
    ):
        if report[field_name] != payload[field_name]:
            raise ViewerRunnerError(f"run report {field_name} differs from payload")
    if report["viewer_payload_id"] != payload["payload_id"]:
        raise ViewerRunnerError("run report payload identity differs")
    if report["viewer_bundle_id"] != manifest["bundle_id"]:
        raise ViewerRunnerError("run report bundle identity differs")
    if manifest["payload_id"] != payload["payload_id"]:
        raise ViewerRunnerError("viewer manifest payload identity differs")


def verify_output(output: str | Path) -> dict[str, Any]:
    """Verify exact published viewer bundle and identity-bound run report."""

    root = Path(output)
    if root.is_symlink() or not root.is_dir():
        raise ViewerRunnerError("output must be a real directory")
    entries = tuple(root.iterdir())
    if {entry.name for entry in entries} != _OUTPUT_MEMBERS:
        raise ViewerRunnerError("output contains unexpected files")
    bundle = root / "viewer_bundle"
    if bundle.is_symlink() or not bundle.is_dir():
        raise ViewerRunnerError("viewer_bundle must be a real directory")
    if {entry.name for entry in bundle.iterdir()} != _BUNDLE_MEMBERS:
        raise ViewerRunnerError("viewer bundle members mismatch")
    payload = validate_viewer_bundle(bundle)
    manifest, _ = _read_json(bundle / "manifest.json")
    report, _ = _read_json(root / "run_report.json")
    _validate_report(report, payload=payload, manifest=manifest)
    return dict(report)


async def run_viewer(
    *,
    asset: str,
    timeframe: str,
    source: str = "binance",
    start: datetime | str,
    end: datetime | str,
    output: str | Path,
    display_bars: int = DEFAULT_DISPLAY_BARS,
    loader_factory: Callable[[], Any] | None = None,
    trendlines_config: Any | None = None,
) -> dict[str, Any]:
    """Fetch, replay, and publish one final-point mature trendlines viewer."""

    asset = validate_asset(asset)
    timeframe_interval_seconds(timeframe)
    if source != "binance":
        raise ViewerRunnerError("source must be binance")
    start_value = parse_utc_timestamp(start, field_name="start")
    end_value = parse_utc_timestamp(end, field_name="end")
    if start_value >= end_value:
        raise ViewerRunnerError("start must precede end")
    display_bars = _positive_int(display_bars, field_name="display_bars")
    destination = Path(output)
    if destination.exists():
        raise ViewerRunnerError("output root already exists")
    if os.environ.get(FETCH_ENVIRONMENT_VARIABLE) != "1":
        raise ViewerRunnerError(
            f"Binance source requires {FETCH_ENVIRONMENT_VARIABLE}=1"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.staging-",
            dir=str(destination.parent),
        )
    )
    try:
        loader = (
            loader_factory()
            if loader_factory is not None
            else BinanceTrendlineResearchLoader()
        )
        spec = TrendlineResearchSpec(
            purpose=TrendlineResearchPurpose.RESEARCH,
            data=TrendlineResearchDataSpec(
                mode=TrendlineResearchDataMode.BINANCE,
                event_start=start_value,
                knowledge_cutoff=end_value,
            ),
            asset=asset,
            timeframes=(timeframe,),
            primary_timeframe=timeframe,
        )
        prepared = await prepare_trendline_research(
            spec,
            trendlines_config=trendlines_config or load_trendlines_config(),
            loader=loader,
        )
        frame = prepared.dataset.frames[timeframe]
        if len(frame) < MINIMUM_VIEWER_BARS:
            raise ViewerRunnerError(
                f"prepared data requires at least {MINIMUM_VIEWER_BARS} bars; got {len(frame)}"
            )
        end_position = len(frame) - 1
        replay_spec = TrendlineResearchReplaySpec(
            windows={
                timeframe: TrendlineReplayWindow(
                    warmup_start_position=min(19, end_position),
                    record_start_position=end_position,
                    end_position=end_position,
                    record_every=1,
                )
            },
            include_signals=True,
        )
        replay = run_causal_replay(prepared, replay_spec)
        point = replay.latest(timeframe)
        if point.position != end_position:
            raise ViewerRunnerError("replay did not record final prepared position")
        viewer_spec = TrendlineViewerSpec(
            timeframe=timeframe,
            position=end_position,
            display_lookback_bars=min(display_bars, end_position + 1),
        )
        evidence = build_research_evidence_bundle(
            prepared,
            replay,
            selection=TrendlineEvidenceSelection(
                timeframe=timeframe,
                position=end_position,
            ),
        )
        payload = build_trendlines_viewer_payload(
            prepared,
            replay,
            evidence,
            viewer_spec,
        )
        bundle_path = write_viewer_bundle(payload, staging / "viewer_bundle")
        validated_payload = validate_viewer_bundle(bundle_path)
        manifest, _ = _read_json(bundle_path / "manifest.json")
        provider_calls, page_count = _provider_accounting(loader, timeframe=timeframe)
        report = _report(
            prepared=prepared,
            replay=replay,
            evidence=evidence,
            payload=validated_payload,
            manifest=manifest,
            timeframe=timeframe,
            start=start_value,
            end=end_value,
            prepared_row_count=len(frame),
            provider_calls=provider_calls,
            page_count=page_count,
            output_bundle=destination / "viewer_bundle",
        )
        _write_json(staging / "run_report.json", report)
        verify_output(staging)
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return verify_output(destination)


def serve_viewer(output: str | Path, *, port: int = DEFAULT_PORT) -> None:
    """Serve verified mature viewer bundle on loopback until interrupted."""

    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ViewerRunnerError("port must be between 1 and 65535")
    server = make_server(Path(output) / "viewer_bundle", host="127.0.0.1", port=port)
    print(f"http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run generic mature trendlines TVLC viewer")
    parser.add_argument("--asset", help="canonical uppercase Binance symbol")
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAME_INTERVAL_SECONDS))
    parser.add_argument("--source", choices=("binance",), default=None)
    parser.add_argument("--start", help="inclusive ISO-8601 UTC event boundary")
    parser.add_argument("--end", help="causal ISO-8601 UTC knowledge cutoff")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--display-bars", type=int, default=DEFAULT_DISPLAY_BARS)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--verify-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_output is not None:
            if any(
                value is not None
                for value in (
                    args.asset,
                    args.timeframe,
                    args.source,
                    args.start,
                    args.end,
                    args.output,
                )
            ) or args.serve or args.port is not None:
                raise ViewerRunnerError("--verify-output cannot be combined with run options")
            report = verify_output(args.verify_output)
            print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
            return 0
        if args.port is not None and not args.serve:
            raise ViewerRunnerError("--port requires --serve")
        if any(value is None for value in (args.asset, args.timeframe, args.start, args.end, args.output)):
            raise ViewerRunnerError("--asset, --timeframe, --start, --end, and --output are required")
        report = asyncio.run(
            run_viewer(
                asset=args.asset,
                timeframe=args.timeframe,
                source=args.source or "binance",
                start=args.start,
                end=args.end,
                output=args.output,
                display_bars=args.display_bars,
            )
        )
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
        if args.serve:
            serve_viewer(args.output, port=args.port or DEFAULT_PORT)
        return 0
    except (ViewerRunnerError, TrendlineViewerContractError, ValueError, OSError) as exc:
        print(f"error: {exc}", flush=True)
        return 2


__all__ = [
    "DEFAULT_DISPLAY_BARS",
    "DEFAULT_PORT",
    "FETCH_ENVIRONMENT_VARIABLE",
    "MINIMUM_VIEWER_BARS",
    "TIMEFRAME_INTERVAL_SECONDS",
    "VIEWER_RUN_SCHEMA_VERSION",
    "ViewerRunnerError",
    "build_parser",
    "main",
    "parse_utc_timestamp",
    "run_viewer",
    "serve_viewer",
    "timeframe_interval_seconds",
    "validate_asset",
    "verify_output",
]
