"""Artifact publication and validation primitives shared by SR studies."""

from __future__ import annotations

from .path_safety import reject_symlink_components, require_regular_file

__all__ = ["reject_symlink_components", "require_regular_file"]
