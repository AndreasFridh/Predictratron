import asyncio
import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ModelSpec
from .engine import demo_data, parse_csv
from .graph import Graph
from .home_assistant import HAClient
from .service import Service
from .store import Store

STATIC = Path(__file__).parent / "static"


def create_app(data_dir=None, ha=None, dev_mode=None):
    development = dev_mode if dev_mode is not None else os.getenv("APP_BUILD", "release") == "development"
    store = Store(data_dir or os.getenv("DATA_DIR", "./data"))
    service = Service(store, ha or HAClient())
    app_token = os.getenv("APP_TOKEN", "")
    ingress_only = os.getenv("INGRESS_ONLY", "false").lower() == "true"

    async def scheduler():
        while True:
            await asyncio.sleep(900)
            # Queue work without waiting on a long-running training operation.
            await asyncio.to_thread(service.scheduled)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduler())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(service.close)

    app = FastAPI(title="Predictratron", version="0.4.0", lifespan=lifespan)
    app.state.store = store
    app.state.service = service

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if ingress_only:
            peer = request.client.host if request.client else ""
            local_health = request.url.path == "/health" and peer in {"127.0.0.1", "::1"}
            if peer != "172.30.32.2" and not local_health:
                return JSONResponse({"detail": "Open Predictratron through Home Assistant"}, status_code=403)
        if app_token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + app_token):
                return JSONResponse({"detail": "Enter the app access key"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing_model(request, exc):
        return JSONResponse({"detail": "Analysis not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid_data(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index(request: Request):
        prefix = request.headers.get("x-ingress-path", "").rstrip("/")
        if prefix and not re.fullmatch(r"/api/(?:hassio|app|apps)_ingress/[a-zA-Z0-9_-]+", prefix):
            raise HTTPException(400, "Invalid Ingress path")
        markup = (STATIC / "index.html").read_text()
        return HTMLResponse(markup.replace("<head>", f'<head>\n  <base href="{prefix}/">', 1))

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.4.0"}

    @app.get("/api/status")
    def status():
        return {"ha_configured": service.ha.configured, "dev_mode": development, "version": "0.4.0"}

    @app.get("/api/entities")
    def entities():
        return service.ha.entities()

    @app.get("/api/models")
    def models():
        return [item for item in store.list() if development or item["config"]["source"] != "demo"]

    @app.post("/api/models", status_code=201)
    def create(spec: ModelSpec):
        return store.get(store.create(spec))

    @app.post("/api/graphs", status_code=201)
    def create_graph(graph: Graph):
        model_id = store.create(graph.compile())
        store.save_graph(model_id, graph)
        return store.get(model_id)

    @app.put("/api/models/{model_id}/graph")
    async def save_graph(model_id: str, graph: Graph):
        def save():
            with service.lock:
                if model_id in service.pending:
                    raise ValueError("Analysis is running. Wait before saving connections.")
                store.save_graph(model_id, graph)
                return store.get(model_id)
        return await asyncio.to_thread(save)

    @app.post("/api/demo/{kind}", status_code=201)
    def demo(kind: Literal["energy", "water"]):
        if not development:
            raise HTTPException(404, "Demo examples are available only in development builds")
        spec, frame = demo_data(kind)
        model_id = store.create(spec)
        store.add_frame(model_id, frame)
        return store.get(model_id)

    @app.get("/api/models/{model_id}")
    def model(model_id: str):
        return store.get(model_id)

    @app.get("/api/models/{model_id}/history")
    def history(model_id: str):
        spec = store.spec(model_id)
        try:
            frame = store.frame(model_id).tail(200)
        except ValueError:
            return []
        return [{"timestamp": stamp.isoformat(), "value": float(row[spec.target.key]) if row[spec.target.key] == row[spec.target.key] else None}
                for stamp, row in frame.iterrows()]

    @app.post("/api/models/{model_id}/csv")
    async def import_csv(model_id: str, file: UploadFile, interval_minutes: int | None = Form(default=None, ge=1, le=525600)):
        spec = store.spec(model_id)
        if spec.source != "csv":
            raise HTTPException(400, "Create a CSV analysis to import data")
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "CSV must be at most 20 MB")
        frame = parse_csv(content, spec, interval_minutes)
        def save():
            with service.lock:
                if model_id in service.pending:
                    raise ValueError("Analysis is running. Wait before importing.")
                return store.add_frame(model_id, frame)
        rows = await asyncio.to_thread(save)
        return {"rows": rows}

    @app.post("/api/models/{model_id}/actions/{action}", status_code=202)
    async def action(model_id: str, action: Literal["sync", "train", "forecast", "run", "publish"]):
        await asyncio.to_thread(service.submit, model_id, action)
        return {"status": "queued", "model_id": model_id}

    @app.get("/api/models/{model_id}/forecast")
    def prediction(model_id: str):
        item = store.get(model_id)
        result = item["forecast"]
        if result is None:
            raise HTTPException(404, "No forecast yet")
        spec = ModelSpec.model_validate(item["config"])
        import pandas as pd
        if pd.Timestamp.now(tz="UTC") - pd.Timestamp(result["origin"]) > 2 * pd.Timedelta(spec.freq):
            raise HTTPException(409, "Forecast is stale. Refresh history and forecast.")
        return result

    return app
