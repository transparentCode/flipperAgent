"""Compatibility CLI facade for candidate reinforcement audit."""

from libs.models.sr.research.studies.candidate_reinforcement_audit.cli import _parser, main  # noqa: F401


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
