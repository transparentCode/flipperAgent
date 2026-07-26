import asyncio

import pytest

from libs.models.trendlines.research_viewer import TrendlineViewerContractError
from libs.models.trendlines.research_viewer.notebook_support import (
    run_research_notebook_session,
)
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
)


def test_synthetic_notebook_support_run_is_network_free() -> None:
    result = asyncio.run(run_research_notebook_session(start_viewer=False))
    try:
        assert result.prepared.spec.data.mode is TrendlineResearchDataMode.SYNTHETIC
        assert result.payload["dataset_id"] == result.prepared.dataset.dataset_id
    finally:
        result.close()


def test_mocked_binance_support_run_uses_explicit_loader() -> None:
    smoke = asyncio.run(run_research_notebook_session(start_viewer=False))
    frame = smoke.prepared.dataset.frames["1h"].copy(deep=True)
    smoke.close()
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=frame.index[0].to_pydatetime(),
            knowledge_cutoff=frame["bar_available_at"].iloc[-1].to_pydatetime(),
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )

    class FakeLoader:
        async def load(self, requested):
            return {"1h": frame}

    result = asyncio.run(
        run_research_notebook_session(
            spec,
            loader=FakeLoader(),
            provider_calls_authorized=True,
            start_viewer=False,
        )
    )
    try:
        assert result.prepared.spec.purpose is TrendlineResearchPurpose.RESEARCH
        assert result.prepared.dataset.identity.availability_sources["1h"].value == "fixed_interval_derived"
    finally:
        result.close()


def test_binance_authorisation_rejects_before_loader() -> None:
    smoke = asyncio.run(run_research_notebook_session(start_viewer=False))
    frame = smoke.prepared.dataset.frames["1h"]
    smoke.close()
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=frame.index[0].to_pydatetime(),
            knowledge_cutoff=frame["bar_available_at"].iloc[-1].to_pydatetime(),
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    called = False

    async def forbidden_loader(_):
        nonlocal called
        called = True
        raise AssertionError("loader must not be called")

    with pytest.raises(TrendlineViewerContractError):
        asyncio.run(run_research_notebook_session(spec, loader=forbidden_loader))
    assert called is False


def test_non_binance_provider_authorisation_is_rejected() -> None:
    with pytest.raises(TrendlineViewerContractError):
        asyncio.run(run_research_notebook_session(provider_calls_authorized=True))
