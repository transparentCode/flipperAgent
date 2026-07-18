"""Compatibility CLI facade for ATR calibration."""

from libs.models.sr.research.studies.atr_calibration.cli import _parser, main  # noqa: F401

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
