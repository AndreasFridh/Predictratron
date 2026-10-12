import copy

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import ModelSpec
from app.engine import demo_data, forecast, train
from app.graph import Graph
from app.home_assistant import HAClient
from app.main import create_app
from app.store import Store


def water_graph(spec=None):
    if spec is None:
        spec, _ = demo_data("water")
    return Graph.model_validate({"version":1,"nodes":[
        {"id":"rain","kind":"input","x":25,"y":60,"signal":spec.inputs[0].model_dump()},
        {"id":"week","kind":"calendar","x":25,"y":170,"calendar":"week"},
        {"id":"season","kind":"calendar","x":25,"y":280,"calendar":"year_day"},
        {"id":"ml","kind":"ml","x":300,"y":160,"config":spec.model_dump()},
        {"id":"out","kind":"output","x":300,"y":440,"signal":spec.target.model_dump()},
    ],"edges":[{"source":"rain","target":"ml"},{"source":"week","target":"ml"},
               {"source":"season","target":"ml"},{"source":"ml","target":"out"}]})


def test_wires_determine_inputs_calendar_and_target():
    graph=water_graph()
    assert graph.compile().inputs[0].key=="rain"
    assert graph.compile().calendar==["week","year_day"]
    graph.edges=[edge for edge in graph.edges if edge.source!="rain" and edge.source!="season"]
    compiled=graph.compile()
    assert compiled.inputs==[]
    assert compiled.calendar==["week"]
    assert compiled.target.key=="water_level"


@pytest.mark.parametrize("edge",[
    {"source":"out","target":"ml"},
    {"source":"rain","target":"out"},
    {"source":"ml","target":"ml"},
    {"source":"unknown","target":"ml"},
    {"source":"rain","target":"ml"},
])
def test_invalid_or_duplicate_connections_rejected(edge):
    payload=water_graph().model_dump()
    payload["edges"].append(edge)
    with pytest.raises(ValueError):
        Graph.model_validate(payload).compile()


def test_output_must_be_connected():
    graph=water_graph()
    graph.edges=[edge for edge in graph.edges if edge.source!="ml"]
    with pytest.raises(ValueError,match="outputsignal"):
        graph.compile()


def test_actual_connected_ha_signals_override_ml_placeholders():
    payload=water_graph().model_dump()
    ml=next(node for node in payload["nodes"] if node["kind"]=="ml")
    ml["config"]["source"]="ha"
    # These settings still contain old CSV/demo placeholder fields. Actual
    # connected signal nodes have the real HA sensor mapping instead.
    for node in payload["nodes"]:
        if node["kind"] in {"input","output"}:
            node["signal"]["entity_id"]="sensor."+node["signal"]["key"]
    spec=Graph.model_validate(payload).compile()
    assert spec.source=="ha"
    assert spec.target.entity_id=="sensor.water_level"
    assert spec.inputs[0].entity_id=="sensor.rain"


def test_layout_and_labels_survive_restart_without_invalidating_model(tmp_path):
    spec, frame=demo_data("water")
    store=Store(tmp_path);model_id=store.create(spec);store.add_frame(model_id,frame)
    store.update(model_id,metrics={"mae":1},trained_at="2026-01-01T00:00:00Z")
    graph=water_graph(spec)
    graph.nodes[0].x=85
    graph.nodes[0].signal.label="Nederbörd"
    assert not store.save_graph(model_id,graph)
    item=Store(tmp_path).get(model_id)
    assert item["graph"]["nodes"][0]["x"]==85
    assert item["config"]["inputs"][0]["label"]=="Nederbörd"
    assert item["metrics"]=={"mae":1}
    assert item["data"]["n"]==len(frame)


def test_changed_connections_invalidate_training_but_preserve_history(tmp_path):
    spec,frame=demo_data("water")
    store=Store(tmp_path);model_id=store.create(spec);store.add_frame(model_id,frame)
    store.update(model_id,metrics={"mae":1},trained_at="2026-01-01T00:00:00Z")
    graph=water_graph(spec);graph.edges=[edge for edge in graph.edges if edge.source!="week"]
    assert store.save_graph(model_id,graph)
    item=store.get(model_id)
    assert item["metrics"] is None
    assert item["trained_at"] is None
    assert item["data"]["n"]==len(frame)
    assert item["config"]["calendar"]==["year_day"]


def test_changed_target_or_data_contract_does_not_overwrite_old_history(tmp_path):
    spec,frame=demo_data("water")
    store=Store(tmp_path);model_id=store.create(spec);store.add_frame(model_id,frame)
    graph=water_graph(spec);graph.nodes[-1].signal.key="different_level"
    with pytest.raises(ValueError,match="ny modell"):
        store.save_graph(model_id,graph)
    assert store.get(model_id)["config"]["target"]["key"]=="water_level"
    assert store.get(model_id)["data"]["n"]==len(frame)


def test_old_artifacts_accept_new_signal_labels():
    spec,frame=demo_data("water")
    artifact=train(frame,spec)
    # Simulate a model trained before label/type metadata was introduced.
    for signal in [artifact["spec"]["target"],*artifact["spec"]["inputs"]]:
        signal.pop("label",None);signal.pop("data_type",None)
    spec.inputs[0].label="Nederbörd"
    assert len(forecast(frame,spec,artifact)["points"])==7


def test_graph_create_and_update_api(tmp_path):
    with TestClient(create_app(tmp_path,HAClient(url="",token=""))) as client:
        payload=water_graph().model_dump()
        result=client.post("/api/graphs",json=payload)
        assert result.status_code==201,result.text
        model_id=result.json()["id"]
        payload["nodes"][0]["x"]=120
        updated=client.put(f"/api/models/{model_id}/graph",json=payload)
        assert updated.status_code==200,updated.text
        assert updated.json()["graph"]["nodes"][0]["x"]==120


def test_declared_input_types_are_enforced(tmp_path):
    spec=ModelSpec(name="Bool",source="csv",target={"key":"target"},inputs=[{"key":"switch","data_type":"bool"}],lags=[0],windows=[1])
    store=Store(tmp_path);model_id=store.create(spec)
    stamps=pd.date_range("2026-01-01",periods=2,freq="h",tz="UTC")
    with pytest.raises(ValueError,match="Boolean"):
        store.add_frame(model_id,pd.DataFrame({"target":[1,2],"switch":[0,.5]},index=stamps))


def test_reconnecting_same_signals_keeps_trained_model(tmp_path):
    spec,frame=demo_data("water")
    store=Store(tmp_path);model_id=store.create(spec);store.add_frame(model_id,frame)
    store.update(model_id,metrics={"mae":1})
    graph=water_graph(spec)
    graph.edges=graph.edges[::-1]
    assert not store.save_graph(model_id,graph)
    assert store.get(model_id)["metrics"]=={"mae":1}


def test_disconnected_signal_history_is_preserved_during_import(tmp_path):
    spec,frame=demo_data("water")
    store=Store(tmp_path);model_id=store.create(spec);store.add_frame(model_id,frame)
    graph=water_graph(spec)
    original_edges=graph.edges[:]
    graph.edges=[edge for edge in graph.edges if edge.source!="rain"]
    store.save_graph(model_id,graph)
    store.add_frame(model_id,frame[["water_level"]])
    graph.edges=original_edges
    store.save_graph(model_id,graph)
    pd.testing.assert_series_equal(store.frame(model_id)["rain"],frame["rain"],check_names=False,check_freq=False)


def test_connected_signals_determine_history_source_not_ml_setting():
    graph = water_graph()
    for node in graph.nodes:
        if node.signal:
            node.signal.entity_id = 'sensor.' + node.signal.key
    assert graph.compile().source == 'ha'
    for node in graph.nodes:
        if node.signal:
            node.signal.entity_id = None
    graph.nodes[3].config['source'] = 'ha'
    assert graph.compile().source == 'csv'


def test_mixed_history_sources_rejected_until_all_connected_signals_mapped():
    graph = water_graph()
    graph.nodes[0].signal.entity_id = 'sensor.rain'
    with pytest.raises(ValueError, match='Blandade datakällor'):
        graph.compile()
    graph.nodes[-1].signal.entity_id = 'sensor.water_level'
    assert graph.compile().source == 'ha'
    graph.nodes[0].signal.entity_id = None
    graph.edges = [edge for edge in graph.edges if edge.source != 'rain']
    assert graph.compile().source == 'ha'
