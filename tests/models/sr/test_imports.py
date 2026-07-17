from __future__ import annotations

import libs.models.sr as sr


def test_package_imports() -> None:
    assert sr.ZoneSide.SUPPORT == "SUPPORT"
    assert sr.ZoneStatus.ACTIVE == "ACTIVE"
    assert sr.SREventType.CREATED == "CREATED"


def test_all_public_names_are_reachable() -> None:
    for name in sr.__all__:
        assert hasattr(sr, name), name
