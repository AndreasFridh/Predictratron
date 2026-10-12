import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ModelSpec, Signal
from app.engine import demo_data, features, forecast, grid, parse_csv, train
from app.home_assistant import HAClient, raw_frame, statistic_frame
from app.main import create_app
from app.store import Store


def csv_spec(**kwargs):
    return ModelSpec(name="Test", source="csv", target={"key": "level"}, inputs=[{"key": "rain"}],
                     lags=[0, 1, 7], windows=[3, 7], horizon=3, **kwargs)


@pytest.fixture(scope="module")
def water():
    spec, frame = demo_data("water")
    artifact = train(frame, spec)
    return spec, frame, artifact


def test_multiple_models_isolated_and_survive_restart(tmp_path):
    store = Store(tmp_path)
    spec, frame = demo_data("water")
    a = store.create(spec)
    b = store.create(spec.model_copy(update={"name": "Other"}))
    store.add_frame(a, frame.iloc[-100:])
    store.add_frame(b, frame.iloc[-20:] * 2)
    restored = Store(tmp_path)
    assert restored.get(a)["data"]["n"] == 100
    assert restored.get(b)["data"]["n"] == 20
    assert restored.frame(a).iloc[-1, 0] != restored.frame(b).iloc[-1, 0]
    assert restored.artifact(a) != restored.artifact(b)


def test_backtest_purges_all_future_labels(water):
    spec, frame, artifact = water
    metrics = artifact["metrics"]
    assert pd.Timestamp(metrics["train_last_target"]) < pd.Timestamp(metrics["test_first_origin"])
    assert metrics["test_rows"] >= 20
    assert len(metrics["per_horizon"]) == spec.horizon
    assert all(m["mae"] >= 0 for m in metrics["per_horizon"])


def test_features_never_depend_on_future_observations(water):
    spec, frame, _ = water
    origin = frame.index[300]
    original = features(frame, spec).loc[origin]
    changed = frame.copy()
    changed.loc[changed.index > origin] *= 100_000
    pd.testing.assert_series_equal(original, features(changed, spec).loc[origin])


def test_daily_forecast_dates_bounds_and_metadata(water):
    spec, frame, artifact = water
    result = forecast(frame, spec, artifact)
    assert len(result["points"]) == 7
    for i, point in enumerate(result["points"], 1):
        assert pd.Timestamp(point["end"]) == frame.index[-1] + pd.Timedelta(days=i)
        assert point["lower"] <= point["value"] <= point["upper"]
        assert point["value"] >= 0
    assert result["unit"] == "cm"
    assert "not guaranteed" in result["interval_note"]


def test_stale_and_missing_latest_inputs_are_rejected(water):
    spec, frame, artifact = water
    stale = frame.copy()
    stale.index -= pd.Timedelta(days=3)
    with pytest.raises(ValueError, match="too old"):
        forecast(stale, spec, artifact)
    missing = frame.copy()
    missing.loc[missing.index[-1], "rain"] = np.nan
    with pytest.raises(ValueError, match="input"):
        forecast(missing, spec, artifact)


def test_gaps_remain_missing_not_interpolated():
    spec = csv_spec()
    stamps = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=4, freq="h")
    frame = pd.DataFrame({"level": [10, 14], "rain": [0, 2]}, index=stamps[[0, 3]])
    result = grid(frame, spec)
    assert result.loc[stamps[1:3]].isna().all().all()


@pytest.mark.parametrize("timestamp", ["2026-01-01T01:00:00", "bad date", "2026-01-01T01:30:00Z"])
def test_csv_rejects_ambiguous_or_unaligned_times(timestamp):
    content = f"timestamp,level,rain\n{timestamp},42,3\n".encode()
    with pytest.raises(ValueError):
        parse_csv(content, csv_spec())


def test_csv_contract_no_double_aggregation():
    content = b"timestamp,level,rain\n2026-01-01T01:00:00Z,42,3\n2026-01-01T02:00:00Z,43,0\n"
    result = parse_csv(content, csv_spec())
    assert result.iloc[0]["rain"] == 3
    assert result.index.tz is not None
    with pytest.raises(ValueError, match="columns"):
        parse_csv(b"timestamp,level\n2026-01-01T01:00:00Z,42\n", csv_spec())


def test_csv_rejects_duplicates_future_and_infinite_values():
    spec = csv_spec()
    for data in [
        b"timestamp,level,rain\n2026-01-01T01:00:00Z,42,3\n2026-01-01T01:00:00Z,43,4\n",
        b"timestamp,level,rain\n2099-01-01T01:00:00Z,42,3\n",
        b"timestamp,level,rain\n2026-01-01T01:00:00Z,inf,3\n",
    ]:
        with pytest.raises(ValueError):
            parse_csv(data, spec)


def test_configuration_requires_distinct_keys_and_valid_timezone():
    with pytest.raises(ValidationError):
        ModelSpec(name="Bad", source="csv", target={"key":"rain"}, inputs=[{"key":"rain"}])
    with pytest.raises(ValidationError):
        csv_spec(timezone="Unknown/Zone")
    with pytest.raises(ValidationError):
        csv_spec(minimum=10, maximum=1)


def test_ha_reset_adjusted_change_and_complete_daily_buckets():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    spec = ModelSpec(name="Energy", target={"key":"load", "entity_id":"sensor.energy", "statistic":"change"},
                     inputs=[], resolution="day", lags=[0,1], windows=[2], horizon=1)
    rows = [{"start": int((start + pd.Timedelta(hours=i)).timestamp()*1000),
             "end": int((start + pd.Timedelta(hours=i+1)).timestamp()*1000), "change": 2, "state": 100+i}
            for i in range(48)]
    result = statistic_frame({"sensor.energy":rows}, spec, start+pd.Timedelta(days=2))
    assert result.iloc[0]["load"] == 48
    assert result.iloc[1]["load"] == 48
    incomplete = statistic_frame({"sensor.energy":rows[:-1]}, spec, start+pd.Timedelta(days=2))
    assert len(incomplete.dropna()) == 1


def test_ha_excludes_current_incomplete_hour():
    spec = ModelSpec(name="Temperature", target={"key":"temp", "entity_id":"sensor.temp"}, lags=[0], windows=[1])
    end = pd.Timestamp("2026-01-01T02:00:00Z")
    rows = [{"end": int((end+pd.Timedelta(hours=i)).timestamp()*1000), "mean": i} for i in [-1,0,1]]
    result = statistic_frame({"sensor.temp":rows}, spec, end)
    assert len(result) == 2
    assert result.index.max() == end


def test_raw_history_means_are_time_weighted_and_unavailable_is_not_filled():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    records = [{"last_changed":"2026-01-01T00:00:00Z","state":"0"},
               {"last_changed":"2026-01-01T00:45:00Z","state":"4"},
               {"last_changed":"2026-01-01T01:30:00Z","state":"unavailable"},
               {"last_changed":"2026-01-01T02:30:00Z","state":"8"}]
    end = start + pd.Timedelta(hours=3)
    means = raw_frame(records, Signal(key="rain"), start, end, "1h")
    assert means.iloc[0] == 1
    assert np.isnan(means.iloc[1]) and np.isnan(means.iloc[2])
    lasts = raw_frame(records, Signal(key="rain", statistic="last"), start, end, "1h")
    assert lasts.iloc[0] == 4
    assert np.isnan(lasts.iloc[1])
    assert lasts.iloc[2] == 8


def wait_job(client, model_id, timeout=30):
    until = time.monotonic()+timeout
    while time.monotonic() < until:
        item = client.get(f"/api/models/{model_id}").json()
        if item["status"] != "running":
            assert item["status"] == "idle", item["error"]
            return item
        time.sleep(.05)
    pytest.fail("Job did not finish")


def test_api_demo_train_predict_and_restarted_storage(tmp_path):
    app = create_app(tmp_path, HAClient(url="", token=""), dev_mode=True)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        item = client.post("/api/demo/water").json()
        model_id = item["id"]
        assert client.get(f"/api/models/{model_id}/forecast").status_code == 404
        assert client.post(f"/api/models/{model_id}/actions/run").status_code == 202
        completed = wait_job(client, model_id)
        assert completed["metrics"] is not None
        result = client.get(f"/api/models/{model_id}/forecast").json()
        assert len(result["points"]) == 7
        assert client.get("/api/models/not-a-model").status_code == 404
    with TestClient(create_app(tmp_path, HAClient(url="", token=""), dev_mode=True)) as client:
        assert len(client.get("/api/models").json()) == 1
        assert client.get(f"/api/models/{model_id}/forecast").status_code == 200


def test_instances_train_and_predict_independently(tmp_path):
    with TestClient(create_app(tmp_path, HAClient(url="", token=""), dev_mode=True)) as client:
        first = client.post("/api/demo/water").json()["id"]
        second = client.post("/api/demo/water").json()["id"]
        untouched = client.get(f"/api/models/{second}").json()
        assert client.post(f"/api/models/{first}/actions/train").status_code == 202
        trained = wait_job(client, first)
        assert trained["metrics"] is not None
        assert trained["forecast"] is None  # Training and prediction are separate operations.
        assert client.get(f"/api/models/{second}").json() == untouched
        assert client.post(f"/api/models/{first}/actions/forecast").status_code == 202
        predicted = wait_job(client, first)
        assert len(predicted["forecast"]["points"]) == 7
        assert predicted["trained_at"] == trained["trained_at"]
        assert predicted["metrics"] == trained["metrics"]  # Prediction does not retrain.
        assert client.get(f"/api/models/{second}").json() == untouched


def test_csv_import_api_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-app-key")
    with TestClient(create_app(tmp_path, HAClient(url="", token=""), dev_mode=True)) as client:
        assert client.get("/api/models").status_code == 401
        assert client.get("/health").status_code == 200
        headers = {"Authorization":"Bearer test-app-key"}
        item = client.post("/api/models", json=csv_spec().model_dump(), headers=headers).json()
        content = b"timestamp,level,rain\n2026-01-01T01:00:00Z,42,3\n"
        result = client.post(f"/api/models/{item['id']}/csv",files={"file":("history.csv",content,"text/csv")}, headers=headers)
        assert result.status_code == 200
        assert result.json()["rows"] == 1
        listing = client.get("/api/models",headers=headers).text
        assert "test-app-key" not in listing


def test_no_credentials_are_exposed_in_status(tmp_path):
    with TestClient(create_app(tmp_path, HAClient(url="http://example.test:8123", token="secret-ha-token"))) as client:
        response = client.get("/api/status")
        assert response.json()["ha_configured"]
        assert "secret-ha-token" not in response.text


def test_publish_is_a_forecast_state_not_an_energy_meter():
    class FakeHA(HAClient):
        def request(self, method, path, **kwargs):
            self.call = (method, path, kwargs)
            return {}
    spec, _ = demo_data("water")
    ha = FakeHA(url="",token="")
    prediction = {"issued_at":"2026-01-01T00:00:00Z", "warning":None,
                  "points":[{"start":"2026-01-01T00:00:00Z", "end":"2026-01-02T00:00:00Z", "value":42}]}
    assert ha.publish("abc",spec,prediction) == "sensor.ml_abc"
    attrs = ha.call[2]["json"]["attributes"]
    assert "state_class" not in attrs
    assert attrs["forecast_end"] == "2026-01-02T00:00:00Z"
