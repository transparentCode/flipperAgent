"""Compatibility CLI facade for baseline adequacy."""

from libs.models.sr.research.studies.baseline_adequacy.cli import _parser, main  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
