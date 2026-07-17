"""Compatibility CLI facade for baseline trial."""

from libs.models.sr.research.studies.baseline_trial.cli import _parser, main  # noqa: F401

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
