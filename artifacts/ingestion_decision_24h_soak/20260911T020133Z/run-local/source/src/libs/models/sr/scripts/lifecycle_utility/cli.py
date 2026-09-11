"""Compatibility CLI facade for lifecycle utility."""

from libs.models.sr.research.studies.lifecycle_utility.cli import _parser, main  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
