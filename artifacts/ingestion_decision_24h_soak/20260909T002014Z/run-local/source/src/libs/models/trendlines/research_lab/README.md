# Mature Trendlines Research Lab

`libs.models.trendlines.research_lab` is a thin workbench layer for the mature
trendlines package. It composes validated research preparation, causal replay,
evidence, and package-local viewer APIs. It does not implement model stages,
configuration resolution, replay, diagnostics, or chart rendering.

The dependency direction is:

```text
research/trendlines_research_lab.ipynb
        -> libs.models.trendlines.research_lab
        -> workflows.research and research_viewer
```

Synthetic, injected, and explicitly authorised Binance controls are supported.
Model parameters remain resolved from canonical YAML. The lab never writes YAML,
fetches data implicitly, or performs provider calls for synthetic smoke mode.

Navigation selects recorded evidence and rebuilds a viewer payload without
rerunning replay. Tables retain full identities and knowledge-time metadata.
Viewer servers and temporary bundles are owned by `TrendlineResearchLabSession`
and are closed by `session.close()`. Close is terminal for selection and viewer
creation; repeated close is safe. Provider accounting is read after preparation
from validated `provider_calls` (with explicit compatibility `calls` support),
and Binance runs fail closed when accounting is unavailable.

Notebook table construction uses a presentation-only timing accumulator.
Explicit export inventory expands evidence files, viewer manifest/payload files,
and lab manifest into byte-length and lowercase SHA-256 rows. Permanent export
remains opt-in.

Available studies cover causal replay inspection, pivots, fitted lines, boundary
rays, native signals, position comparison, performance, and explicit evidence
export. Longevity, churn, null comparison, sensitivity, robustness, cross-asset
adequacy, and predictive outcomes remain L2-D work. RSI/MACD and
price/oscillator confluence remain a separate programme.
