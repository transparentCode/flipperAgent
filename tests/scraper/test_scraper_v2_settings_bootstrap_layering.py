"""Settings, bootstrap SQL, layering guard, PostgreSQL-gated and live tests."""

from __future__ import annotations

import ast
import copy
import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from scraper_v2_support import REPO_ROOT, production_settings, require_test_database

from apps.scraper_app.settings import SettingsError, database_uri, parse_settings
from apps.scraper_app.storage import bootstrap

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)


def _raw() -> dict:
    return copy.deepcopy(
        yaml.safe_load((REPO_ROOT / "configs" / "scraper.yaml").read_text())["scraper"]
    )


def test_production_file_yields_exactly_twenty_unique_datasets() -> None:
    settings = production_settings()
    specs = settings.dataset_specs()
    assert len(specs) == 20 and len({s.id for s in specs}) == 20
    by_id = {s.id: s for s in specs}
    for spec_id, spec in by_id.items():
        if spec_id.startswith("tv.cryptocap") and spec_id.endswith(".1d"):
            pair = (604800, 1036800)
        else:  # one provisional rule for 1h/4h indices and every Binance series
            pair = (345600, 1036800)
        assert (spec.finality_horizon_seconds, spec.revision_watch_seconds) == pair, (
            spec_id
        )
    assert (
        by_id["tv.binance.btcusdt_p.oi.1h"].canonical_symbol == "BINANCE:BTCUSDT.P_OI"
    )
    funding = by_id["tv.binance.ethusdt_p.funding.1h"]
    assert (funding.contiguous, funding.non_negative) == (False, False)
    assert by_id["tv.cryptocap.btc_d.1d"].resolution == "1D"
    assert settings.server.port == 8005


def test_production_coinglass_block_parses_and_the_lane_is_on() -> None:
    settings = production_settings()
    cg = settings.coinglass
    assert cg is not None
    ids = [s.id for s in settings.payload_specs()]
    assert ids == [
        "cg.binance.btcusdt.liq_heatmap.5m.24h",
        "cg.maxpain.24h",
        "cg.binance.ethusdt.liq_heatmap.5m.24h",
        "cg.binance.solusdt.liq_heatmap.5m.24h",
        "cg.binance.bnbusdt.liq_heatmap.5m.24h",
        "cg.binance.btcusdt.liq_map.1d",
        "cg.binance.ethusdt.liq_map.1d",
        "cg.binance.solusdt.liq_map.1d",
        "cg.binance.bnbusdt.liq_map.1d",
    ]
    assert [s.requires_login for s in settings.payload_specs()] == [False, False] + [
        True
    ] * 7
    assert {s.kind for s in settings.payload_specs()} == {
        "liq_heatmap",
        "max_pain",
        "liq_map",
    }
    assert (cg.cycle_retries, cg.cycle_retry_delay_seconds) == (1, 20)
    assert cg.slot_minutes == (5, 20, 35, 50) and cg.slot_second == 0
    assert cg.engine_url == "http://scraper-browser:9222"
    assert cg.cookies_path == "secrets/coinglass_cookies.json"
    assert (cg.cycle_deadline_seconds, cg.max_payload_bytes) == (120, 4_000_000)


def test_unknown_keys_are_rejected_at_every_level() -> None:
    for mutate in (
        lambda r: r.update(extra=1),
        lambda r: r["tradingview"].update(extra=1),
        lambda r: r["datasets"][0].update(extra=1),
    ):
        raw = _raw()
        mutate(raw)
        with pytest.raises(ValidationError):
            parse_settings(raw)


def test_duplicate_ids_and_unknown_intervals_are_rejected() -> None:
    raw = _raw()
    raw["datasets"][1]["id"] = raw["datasets"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate"):
        parse_settings(raw)
    raw = _raw()
    raw["datasets"][0]["interval"] = "2h"
    with pytest.raises(ValidationError):
        parse_settings(raw)


def test_production_config_passes_the_retention_validator_with_tradingview_14() -> None:
    raw = _raw()
    assert raw["retention"]["tradingview_days"] == 14
    assert raw["retention"]["coinglass_days"] == 14
    parse_settings(raw)  # 12 d + 2 x 1 d == 14 d for 1D: exactly at the limit
    daily = next(d for d in raw["datasets"] if d["interval"] == "1D")
    daily["revision_watch_seconds"] = 1036801
    with pytest.raises(ValidationError, match="tradingview_days"):
        parse_settings(raw)


def test_revision_watch_validators() -> None:
    raw = _raw()
    raw.pop("retention")
    raw["datasets"][0]["revision_watch_seconds"] = (
        raw["datasets"][0]["finality_horizon_seconds"] - 1
    )
    with pytest.raises(ValidationError, match="below finality_horizon"):
        parse_settings(raw)
    raw = _raw()
    raw.pop("retention")  # 1h dataset: 5000 bars max, 3 margin -> 4997 h at most
    raw["datasets"][0]["revision_watch_seconds"] = 4998 * 3600
    with pytest.raises(ValidationError, match="max_bars_per_request"):
        parse_settings(raw)
    raw = _raw()
    raw.pop("retention")
    raw["datasets"][0]["revision_watch_seconds"] = 4997 * 3600
    parse_settings(raw)
    raw = _raw()
    raw.pop("retention")
    del raw["datasets"][0]["revision_watch_seconds"]
    with pytest.raises(ValidationError):
        parse_settings(raw)


def test_probe_timeout_is_required() -> None:
    raw = _raw()
    del raw["readiness"]["probe_timeout_seconds"]
    with pytest.raises(ValidationError):
        parse_settings(raw)


def test_inconsistent_retry_and_bar_limits_are_rejected() -> None:
    raw = _raw()
    raw["tradingview"]["retry_backoff_seconds"] = [5]
    with pytest.raises(ValidationError):
        parse_settings(raw)
    raw = _raw()
    raw["tradingview"]["min_bars_per_request"] = 6000
    with pytest.raises(ValidationError):
        parse_settings(raw)


def test_new_operational_settings_are_configured_and_strict() -> None:
    settings = production_settings()
    assert settings.database.connect_timeout_seconds == 10
    assert settings.database.command_timeout_seconds == 15
    assert settings.readiness.latest_bar_grace_seconds == 300
    assert settings.readiness.recent_gap_window_seconds == 172800
    assert settings.readiness.max_clock_skew_seconds == 120
    assert settings.readiness.probe_timeout_seconds == 5
    raw = _raw()
    raw["database"]["extra"] = 1
    with pytest.raises(ValidationError):
        parse_settings(raw)
    raw = _raw()
    del raw["readiness"]["max_clock_skew_seconds"]
    with pytest.raises(ValidationError):
        parse_settings(raw)


def test_schema_adds_holes_idempotently_for_existing_databases() -> None:
    sql = (REPO_ROOT / "src/apps/scraper_app/storage/schema.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS holes" in sql
    assert "autovacuum_analyze_scale_factor = 0" in sql
    assert "autovacuum_analyze_threshold = 2000" in sql


def test_database_uri_comes_only_from_the_environment_and_fails_fast() -> None:
    with pytest.raises(SettingsError):
        database_uri({})
    assert (
        database_uri({"SCRAPER_POSTGRES_URI": " postgresql://x "}) == "postgresql://x"
    )


def test_grants_are_limited_to_select_insert_and_sequence_usage() -> None:
    statements = bootstrap.grant_statements("scraper.reads_read_id_seq")
    grants = [s for s in statements if s.startswith("GRANT")]
    text = " ".join(statements).upper()
    for forbidden in ("UPDATE", "DELETE", "TRUNCATE", "ALL PRIVILEGES", "PUBLIC"):
        assert forbidden not in text.replace("REVOKE ALL", "")
    assert (
        "GRANT SELECT, INSERT ON scraper.reads, scraper.bar_observations, "
        "scraper.payload_observations TO scraper_app" in grants
    )
    assert "GRANT USAGE ON SEQUENCE scraper.reads_read_id_seq TO scraper_app" in grants


def test_schema_sql_matches_the_contract_shape() -> None:
    sql = (REPO_ROOT / "src/apps/scraper_app/storage/schema.sql").read_text().lower()
    for needle in (
        "create schema if not exists scraper",
        "scraper.reads",
        "scraper.bar_observations",
        "primary key (dataset_id, bar_open, seq)",
        "clock_timestamp()",
    ):
        assert needle in sql
    assert "hypertable" not in sql and "retention" not in sql


@pytest.mark.asyncio
async def test_apply_schema_executes_in_order_with_a_server_quoted_password() -> None:
    class Conn:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def transaction(self):
            class T:
                async def __aenter__(self_inner):
                    return None

                async def __aexit__(self_inner, *a):
                    return False

            return T()

        async def execute(self, sql):
            self.executed.append(sql)

        async def fetchval(self, query, *args):
            if "quote_literal" in query:
                return "'quoted'"
            if "pg_roles" in query:
                return None
            return "scraper.reads_read_id_seq"

    conn = Conn()
    await bootstrap.apply_scraper_schema(conn, "pw")  # type: ignore[arg-type]
    assert "CREATE SCHEMA" in conn.executed[0]
    assert conn.executed[1] == "CREATE ROLE scraper_app WITH LOGIN PASSWORD 'quoted'"
    assert all("pw" not in s for s in conn.executed)
    with pytest.raises(ValueError):
        await bootstrap.apply_scraper_schema(conn, "")  # type: ignore[arg-type]


# --- layering guard ---------------------------------------------------------

SRC = REPO_ROOT / "src" / "apps" / "scraper_app"
NEW_PATHS = [
    "main.py",
    "settings.py",
    "domain",
    "adapters",
    "storage",
    "runtime",
    "http_api",
]
FORBIDDEN_APP = {"api", "core", "providers", "service", "cli", "runtime_status"}
FORBIDDEN_TOP = {"arq", "valkey", "redis", "patchright", "pandas", "scripts"}


def _new_files() -> list[Path]:
    files: list[Path] = []
    for name in NEW_PATHS:
        path = SRC / name
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def _violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for module in modules:
            parts = module.split(".")
            if parts[0] in FORBIDDEN_TOP or (
                parts[:2] == ["apps", "scraper_app"]
                and len(parts) > 2
                and parts[2] in FORBIDDEN_APP
            ):
                found.append(module)
    return found


def test_layer_checker_detects_forbidden_imports() -> None:
    assert _violations("from apps.scraper_app.core import X") == [
        "apps.scraper_app.core",
        "apps.scraper_app.core.X",
    ]
    assert _violations("from apps.scraper_app import runtime_status") == [
        "apps.scraper_app.runtime_status"
    ]
    assert _violations("import pandas as pd") == ["pandas"]
    assert _violations("from apps.scraper_app.runtime.status import X") == []


def test_retired_scraper_paths_no_longer_exist() -> None:
    for name in sorted(FORBIDDEN_APP):
        assert not (SRC / name).exists(), name
        assert not (SRC / f"{name}.py").exists(), name
    for retired in (
        "src/apps/api_app/clients",
        "src/apps/api_app/routers/ingestion.py",
        "src/libs/common/clients",
        "scripts/tv_browser_backfill.py",
        "Dockerfile.tv-scraper",
        "configs/tradingview.yaml",
        "configs/coinglass.yaml",
    ):
        assert not (REPO_ROOT / retired).exists(), retired


def test_new_modules_import_none_of_the_forbidden_modules() -> None:
    files = _new_files()
    assert len(files) > 15
    assert {f for f in files if f.name == "__init__.py"}
    offenders = {str(f): v for f in files if (v := _violations(f.read_text()))}
    assert offenders == {}


def test_no_relative_imports_escape_to_old_modules() -> None:
    for f in _new_files():
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert (
                    node.module is None
                    or node.module.split(".")[0] not in FORBIDDEN_APP
                )


# --- PostgreSQL-gated -------------------------------------------------------


@needs_postgres
@pytest.mark.asyncio
async def test_bootstrap_twice_and_runtime_role_cannot_update_or_delete() -> None:
    import asyncpg

    admin = await asyncpg.connect(POSTGRES_URI)
    await require_test_database(admin)
    try:
        await bootstrap.apply_scraper_schema(admin, "scraper-test-password")
        await bootstrap.apply_scraper_schema(admin, "scraper-test-password")
        await admin.execute(
            "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
            "error_code) VALUES ('t', 'schedule', 'failed', now(), 'timeout')"
        )
        await admin.execute("SET ROLE scraper_app")
        await admin.fetchval("SELECT count(*) FROM scraper.reads")
        for statement in (
            "UPDATE scraper.reads SET dataset_id = 'x'",
            "DELETE FROM scraper.reads",
            "TRUNCATE scraper.reads",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await admin.execute(statement)
    finally:
        await admin.execute("RESET ROLE")
        await admin.execute("DELETE FROM scraper.reads WHERE dataset_id = 't'")
        await admin.close()


@needs_postgres
@pytest.mark.asyncio
async def test_advisory_lock_is_exclusive_on_a_real_database() -> None:
    import asyncpg

    from apps.scraper_app.runtime.singleton import AdvisoryLock

    probe = await asyncpg.connect(POSTGRES_URI)
    try:
        await require_test_database(probe)
    finally:
        await probe.close()
    first = AdvisoryLock(lambda: asyncpg.connect(POSTGRES_URI))
    second = AdvisoryLock(lambda: asyncpg.connect(POSTGRES_URI))
    try:
        assert await first.try_acquire()
        assert not await second.try_acquire()
        await first.release()
        assert await second.try_acquire()
    finally:
        await first.release()
        await second.release()


# --- opt-in live ------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("SCRAPER_LIVE_TRADINGVIEW") != "1",
    reason="set SCRAPER_LIVE_TRADINGVIEW=1 to talk to TradingView",
)
@pytest.mark.asyncio
async def test_live_one_dataset_end_to_end() -> None:
    from datetime import UTC, datetime

    from apps.scraper_app.adapters.tradingview.client import TradingViewClient
    from apps.scraper_app.domain.bars import validate_bars
    from apps.scraper_app.settings import TradingViewSettings

    prod = production_settings()
    spec = next(s for s in prod.dataset_specs() if s.id == "tv.cryptocap.total3.1h")
    settings: TradingViewSettings = prod.tradingview
    result = await TradingViewClient(settings).fetch_series(
        spec.request_symbol, spec.resolution, 30
    )
    gate = validate_bars(
        spec,
        pro_name=result.pro_name,
        provider_time=result.provider_time,
        raw_bars=result.bars,
    )
    bars = gate.bars
    assert bars and bars[-1].bar_close.timestamp() <= result.provider_time
    assert abs(result.provider_time - datetime.now(UTC).timestamp()) < 300
