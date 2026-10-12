# Predictratron — analysis flows

Predictratron trains independent time-series models and predicts future numeric values.
Each analysis flow has its own signal graph, history, trained model and forecasts.

## Navigation

Expand or collapse the sidebar with the menu button. Its state is remembered in
this browser. The collapsed sidebar leaves more room for the canvas and still
lets you create a new analysis. Search by analysis name or ID, or filter by
Running, Trained, Needs training and Error. Lists show 50 analyses at a time;
use **Show 50 more** to display more results.

## Create an analysis

1. Choose **New analysis** for an independent canvas with an ML box.
2. Add input signals and an output from **Signals**. Drag or click to add them.
3. Open signal settings and choose a HA sensor or CSV column, name and data type.
4. Connect input ports to ML, then connect ML to the output signal.
5. Set the interval, forecast horizon and history window in **ML settings**.
6. Choose **Save analysis**, then fetch HA history or import CSV.
7. Choose **Train on history**, followed by **Predict future**.
8. Open **Results** for forecasts, validation errors and comparison with a baseline.

Signals determine the history source. All connected measurement signals must
map to HA sensors, or all must be CSV columns without HA mappings. Mixed HA/CSV
history is not supported yet. Calendar and disconnected signals do not affect
the source. Changing a target, interval or historical signal contract after
import requires **Save as new analysis** to preserve existing history.

## Search HA signals

Use **Search HA signals** in the palette or **Search** beside a signal mapping.
Search a name or entity ID. Plain text finds a substring, ignoring case.
Wildcards match the whole name or ID: `*` means any characters and `?` one
character. Examples: `sensor.*temp*`, `*kitchen*`, `sensor.energ?`.

Results show the latest value, unit and update timestamp in the browser's time
zone. Filter by sensor type. Results show 50 rows at a time. Values refresh when
the picker opens and with **Refresh values**; they are snapshots, not a live feed.
Unknown/unavailable sensors can have historical data. Text sensors cannot be
selected; Boolean signals are supported only as inputs.

## Intervals and aggregation

Minute, hour, day, week and custom fixed intervals (1–525,600 minutes) are
supported. Training and forecasting use the same interval. Weeks start Monday
00:00 UTC. Calendar months and years are not supported. Interval timestamps label
the end of each interval. Calendar features use the analysis time zone.

Each signal can use mean or latest value. CSV interval values can be summed.
Cumulative HA meters use reset-adjusted increments, requiring intervals divisible
by five minutes. CSV may specify its original interval; only complete finished
periods are aggregated. Upsampling, duplicate timestamps and infinite values are
rejected. CSV timestamps need a time zone, and files must be at most 20 MB.

## Training and quality

The model uses lagged observed signals, rolling windows, calendar features and
optional target history. Future weather forecasts are not yet inputs. Validation
uses later history and removes overlapping future targets. Compare the model's
MAE with its baseline; a model can perform worse than a simple latest-value forecast.
The displayed band reflects historical error magnitude, not guaranteed coverage.

Training does not create a forecast. Prediction uses the saved trained model
without retraining. Each analysis retains its own history and model artifact.
Predictive changes require retraining. Stale history must be refreshed before
forecasting. History requests support up to 3,650 days and 200,000 intervals,
subject to data retained by Home Assistant.

Automatic refresh is opt-in for HA analyses. Every 15 minutes it checks enabled
analyses, fetches history and updates local forecasts, retraining after the chosen
number of days. HA publication is manual and uses REST state creation, not a
registered persistent integration. Forecasts are not actual energy consumption
and should not be added as consumption in the Energy Dashboard.

## Installation and persistence

Add `https://github.com/AndreasFridh/Predictratron` to the HA app store repository
list. Install Predictratron, start it, and open its web UI. HA OS or Supervisor on
amd64 or aarch64 is required. The app uses its own Supervisor credential and
Ingress. No separate HA URL or token is needed. History and model artifacts are
stored in `/data` and included in app backups.

For standalone Docker, run `docker compose up -d --build` in this directory.
Open `http://localhost:8080`. Use `.env.example` for external HA connectivity.
Keep API credentials on the server. `HA_TOKEN_FILE` can reference a mounted secret;
`HA_CA_FILE` can reference a trusted CA. Standalone access can require `APP_TOKEN`.
The Compose data volume persists across container replacement.

## Development builds and examples

Release builds hide synthetic demo analyses and reject demo creation. Existing
stored demo data is preserved. To enable examples in a local development build:

```sh
APP_BUILD=development docker compose up -d --build
```

Alternatively, build with `docker build --build-arg APP_BUILD=development`.
Regular builds default to `APP_BUILD=release`. Synthetic examples demonstrate the
workflow and do not indicate accuracy in your home. The interface is English;
user-provided analysis names, labels and HA sensor names are preserved.
