# Changelog

## 0.4.0

- Use English throughout the interface and user-facing errors.
- Rename workspaces to analysis flows, with Save analysis and New analysis actions.
- Add a persistent collapsible sidebar, analysis search, status filters and bounded lists.
- Hide demo analyses and disable demo creation in release builds; enable with APP_BUILD=development.
- Preserve existing analysis histories, model artifacts and user-defined names.

## 0.3.1

- Remove the data source selector from ML box settings.
- Derive HA/CSV history from connected signal mappings, preserving synthetic demos.
- Reject unsupported mixed HA/CSV connections; disconnected nodes do not affect the source.

## 0.3.0

- Replace the long Home Assistant signal list with a searchable signal picker.
- Support literal name/entity-id search and * / ? wildcards, signal type filters and bounded results.
- Show latest values, units, update timestamps and unknown/unavailable states.
- Refresh values on opening the picker or on request; use the same picker for inputs and output.

## 0.2.0

- Package Predictratron as a Home Assistant app for aarch64 and amd64.
- Add Home Assistant Ingress with path-aware static assets/API requests.
- Use the app's Supervisor credential for HA REST and WebSocket history.
- Preserve each instance's history, training files and forecasts in app data.
- Drop runtime privileges after preparing the Supervisor data volume.
- Include drag-and-drop signals, independent ML instances and two-step train/predict.
- Support minute, hour, day, week and custom fixed periods with complete-period aggregation.
