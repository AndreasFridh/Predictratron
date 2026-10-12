import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import numpy as np
import pandas as pd
from websockets.sync.client import connect

from .engine import aggregate_periods


def numeric(value):
    if value == "on":
        return 1.0
    if value == "off":
        return 0.0
    try:
        result = float(value)
        return result if np.isfinite(result) else np.nan
    except (ValueError, TypeError):
        return np.nan


def statistic_frame(data, spec, end, input_minutes=60):
    series = []
    for signal in spec.signals:
        values = {}
        field = {"mean": "mean", "last": "state", "change": "change"}[signal.statistic]
        for row in data.get(signal.entity_id, []):
            # HA's websocket statistics use UTC epoch milliseconds.
            stamp = pd.to_datetime(row["end"], unit="ms", utc=True)
            if stamp <= end:
                values[stamp] = numeric(row.get(field))
        series.append(pd.Series(values, name=signal.key, dtype=float))
    frame = pd.concat(series, axis=1).sort_index()
    if frame.empty:
        return frame
    if spec.step_minutes != input_minutes:
        frame = aggregate_periods(frame, spec, input_minutes)
    return frame.loc[frame.index <= end].dropna(how="all")


def raw_frame(records, signal, start, end, freq, anchor=None):
    """Time-weighted state means / last-known values, preserving unavailable gaps."""
    observations = {}
    for row in records:
        stamp = pd.Timestamp(row.get("last_updated") or row.get("last_changed"))
        if stamp.tzinfo is not None and stamp <= end:
            observations[stamp.tz_convert("UTC")] = numeric(row.get("state"))
    if not observations:
        return pd.Series(dtype=float, name=signal.key)
    states = pd.Series(observations, dtype=float).sort_index()
    ends = pd.date_range(start + pd.Timedelta(freq), end, freq=freq, tz="UTC")
    if signal.statistic == "last":
        # Index the original states, including their explicit unavailable NaNs.
        # A change exactly at the boundary belongs to the following period.
        indices = states.index.searchsorted(ends, side="left") - 1
        values = [states.iloc[i] if i >= 0 else np.nan for i in indices]
        return pd.Series(values, index=ends, name=signal.key)
    boundaries = pd.DatetimeIndex(sorted(set([start, end, *ends, *states.index[(states.index > start) & (states.index < end)]])))
    left = boundaries[:-1]
    duration = (boundaries[1:] - left).total_seconds()
    positions = states.index.searchsorted(left, side="right") - 1
    values = np.array([states.iloc[i] if i >= 0 else np.nan for i in positions])
    origin = anchor if anchor is not None else pd.Timestamp("1970-01-01", tz="UTC")
    step = pd.Timedelta(freq)
    labels = origin + ((left - origin) // step + 1) * step
    pieces = pd.DataFrame({"weighted": np.nan_to_num(values) * duration,
                           "known": np.where(np.isfinite(values), duration, 0)}, index=labels)
    grouped = pieces.groupby(level=0).sum()
    period_seconds = pd.Timedelta(freq).total_seconds()
    result = (grouped["weighted"] / grouped["known"]).where(grouped["known"] >= period_seconds - 0.001)
    return result.reindex(ends).rename(signal.key)


class HAClient:
    def __init__(self, url=None, token=None):
        default_url = "http://supervisor/core" if os.getenv("SUPERVISOR_TOKEN") else ""
        self.url = (url if url is not None else os.getenv("HA_URL", default_url)).rstrip("/")
        if token is not None:
            self.token = token
        else:
            token_file = os.getenv("HA_TOKEN_FILE")
            self.token = Path(token_file).read_text().strip() if token_file else os.getenv("HA_TOKEN", os.getenv("SUPERVISOR_TOKEN", ""))
        self.ca_file = os.getenv("HA_CA_FILE") or None

    @property
    def configured(self):
        return bool(self.url and self.token)

    def require(self):
        if not self.configured:
            raise ValueError("Home Assistant is not connected. Set HA_URL and HA_TOKEN_FILE or HA_TOKEN in the container.")
        parts = urlsplit(self.url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
            raise ValueError("HA_URL must be an HTTP(S) URL without embedded credentials")

    def request(self, method, path, **kwargs):
        self.require()
        try:
            verify = ssl.create_default_context(cafile=self.ca_file)
            with httpx.Client(timeout=60, verify=verify, headers={"Authorization": f"Bearer {self.token}"}) as client:
                response = client.request(method, f"{self.url}/api/{path.lstrip('/')}", **kwargs)
            if response.status_code >= 400:
                raise ValueError(f"Home Assistant returned HTTP {response.status_code}")
            return response.json()
        except httpx.RequestError as exc:
            raise ValueError("Cannot connect to Home Assistant. Check the URL, network and certificate.") from exc

    def websocket(self, command):
        self.require()
        parts = urlsplit(self.url)
        path = parts.path + ("/websocket" if parts.hostname == "supervisor" and parts.path == "/core" else "/api/websocket")
        url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, path, "", ""))
        options = {"ssl": ssl.create_default_context(cafile=self.ca_file)} if parts.scheme == "https" else {}
        try:
            with connect(url, open_timeout=20, max_size=32 * 1024 * 1024, **options) as ws:
                hello = json.loads(ws.recv(timeout=60))
                if hello.get("type") != "auth_required":
                    raise ValueError("Unexpected Home Assistant response")
                ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth = json.loads(ws.recv(timeout=60))
                if auth.get("type") != "auth_ok":
                    raise ValueError("Home Assistant rejected API authentication")
                ws.send(json.dumps({"id": 1, **command}))
                while True:
                    response = json.loads(ws.recv(timeout=90))
                    if response.get("id") == 1:
                        if not response.get("success"):
                            raise ValueError("Cannot fetch HA statistics; check sensors and permissions")
                        return response["result"]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Home Assistant statistics connection failed") from exc

    def entities(self):
        result = []
        for state in self.request("GET", "states"):
            if state["entity_id"].startswith(("sensor.", "binary_sensor.", "input_number.")):
                attributes = state.get("attributes", {})
                result.append({"entity_id": state["entity_id"], "name": attributes.get("friendly_name", state["entity_id"]),
                               "unit": attributes.get("unit_of_measurement", ""),
                               "state_class": attributes.get("state_class"), "state": state["state"],
                               "last_updated": state.get("last_updated"), "last_changed": state.get("last_changed")})
        return result

    def history(self, spec):
        end = spec.floor(pd.Timestamp.now(tz="UTC"))
        start = spec.floor(end - pd.Timedelta(days=spec.history_days))
        if (end - start) / pd.Timedelta(spec.freq) > 200_000:
            raise ValueError("Selected history exceeds 200,000 intervals. Shorten history or use longer intervals.")
        base_minutes = 60 if spec.step_minutes % 60 == 0 else 5 if spec.step_minutes % 5 == 0 else None
        data = self.websocket({"type": "recorder/statistics_during_period", "start_time": start.isoformat(),
                               "end_time": end.isoformat(), "statistic_ids": sorted(set(s.entity_id for s in spec.signals)),
                               "period": "hour" if base_minutes == 60 else "5minute", "types": ["mean", "state", "change"]}) if base_minutes else {}
        frame = statistic_frame(data, spec, end, base_minutes) if base_minutes else pd.DataFrame(columns=[s.key for s in spec.signals])
        for signal in spec.signals:
            if not frame.empty and frame[signal.key].notna().any():
                continue
            if signal.statistic == "change":
                raise ValueError(f"{signal.entity_id} has no increment statistics. Use a registered cumulative meter.")
            # Binary sensors and 'last' on measurement sensors may have no
            # long-term statistics. Their available raw state history is used.
            groups = self.request("GET", "history/period/" + start.isoformat(), params={
                "filter_entity_id": signal.entity_id, "end_time": end.isoformat(),
                "no_attributes": "true", "significant_changes_only": "false"})
            records = groups[0] if groups else []
            raw = raw_frame(records, signal, start, end, spec.freq, spec.anchor)
            frame = frame.reindex(frame.index.union(raw.index))
            frame[signal.key] = raw
        for signal in spec.signals:
            if frame.empty or not frame[signal.key].notna().any():
                raise ValueError(f"No usable history for {signal.entity_id}. Check statistics type and Recorder.")
        frame = frame.sort_index().dropna(how="all")
        return frame

    def publish(self, model_id, spec, forecast):
        first = forecast["points"][0]
        entity = f"sensor.ml_{model_id}"
        self.request("POST", "states/" + entity, json={"state": round(first["value"], 4), "attributes": {
            "friendly_name": spec.name + " · prognos", "unit_of_measurement": spec.unit,
            "forecast_start": first["start"], "forecast_end": first["end"],
            "issued_at": forecast["issued_at"], "forecast": forecast["points"],
            "warning": forecast["warning"], "icon": "mdi:chart-timeline-variant"}})
        return entity
