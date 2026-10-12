import io
import math
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline

from .config import ModelSpec


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def parse_csv(content: bytes, spec: ModelSpec, input_minutes=None):
    try:
        frame = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise ValueError("Cannot read CSV. Use comma separators.") from exc
    columns = [s.key for s in spec.signals]
    missing = set(["timestamp", *columns]) - set(frame.columns)
    if missing:
        raise ValueError("CSV is missing columns: " + ", ".join(sorted(missing)))
    # Naive timestamps are rejected to avoid silent DST and local-time errors.
    try:
        stamps = [pd.Timestamp(x) for x in frame["timestamp"]]
        if any(s.tzinfo is None or pd.isna(s) for s in stamps):
            raise ValueError()
        frame.index = pd.to_datetime(stamps, utc=True)
    except Exception as exc:
        raise ValueError("timestamp needs a time zone, for example 2026-10-11T09:00:00Z") from exc
    if frame.index.has_duplicates:
        raise ValueError("CSV contains duplicate timestamps")
    input_minutes = spec.step_minutes if input_minutes is None else input_minutes
    if input_minutes < 1 or spec.step_minutes % input_minutes:
        raise ValueError("CSV interval must evenly divide the ML interval. Upsampling is not supported.")
    source_spec = spec.model_copy(update={"resolution": "custom", "period_minutes": input_minutes})
    if not (frame.index == source_spec.floor(frame.index)).all():
        raise ValueError("Timestamps must align with the selected CSV interval boundaries in UTC")
    if frame.empty or len(frame) > 200_000:
        raise ValueError("CSV needs 1–200,000 rows")
    selected = frame[columns].copy()
    for col in columns:
        try:
            selected[col] = pd.to_numeric(selected[col], errors="raise")
        except Exception as exc:
            raise ValueError(f"{col} must contain numeric values or empty fields") from exc
        if np.isinf(selected[col]).any():
            raise ValueError(f"{col} contains infinite values")
    if not selected[spec.target.key].notna().any():
        raise ValueError("Target column has no measurements")
    current = source_spec.floor(pd.Timestamp.now(tz="UTC"))
    if (selected.index > current).any():
        raise ValueError("History cannot contain future measurements")
    selected = selected.sort_index()
    if input_minutes != spec.step_minutes:
        selected = aggregate_periods(selected, spec, input_minutes)
        if selected.empty:
            raise ValueError("CSV contains no complete finished intervals. Import longer history or choose a shorter interval.")
    return selected


def aggregate_periods(frame, spec, input_minutes):
    """Aggregate complete end-labelled source periods; never invent missing data."""
    if spec.step_minutes % input_minutes:
        raise ValueError("Source interval must evenly divide the analysis interval")
    expected = spec.step_minutes // input_minutes
    result = {}
    for signal in spec.signals:
        grouped = frame[signal.key].resample(spec.freq, closed="right", label="right", origin=spec.anchor)
        if signal.statistic in {"change", "sum"}:
            reduced = grouped.sum(min_count=expected)
        elif signal.statistic == "last":
            reduced = grouped.last()
        else:
            reduced = grouped.mean()
        result[signal.key] = reduced.where(grouped.count() == expected)
    current = spec.floor(pd.Timestamp.now(tz="UTC"))
    return pd.DataFrame(result).loc[lambda x: x.index <= current].dropna(how="all")


def grid(frame, spec):
    frame = frame.sort_index()
    current = spec.floor(pd.Timestamp.now(tz="UTC"))
    frame = frame.loc[frame.index <= current]
    if frame.empty:
        raise ValueError("No completed measurement intervals")
    # Every row describes the period ENDING at timestamp; gaps stay missing.
    start, end = frame.index.min(), frame.index.max()
    count = int((end - start) / pd.Timedelta(spec.freq)) + 1
    if count > 200_000:
        raise ValueError("History exceeds 200,000 measurement intervals")
    return frame.reindex(pd.date_range(start, end, freq=spec.freq, tz="UTC"))


def features(frame, spec):
    fields = [s.key for s in spec.inputs]
    if spec.use_target_history:
        fields.append(spec.target.key)
    columns = {}
    for key in fields:
        series = frame[key]
        for lag in spec.lags:
            columns[f"{key}:lag:{lag}"] = series.shift(lag)
        for window in spec.windows:
            rolling = series.rolling(window, min_periods=window)
            columns[f"{key}:mean:{window}"] = rolling.mean()
            columns[f"{key}:sum:{window}"] = rolling.sum()
    local = frame.index.tz_convert(spec.timezone)
    times = {
        "hour": (local.hour.to_numpy(), 24),
        "weekday": (local.dayofweek.to_numpy(), 7),
        "week": (local.isocalendar().week.to_numpy(dtype=float) - 1, 53),
        "year_day": (local.dayofyear.to_numpy() - 1, 365.25),
    }
    for name in spec.calendar:
        values, period = times[name]
        columns[f"calendar:{name}:sin"] = np.sin(2 * np.pi * values / period)
        columns[f"calendar:{name}:cos"] = np.cos(2 * np.pi * values / period)
    return pd.DataFrame(columns, index=frame.index)


def estimator():
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        RandomForestRegressor(n_estimators=96, max_depth=16, min_samples_leaf=2, n_jobs=1, random_state=42),
    )


def clip(values, spec):
    if spec.target.data_type == "int":
        values = np.rint(values)
    return np.clip(values, spec.minimum if spec.minimum is not None else -np.inf,
                   spec.maximum if spec.maximum is not None else np.inf)


def train(frame, spec):
    frame = grid(frame, spec)
    for signal in spec.inputs:
        if not frame[signal.key].notna().any():
            raise ValueError(f"History missing for {signal.key}. Fetch or import history for the new signal.")
    x = features(frame, spec)
    target = frame[spec.target.key]
    y = pd.concat([target.shift(-h).rename(str(h)) for h in range(1, spec.horizon + 1)], axis=1)
    # Inputs may be imputed; observed training labels never are.
    valid = y.notna().all(axis=1) & target.notna()
    valid.iloc[:spec.warmup] = False
    x, y = x.loc[valid], y.loc[valid]
    if len(x) < 100:
        raise ValueError(f"Only {len(x)} usable forecast origins. At least 100 are needed after lags, gaps and horizon.")
    split = int(len(x) * 0.8)
    test_start = x.index[split]
    train_mask = x.index + pd.Timedelta(hours=spec.horizon * spec.step_hours) < test_start
    x_train, y_train = x.loc[train_mask], y.loc[train_mask]
    x_test, y_test = x.iloc[split:], y.iloc[split:]
    if len(x_train) < 50 or len(x_test) < 20:
        raise ValueError("Insufficient history for validation without overlapping future targets. Fetch more data or shorten the horizon.")
    model = estimator()
    model.fit(x_train, y_train)
    predicted = clip(np.asarray(model.predict(x_test)).reshape(len(x_test), spec.horizon), spec)
    actual = y_test.to_numpy()
    persistence = np.repeat(target.loc[x_test.index].to_numpy()[:, None], spec.horizon, axis=1)
    period = 10080 // spec.step_minutes if 10080 % spec.step_minutes == 0 else 0
    seasonal = persistence.copy()
    for h in range(1, spec.horizon + 1):
        if h <= period:
            previous = target.shift(period - h).reindex(x_test.index).to_numpy()
            seasonal[:, h - 1] = np.where(np.isfinite(previous), previous, seasonal[:, h - 1])
    mae = float(mean_absolute_error(actual, predicted))
    baseline_scores = {"senaste_värde": float(mean_absolute_error(actual, persistence)),
                       "förra_veckan": float(mean_absolute_error(actual, seasonal))}
    baseline_name = min(baseline_scores, key=baseline_scores.get)
    baseline = baseline_scores[baseline_name]
    errors = np.abs(actual - predicted)
    # This is descriptive holdout error, not an independently calibrated interval.
    radii = np.quantile(errors, 0.9, axis=0)
    per_horizon = [{"step": h + 1, "mae": float(errors[:, h].mean()), "error_p90": float(radii[h])}
                   for h in range(spec.horizon)]
    # Tree feature importance has no causal meaning.
    forest = model[-1]
    names = model[0].get_feature_names_out(x.columns)
    groups = {}
    for name, importance in zip(names, forest.feature_importances_):
        group = name.removeprefix("missingindicator_").split(":")[0]
        groups[group] = groups.get(group, 0) + float(importance)
    metrics = {
        "mae": mae, "baseline_mae": baseline, "baseline": baseline_name,
        "baselines": baseline_scores, "beats_baseline": mae < baseline,
        "improvement_percent": 100 * (baseline - mae) / baseline if baseline > 0 else None,
        "training_rows": len(x_train), "test_rows": len(x_test), "usable_rows": len(x),
        "train_last_origin": x_train.index[-1].isoformat(),
        "train_last_target": (x_train.index[-1] + pd.Timedelta(hours=spec.horizon * spec.step_hours)).isoformat(),
        "test_first_origin": test_start.isoformat(), "test_last_origin": x_test.index[-1].isoformat(),
        "per_horizon": per_horizon, "importance": groups,
        "test_preview": [{"timestamp": (stamp + pd.Timedelta(spec.freq)).isoformat(),
                          "actual": float(actual[i, 0]), "predicted": float(predicted[i, 0]),
                          "baseline": float((persistence if baseline_name == "senaste_värde" else seasonal)[i, 0])}
                         for i, stamp in enumerate(x_test.index) if i >= len(x_test) - 120],
    }
    # Refit only after collecting out-of-time validation results.
    final = estimator()
    final.fit(x, y)
    artifact = {"model": final, "columns": list(x.columns), "spec": spec.model_dump(),
                "radii": radii, "trained_at": now_utc(), "metrics": metrics}
    return artifact


def forecast(frame, spec, artifact):
    if spec.signature() != ModelSpec.model_validate(artifact["spec"]).signature():
        raise ValueError("ML settings changed. Retrain the model.")
    frame = grid(frame, spec)
    latest = frame.index[-1]
    now = spec.floor(pd.Timestamp.now(tz="UTC"))
    if now - latest > 2 * pd.Timedelta(spec.freq):
        raise ValueError("History is too old for a current forecast. Fetch new measurements first.")
    if pd.isna(frame[spec.target.key].iloc[-1]):
        raise ValueError("Latest target value is missing. Fetch new measurements first.")
    if len(frame) <= spec.warmup:
        raise ValueError("Insufficient history for selected lags")
    missing = [s.key for s in spec.inputs if pd.isna(frame[s.key].iloc[-1])]
    if missing:
        raise ValueError("Senaste input saknas: " + ", ".join(missing))
    x = features(frame, spec).iloc[[-1]][artifact["columns"]]
    values = clip(np.asarray(artifact["model"].predict(x)).reshape(-1), spec)
    points = []
    for h, value in enumerate(values, 1):
        end = latest + pd.Timedelta(hours=h * spec.step_hours)
        if end <= now:
            continue
        radius = float(artifact["radii"][h - 1])
        lower, upper = clip(np.array([value - radius, value + radius]), spec)
        points.append({"start": (end - pd.Timedelta(spec.freq)).isoformat(), "end": end.isoformat(),
                       "value": float(value), "lower": float(lower), "upper": float(upper)})
    if not points:
        raise ValueError("All forecast intervals have expired. Fetch new history.")
    return {"issued_at": now_utc(), "origin": latest.isoformat(), "unit": spec.unit,
            "resolution": spec.resolution, "period_minutes": spec.step_minutes, "points": points,
            "warning": None if artifact["metrics"]["beats_baseline"] else "The model did not beat the baseline in the latest validation.",
            "interval_note": "The band shows the 90th percentile of absolute validation errors; coverage is not guaranteed."}


def save_artifact(path, artifact):
    temporary = path.with_suffix(".tmp")
    joblib.dump(artifact, temporary)
    temporary.replace(path)


def demo_data(kind):
    rng = np.random.default_rng(42 if kind == "energy" else 91)
    resolution = "hour" if kind == "energy" else "day"
    end = pd.Timestamp.now(tz="UTC").floor("h" if kind == "energy" else "24h")
    n = 24 * 100 if kind == "energy" else 365 * 2
    index = pd.date_range(end=end, periods=n, freq="h" if kind == "energy" else "24h")
    if kind == "energy":
        t = np.arange(n)
        temp = 7 + 7 * np.sin(t / (24 * 15)) + rng.normal(0, 1, n)
        hour = index.tz_convert("Europe/Stockholm").hour.to_numpy()
        load = 0.5 + np.maximum(0, 15 - temp) * 0.07 + 0.6 * ((hour >= 17) & (hour <= 21)) + rng.normal(0, 0.05, n)
        spec = ModelSpec(name="Electricity consumption · DEMO", source="demo", target={"key": "consumption"},
                         inputs=[{"key": "temperature"}], unit="kWh", horizon=24, minimum=0)
        frame = pd.DataFrame({"consumption": load, "temperature": temp}, index=index)
    else:
        rain = rng.exponential(4, n) * (rng.random(n) < 0.3)
        level = np.zeros(n)
        level[0] = 40
        for i in range(1, n):
            level[i] = 30 + (level[i - 1] - 30) * 0.94 + rain[i - 1] * 0.8 + rng.normal(0, 0.15)
        spec = ModelSpec(name="Soil water level · DEMO", source="demo", target={"key": "water_level"},
                         inputs=[{"key": "rain"}], unit="cm", resolution=resolution, horizon=7,
                         calendar=["week", "year_day"], lags=[0, 1, 2, 7, 14], windows=[3, 7, 14], minimum=0)
        frame = pd.DataFrame({"water_level": level, "rain": rain}, index=index)
    return spec, frame
