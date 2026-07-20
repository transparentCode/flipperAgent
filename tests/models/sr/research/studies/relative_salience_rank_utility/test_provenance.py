"""V2.4 source/evaluation provenance fails closed before publication."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.relative_salience_rank_utility import cli
from libs.models.sr.research.studies.relative_salience_rank_utility.artifacts import (
    publish_evaluation_bundle,
    validate_evaluation_bundle,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.config import (
    COHORTS,
    load_relative_salience_rank_config,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.contracts import (
    IntervalBar,
    RankDisposition,
    RankStudy,
    SourceBundle,
    SourceMember,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.runner import compute_study


UTC = timezone.utc
SOURCE_COMMIT = "a" * 40
LATER_COMMIT = "b" * 40


def _config():
    return load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")


def _source_bundle() -> SourceBundle:
    start = datetime(2025, 12, 31, tzinfo=UTC)
    members = []
    for asset, timeframe in COHORTS:
        cadence = timedelta(days=1) if timeframe == "1d" else timedelta(hours=12)
        bar = IntervalBar(
            start,
            start + cadence,
            100.0,
            101.0,
            99.0,
            100.0,
            1.0,
            f"binance_usdm:{asset}:{timeframe}:{int(start.timestamp() * 1000)}",
        )
        members.append(SourceMember(asset, timeframe, (bar,), (), 0, "frozen_history"))
    return SourceBundle(SOURCE_COMMIT, _config().config_hash, tuple(members))


def test_compute_study_rejects_source_evaluation_implementation_mismatch(monkeypatch) -> None:
    source = _source_bundle()
    monkeypatch.setattr(
        "libs.models.sr.research.studies.relative_salience_rank_utility.runner._member_cases",
        lambda _member: pytest.fail("case computation must not begin after provenance rejection"),
    )
    with pytest.raises(ContractValidationError, match="V2.4 source/evaluation implementation identity mismatch"):
        compute_study(_config(), source_bundle=source, implementation_commit=LATER_COMMIT)


def test_evaluate_rejects_later_implementation_without_publication(monkeypatch) -> None:
    source = _source_bundle()
    published = []
    monkeypatch.setattr(cli, "load_relative_salience_rank_config", lambda _path: _config())
    monkeypatch.setattr(cli, "load_source_bundle", lambda _path: source)
    monkeypatch.setattr(cli, "repository_commit", lambda _root: LATER_COMMIT)
    monkeypatch.setattr(cli, "publish_evaluation_bundle", lambda *_args, **_kwargs: published.append(True))

    with pytest.raises(ContractValidationError, match="V2.4 source/evaluation implementation identity mismatch"):
        cli.main(["evaluate", "--source", "ignored"])
    assert published == []


def test_validate_uses_frozen_source_commit_from_later_docs_head(monkeypatch, capsys) -> None:
    source = _source_bundle()
    received = []
    monkeypatch.setattr(cli, "load_relative_salience_rank_config", lambda _path: _config())
    monkeypatch.setattr(cli, "load_source_bundle", lambda _path: source)
    monkeypatch.setattr(cli, "repository_commit", lambda _root: pytest.fail("validate must not resolve current repository HEAD"))
    monkeypatch.setattr(
        cli,
        "validate_evaluation_bundle",
        lambda *_args, **kwargs: received.append(kwargs["implementation_commit"]) or SimpleNamespace(study_id="study-id"),
    )

    assert cli.main(["validate", "--source", "ignored", "--evaluation", "ignored"]) == 0
    assert received == [SOURCE_COMMIT]
    assert capsys.readouterr().out == "study-id\n"


def test_validate_rejects_evaluation_implementation_disagreeing_with_source(tmp_path) -> None:
    config = _config()
    source = _source_bundle()
    forged = RankStudy(
        LATER_COMMIT,
        config.config_hash,
        source.bundle_id,
        (),
        (),
        RankDisposition.INSUFFICIENT_SOURCE_DENSITY,
        {},
    )
    _, path = publish_evaluation_bundle(forged, config=config, output_root=tmp_path)

    with pytest.raises(ContractValidationError, match="V2.4 evaluation implementation identity mismatch"):
        validate_evaluation_bundle(
            path,
            config=config,
            source_bundle=source,
            implementation_commit=source.implementation_commit,
        )
