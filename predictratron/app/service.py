import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import joblib
import pandas as pd

from .engine import forecast, save_artifact, train

log = logging.getLogger(__name__)


class Service:
    def __init__(self, store, ha):
        self.store = store
        self.ha = ha
        # Bound CPU and memory use. Different profiles are persisted separately;
        # training jobs run one at a time in this first version.
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        self.pending = set()

    def submit(self, model_id, action):
        with self.lock:
            self.store.get(model_id)
            if model_id in self.pending:
                raise ValueError("Den här modellen arbetar redan")
            self.pending.add(model_id)
            self.store.update(model_id, status="running", error=None)
            self.pool.submit(self._work, model_id, action)

    def _work(self, model_id, action):
        try:
            spec = self.store.spec(model_id)
            if action in {"sync", "run"} and spec.source == "ha":
                self.store.add_frame(model_id, self.ha.history(spec))
            elif action == "sync":
                raise ValueError("Den här modellen använder CSV eller demodata; ingen HA-historik hämtas")
            if action in {"train", "run"}:
                artifact = train(self.store.frame(model_id), spec)
                save_artifact(self.store.artifact(model_id), artifact)
                self.store.update(model_id, metrics=artifact["metrics"], trained_at=artifact["trained_at"], forecast=None)
            if action in {"forecast", "run", "publish"}:
                path = self.store.artifact(model_id)
                if not path.exists():
                    raise ValueError("Träna modellen innan du gör en prognos")
                result = forecast(self.store.frame(model_id), spec, joblib.load(path))
                if action == "publish":
                    if spec.source == "demo":
                        raise ValueError("Demodata publiceras inte som en verklig HA-prognos")
                    result["entity_id"] = self.ha.publish(model_id, spec, result)
                self.store.update(model_id, forecast=result)
            self.store.update(model_id, status="idle", error=None)
        except ValueError as exc:
            self.store.update(model_id, status="error", error=str(exc))
        except Exception:
            # Do not echo arbitrary upstream responses or credential-bearing URLs.
            log.error("Operation %s failed for model %s", action, model_id)
            self.store.update(model_id, status="error", error="Arbetet misslyckades. Kontrollera data och modellinställningar.")
        finally:
            with self.lock:
                self.pending.discard(model_id)

    def scheduled(self):
        for item in self.store.list():
            spec = self.store.spec(item["id"])
            if not spec.auto_update or spec.source != "ha":
                continue
            with self.lock:
                if item["id"] in self.pending:
                    continue
                self.pending.add(item["id"])
                self.store.update(item["id"], status="running", error=None)
            self.pool.submit(self._auto, item["id"])

    def _auto(self, model_id):
        try:
            spec = self.store.spec(model_id)
            self.store.add_frame(model_id, self.ha.history(spec))
            item = self.store.get(model_id)
            overdue = not item["trained_at"] or pd.Timestamp.now(tz="UTC") - pd.Timestamp(item["trained_at"]) >= pd.Timedelta(days=spec.retrain_days)
            if overdue or not self.store.artifact(model_id).exists():
                artifact = train(self.store.frame(model_id), spec)
                save_artifact(self.store.artifact(model_id), artifact)
                self.store.update(model_id, metrics=artifact["metrics"], trained_at=artifact["trained_at"])
            result = forecast(self.store.frame(model_id), spec, joblib.load(self.store.artifact(model_id)))
            self.store.update(model_id, forecast=result, status="idle", error=None)
        except ValueError as exc:
            self.store.update(model_id, status="error", error=str(exc))
        except Exception:
            log.error("Automatic update failed for model %s", model_id)
            self.store.update(model_id, status="error", error="Automatisk uppdatering misslyckades")
        finally:
            with self.lock:
                self.pending.discard(model_id)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
