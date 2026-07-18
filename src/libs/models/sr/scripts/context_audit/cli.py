"""Compatibility CLI facade for context audit."""

from libs.models.sr.research.studies.context_audit.cli import _parser, main  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
