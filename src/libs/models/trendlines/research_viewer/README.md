# Mature Trendlines Research Viewer

`libs.models.trendlines.research_viewer` is a presentation-only leaf for validated
L2-A2 replay and evidence contracts. It does not fetch data, resolve configuration,
execute models, construct history, or build diagnostic rows.

The package creates strict `trendlines_research_viewer_payload_v1` payloads and
explicit two-file `trendlines_research_viewer_bundle_v1` bundles. Its server binds
only to loopback and serves one validated bundle with `Cache-Control: no-store`.

Default notebook mode is deterministic synthetic smoke data. Binance mode requires
an explicit research spec, injected loader, and provider authorization. Permanent
evidence or viewer export is always explicit.

```bash
npm ci
npm run build
```
