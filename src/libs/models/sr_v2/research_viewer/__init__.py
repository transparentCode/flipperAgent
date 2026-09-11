"""Local-only structural research viewer."""

from .bundle import (
    build_viewer_payload,
    iframe_urls,
    validate_viewer_bundle,
    write_viewer_bundle,
)
from .server import (
    SRV2ResearchViewerSession,
    create_owned_viewer_workspace,
    make_server,
)

__all__ = [
    "SRV2ResearchViewerSession",
    "build_viewer_payload",
    "create_owned_viewer_workspace",
    "iframe_urls",
    "make_server",
    "validate_viewer_bundle",
    "write_viewer_bundle",
]
