# Changelog

## 0.2.0

- Package Predictratron as a Home Assistant app for aarch64 and amd64.
- Add Home Assistant Ingress with path-aware static assets/API requests.
- Use the app's Supervisor credential for HA REST and WebSocket history.
- Preserve each instance's history, training files and forecasts in app data.
- Drop runtime privileges after preparing the Supervisor data volume.
- Include drag-and-drop signals, independent ML instances and two-step train/predict.
- Support minute, hour, day, week and custom fixed periods with complete-period aggregation.
