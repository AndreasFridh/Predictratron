# Predictratron

A local time-series ML app for Home Assistant. Connect input signals to an ML
box, train each independent model on its own history, and predict future values.

[![Add to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FAndreasFridh%2FPredictratron)

## Install in Home Assistant

1. Open **Settings → Apps → App store** (called **Add-ons** in older versions).
2. Open **⋮ → Repositories** and add:
   `https://github.com/AndreasFridh/Predictratron`
3. Find **Predictratron**, choose **Install**, then **Start**.
4. Choose **Open web UI**. Enable **Show in sidebar** if desired.

Requires Home Assistant OS or a Supervisor-based installation, on `aarch64` or
`amd64`. The first installation builds the image locally and can take several
minutes. No separate Home Assistant URL or token is needed: the app uses its own
Supervisor-issued credential. No network port is published; access is through
Home Assistant Ingress.

## What it does

- Search HA signals by name/entity-id with `*` and `?` wildcards, type filters and latest values.
- Drag-and-drop signals shown as **○ – Name (Datatype)**.
- Independent model instances with separate history, training, scores and forecasts.
- Explicit **Train on history** and **Predict future** actions in each ML box.
- Minute, hour, day, week or custom fixed intervals.
- Per-signal mean, last value, CSV sum or cumulative-meter increment.
- Home Assistant sensor history or CSV with automatic reduction to complete periods.
- Chronological holdout evaluation against simple baseline forecasts.
- Models and training files persist in `/data` and are included in app backups.
- Optional automatic history refresh/retraining; manual forecast publication to HA.

Examples include temperature → hourly consumption, or rainfall + week → soil
water level. Inputs currently use observed history; future weather forecasts are
not yet consumed. Calendar months/years and categorical outputs are not yet
supported. The app is experimental; synthetic demos show the workflow rather
than real-world accuracy.

See [usage and data semantics](predictratron/DOCS.md) and
[validation](predictratron/VALIDATION.md).

## Standalone Docker

```sh
cd predictratron
docker compose up -d --build
```

Open `http://localhost:8080`. Standalone deployment can use `.env.example` for
an external HA connection. The HA app and standalone installations store their
data separately.

## Development

```sh
cd predictratron
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --test tests/js/*.test.cjs
```

Home Assistant packaging follows the official
[app configuration](https://developers.home-assistant.io/docs/apps/configuration/),
[Ingress](https://developers.home-assistant.io/docs/apps/presentation/#ingress), and
[Core API proxy](https://developers.home-assistant.io/docs/apps/communication/#home-assistant-core)
documentation.
