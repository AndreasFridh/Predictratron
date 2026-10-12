from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import ModelSpec, Signal


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["input", "calendar", "ml", "output"]
    x: float = Field(ge=0, le=6000, allow_inf_nan=False)
    y: float = Field(ge=0, le=6000, allow_inf_nan=False)
    signal: Signal | None = None
    calendar: Literal["hour", "weekday", "week", "year_day"] | None = None
    # The connected target/inputs are authoritative; incomplete ML settings
    # must not be validated against disconnected placeholder signal fields.
    config: dict | None = None

    @model_validator(mode="after")
    def payload(self):
        if self.kind in {"input", "output"} and not self.signal:
            raise ValueError("Signalen saknar inställningar")
        if self.kind == "calendar" and not self.calendar:
            raise ValueError("Kalendersignalen saknar kalenderfält")
        if self.kind == "ml" and not self.config:
            raise ValueError("ML-boxen saknar modellinställningar")
        return self


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    nodes: list[Node] = Field(min_length=2, max_length=50)
    edges: list[Edge] = Field(default_factory=list, max_length=50)

    def compile(self):
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Noderna behöver unika id")
        nodes = {node.id: node for node in self.nodes}
        boxes = [node for node in self.nodes if node.kind == "ml"]
        if len(boxes) != 1:
            raise ValueError("Varje modellinstans behöver exakt en ML-box")
        box = boxes[0]
        seen = set()
        inputs, calendars, outputs = [], [], []
        for edge in self.edges:
            pair = (edge.source, edge.target)
            if pair in seen:
                raise ValueError("Samma koppling finns flera gånger")
            seen.add(pair)
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError("Kopplingen hänvisar till en signal som saknas")
            source, target = nodes[edge.source], nodes[edge.target]
            if source.kind in {"input", "calendar"} and target.id == box.id:
                (inputs if source.kind == "input" else calendars).append(source)
            elif source.id == box.id and target.kind == "output":
                outputs.append(target)
            else:
                raise ValueError("Koppla inputsignaler till ML-boxen och ML-boxen till outputsignalen")
        if len(outputs) != 1:
            raise ValueError("Koppla ML-boxen till exakt en outputsignal")
        calendar_keys = [node.calendar for node in calendars]
        if len(calendar_keys) != len(set(calendar_keys)):
            raise ValueError("Samma kalenderfält kan bara kopplas in en gång")
        signals = [outputs[0].signal, *[node.signal for node in inputs]]
        ha_signals = [signal for signal in signals if signal.entity_id]
        if ha_signals and len(ha_signals) != len(signals):
            raise ValueError("Alla anslutna mätvärdessignaler behöver en HA-sensor, eller vara CSV-kolumner utan HA-sensor. Blandade datakällor stöds inte ännu.")
        data_source = "ha" if ha_signals else "demo" if box.config.get("source") == "demo" else "csv"
        return ModelSpec.model_validate({**box.config,
                                        "source": data_source,
                                        "auto_update": data_source == "ha" and box.config.get("auto_update", False),
                                        "target": outputs[0].signal.model_dump(),
                                        "inputs": [node.signal.model_dump() for node in inputs],
                                        "calendar": calendar_keys})
