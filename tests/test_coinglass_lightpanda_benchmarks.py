"""Tests for CoinGlass Lightpanda benchmark helpers."""

from __future__ import annotations

from apps.coinglass_scraper.lightpanda_testing.run_browser_benchmarks import (
    _json_version_url,
)


def test_json_version_url_normalizes_trailing_slash():
    assert _json_version_url("ws://127.0.0.1:9222/") == "http://127.0.0.1:9222/json/version"
