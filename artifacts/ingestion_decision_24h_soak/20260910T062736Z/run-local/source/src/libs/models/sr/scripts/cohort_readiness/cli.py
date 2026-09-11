"""Compatibility CLI facade for cohort readiness."""

from libs.models.sr.research.studies.cohort_readiness.cli import _parser, main  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
