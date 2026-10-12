# Validation — 12 October 2026, version 0.4.0

- 61 Python tests and 6 JavaScript tests passed locally.
- Release builds reject demo creation and omit stored demo analyses from navigation.
  Development builds retain examples. Existing demo data is preserved.
- English interface, analysis terminology, wildcard HA search, input/output selection,
  independent history and forecasts, interval aggregation and data contracts are covered.
- Browser checks used 120 synthetic analysis records. Search found an analysis beyond
  the first page, Running filtering returned six records, and Show 50 more expanded
  the list from 50 to 100. Collapsing survived reload and exposed the full canvas.
- The local ARM64 container builds, starts and preserves its existing data volume.
- Previous validation covered training/prediction, purged holdout evaluation, signal
  dragging and connections, HA Ingress routes, CSV imports, time zones and persistence.

Browser fixtures and examples are synthetic. No real Home Assistant connection,
actual sensor history, HA publication or real-world forecast accuracy was validated
for this change. No Home Assistant server configuration was changed.

The test client reports a deprecation warning about its httpx adapter; tests pass.
