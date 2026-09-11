import asyncio
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from libs.models.trendlines.research_viewer import (
    TrendlineResearchNotebookSession,
    make_server,
)
from libs.models.trendlines.research_viewer.notebook_support import run_research_notebook_session


VIEWER_WEB_ROOT = Path(__file__).resolve().parents[2] / "research_viewer" / "web"


@pytest.fixture(scope="module")
def smoke_session() -> TrendlineResearchNotebookSession:
    result = asyncio.run(run_research_notebook_session(start_viewer=False))
    yield result
    result.close()


def test_loopback_server_accepts_ephemeral_port(smoke_session: TrendlineResearchNotebookSession) -> None:
    server = make_server(smoke_session.viewer_bundle_path, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_non_loopback_server_is_rejected(smoke_session: TrendlineResearchNotebookSession) -> None:
    with pytest.raises(ValueError):
        make_server(smoke_session.viewer_bundle_path, host="0.0.0.0", port=0)


def test_server_path_allowlist_rejects_unknown_path(smoke_session: TrendlineResearchNotebookSession) -> None:
    server = make_server(smoke_session.viewer_bundle_path, port=0)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{server.server_address[1]}/not-allowed")
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_symlink_bundle_is_rejected(smoke_session: TrendlineResearchNotebookSession, tmp_path) -> None:
    link = tmp_path / "bundle-link"
    link.symlink_to(smoke_session.viewer_bundle_path, target_is_directory=True)
    with pytest.raises(ValueError):
        make_server(link, port=0)


def test_server_marks_payload_no_store(smoke_session: TrendlineResearchNotebookSession) -> None:
    server = make_server(smoke_session.viewer_bundle_path, port=0)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urlopen(f"http://127.0.0.1:{server.server_address[1]}/bundle/chart_payload.json")
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_html_import_map_matches_vendor_route(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    index_html = (VIEWER_WEB_ROOT / "index.html").read_text(encoding="utf-8")
    assert index_html.count('<script type="importmap">') == 1
    assert '"lightweight-charts": "/vendor/lightweight-charts.mjs"' in index_html

    compiled_main = (VIEWER_WEB_ROOT / "dist" / "main.js").read_text(encoding="utf-8")
    assert (
        'from "lightweight-charts"' in compiled_main
        or "from 'lightweight-charts'" in compiled_main
    )

    vendor_path = (
        VIEWER_WEB_ROOT
        / "node_modules"
        / "lightweight-charts"
        / "dist"
        / "lightweight-charts.standalone.production.mjs"
    )
    expected_vendor = vendor_path.read_bytes()
    assert expected_vendor

    server = make_server(smoke_session.viewer_bundle_path, port=0)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        served_html = urlopen(f"{base_url}/").read().decode("utf-8")
        served_vendor = urlopen(f"{base_url}/vendor/lightweight-charts.mjs").read()
        assert served_html == index_html
        assert served_vendor == expected_vendor
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
