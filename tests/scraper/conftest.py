"""With ``SCRAPER_REQUIRE_PG=1`` a skipped database-gated test is a failure."""

from __future__ import annotations

import pytest
from scraper_v2_support import is_postgres_skip, postgres_required


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not (postgres_required() and report.skipped):
        return
    reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else ""
    if is_postgres_skip(reason):
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid}: SCRAPER_REQUIRE_PG=1 but the test was skipped: {reason}"
        )
