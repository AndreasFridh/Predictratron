import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .config import ModelSpec


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "predictor.sqlite3"
        with self.connect() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL,
                    metrics TEXT, forecast TEXT, trained_at TEXT,
                    status TEXT NOT NULL DEFAULT 'idle', error TEXT
                );
                CREATE TABLE IF NOT EXISTS samples (
                    model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
                    timestamp TEXT NOT NULL, values_json TEXT NOT NULL,
                    PRIMARY KEY(model_id, timestamp)
                );
            """)
            columns = {row[1] for row in con.execute("PRAGMA table_info(models)")}
            for name in ("graph", "data_schema"):
                if name not in columns:
                    con.execute(f"ALTER TABLE models ADD COLUMN {name} TEXT")
            for row in con.execute("SELECT id, config FROM models WHERE data_schema IS NULL").fetchall():
                spec = ModelSpec.model_validate_json(row["config"])
                con.execute("UPDATE models SET data_schema=? WHERE id=?", (json.dumps(self.schema(spec)), row["id"]))
            # A process restart cannot resume a partly completed operation.
            con.execute("UPDATE models SET status='idle', error='Arbetet avbröts vid omstart' WHERE status='running'")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def create(self, spec):
        model_id = uuid.uuid4().hex[:16]
        with self.connect() as con:
            con.execute("INSERT INTO models (id, config, data_schema) VALUES (?, ?, ?)",
                        (model_id, spec.model_dump_json(), json.dumps(self.schema(spec))))
        return model_id

    def get(self, model_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
            if row is None:
                raise KeyError(model_id)
            stats = con.execute("SELECT COUNT(*) AS n, MIN(timestamp) AS first, MAX(timestamp) AS last FROM samples WHERE model_id=?", (model_id,)).fetchone()
        item = dict(row)
        for key in ("config", "metrics", "forecast", "graph", "data_schema"):
            item[key] = json.loads(item[key]) if item[key] else None
        item["data"] = dict(stats)
        return item

    @staticmethod
    def schema(spec):
        return {signal.key: signal.model_dump(exclude={"label"}) for signal in spec.signals}

    def save_graph(self, model_id, graph):
        spec = graph.compile()
        item = self.get(model_id)
        old = ModelSpec.model_validate(item["config"])
        manifest = item["data_schema"] or self.schema(old)
        incoming = self.schema(spec)
        if item["data"]["n"]:
            if old.source != spec.source or old.step_minutes != spec.step_minutes or incoming[spec.target.key] != manifest.get(old.target.key):
                raise ValueError("Mål, datakälla eller upplösning har ändrats. Spara som ny modell för att behålla den gamla historiken.")
            for key, contract in incoming.items():
                if key in manifest and contract != manifest[key]:
                    raise ValueError(f"Datakällan eller typen för {key} har ändrats. Spara som ny modell för att undvika att blanda mätvärden.")
        changed = old.signature() != spec.signature()
        with self.connect() as con:
            con.execute("UPDATE models SET config=?, graph=?, data_schema=?, error=NULL, status='idle' WHERE id=?",
                        (spec.model_dump_json(), graph.model_dump_json(), json.dumps({**manifest, **incoming}), model_id))
            if changed:
                con.execute("UPDATE models SET metrics=NULL, forecast=NULL, trained_at=NULL WHERE id=?", (model_id,))
        return changed

    def spec(self, model_id):
        return ModelSpec.model_validate(self.get(model_id)["config"])

    def list(self):
        with self.connect() as con:
            ids = [row[0] for row in con.execute("SELECT id FROM models ORDER BY rowid")]
        return [self.get(i) for i in ids]

    def update(self, model_id, **values):
        allowed = {"metrics", "forecast", "trained_at", "status", "error"}
        if not values or not set(values) <= allowed:
            raise ValueError("Ogiltig uppdatering")
        parameters = [json.dumps(v, allow_nan=False) if k in {"metrics", "forecast"} and v is not None else v for k, v in values.items()]
        with self.connect() as con:
            con.execute(f"UPDATE models SET {', '.join(k+'=?' for k in values)} WHERE id=?", [*parameters, model_id])

    def add_frame(self, model_id, frame):
        spec = self.spec(model_id)
        for signal in spec.signals:
            values = frame[signal.key].dropna()
            if signal.data_type == "bool" and not values.isin([0, 1]).all():
                raise ValueError(f"{signal.key} är Boolean och behöver värden 0 eller 1")
            if signal.data_type == "int" and not (values == values.round()).all():
                raise ValueError(f"{signal.key} är Integer och behöver heltal")
        rows = []
        for stamp, values in frame.iterrows():
            clean = {k: float(v) if pd.notna(v) else None for k, v in values.items()}
            rows.append((model_id, stamp.isoformat(), json.dumps(clean, allow_nan=False)))
        with self.connect() as con:
            # Preserve stored values for temporarily disconnected signals.
            # Explicit nulls still become missing values on reindexing.
            con.executemany("INSERT INTO samples VALUES (?, ?, ?) ON CONFLICT(model_id, timestamp) DO UPDATE SET values_json=json_patch(samples.values_json, excluded.values_json)", rows)
            con.execute("UPDATE models SET forecast=NULL WHERE id=?", (model_id,))
        return len(rows)

    def frame(self, model_id):
        with self.connect() as con:
            rows = con.execute("SELECT timestamp, values_json FROM samples WHERE model_id=? ORDER BY timestamp", (model_id,)).fetchall()
        if not rows:
            raise ValueError("Ingen historik ännu. Hämta från HA eller importera CSV.")
        frame = pd.DataFrame([json.loads(r[1]) for r in rows], index=pd.to_datetime([r[0] for r in rows], utc=True))
        frame.index.name = "timestamp"
        return frame.reindex(columns=[signal.key for signal in self.spec(model_id).signals]).astype(float)

    def artifact(self, model_id):
        # Only database-generated ids reach this method through a prior get().
        self.get(model_id)
        return self.root / f"{model_id}.joblib"
