"""Package-local presentation layer for validated mature-trendlines research."""

from .bundle import read_viewer_bundle, validate_viewer_bundle, write_viewer_bundle
from .contracts import (
    VIEWER_BUNDLE_SCHEMA_VERSION,
    VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION,
    VIEWER_PAYLOAD_SCHEMA_VERSION,
    TrendlineViewerContractError,
    TrendlineViewerSpec,
)
from .payload import build_trendlines_viewer_payload, validate_viewer_payload


def __getattr__(name: str):
    if name in {
        "TrendlineResearchNotebookSession",
        "default_replay_spec",
        "default_synthetic_research_spec",
        "run_research_notebook_session",
    }:
        from . import notebook_support

        return getattr(notebook_support, name)
    if name in {"TrendlinesResearchViewerSession", "make_server"}:
        from . import server

        return getattr(server, name)
    raise AttributeError(name)

__all__ = [
    "VIEWER_BUNDLE_SCHEMA_VERSION",
    "VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION",
    "VIEWER_PAYLOAD_SCHEMA_VERSION",
    "TrendlineResearchNotebookSession",
    "TrendlineViewerContractError",
    "TrendlineViewerSpec",
    "TrendlinesResearchViewerSession",
    "build_trendlines_viewer_payload",
    "default_replay_spec",
    "default_synthetic_research_spec",
    "make_server",
    "read_viewer_bundle",
    "run_research_notebook_session",
    "validate_viewer_bundle",
    "validate_viewer_payload",
    "write_viewer_bundle",
]
