"""Synthetic provider contention benchmark using the production CPU service admission gate."""
from collections import Counter
from math import ceil
import threading
import time
from urllib.request import urlopen
from urllib.error import HTTPError

from soorin.e2e.local_validation import _request_json, ValidationError
from soorin.services import cpu_models


class TimedGate(cpu_models.InferenceGate):
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.waiting = self.high_water = self.rejections = 0
        self.wait_seconds_total = 0.0

    def acquire(self):
        start = time.monotonic()
        with self.lock:
            self.waiting += 1
            self.high_water = max(self.high_water, self.waiting)
        try:
            granted = super().acquire()
            with self.lock:
                self.rejections += int(not granted)
            return granted
        finally:
            with self.lock:
                self.waiting -= 1
                self.wait_seconds_total += time.monotonic() - start


class SyntheticEngine(cpu_models.Engine):
    def infer(self, path, body):
        # Deterministic service time; no weights, external services or source payload logging.
        time.sleep(0.025)
        self.calls += 1
        if self.role == "embedding":
            return {"data": [{"index": i, "embedding": [1.0] + [0.0] * 1023}
                             for i, _ in enumerate(body["input"])]}
        if self.role == "reranker":
            return [{"index": i, "score": 1.0} for i, _ in enumerate(body["texts"])]
        return {"entities": []}


class ModelBenchmark:
    def __init__(self):
        self.gate = TimedGate()
        self.engines = {}
        self.urls = {}
        for i, role in enumerate(("embedding", "reranker", "ner")):
            port = 31980 + i
            self.urls[role] = f"http://127.0.0.1:{port}"
            engine = SyntheticEngine(role, "", model=True)
            self.engines[role] = engine
            threading.Thread(target=cpu_models.serve, args=(engine, "127.0.0.1", port, self.gate),
                             daemon=True).start()
            for _ in range(50):
                try:
                    with urlopen(self.urls[role] + "/ready", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"synthetic {role} readiness deadline")

    def configure(self, api, workspace):
        api(f"/api/v1/workspaces/{workspace}/settings", {
            "embed_base_url": self.urls["embedding"] + "/v1",
            "embed_model": self.engines["embedding"].name, "embed_dim": 1024}, "PUT")
        api(f"/api/v1/workspaces/{workspace}/settings/reranker", {
            "enabled": True, "base_url": self.urls["reranker"],
            "model": self.engines["reranker"].name, "fallback": False}, "PUT")

    def start(self, api, root):
        self.stop = threading.Event()
        self.times = []
        self.outcomes = Counter()
        self.lock = threading.Lock()
        self.before = {role: engine.calls for role, engine in self.engines.items()}

        def probe(role):
            while not self.stop.is_set():
                start = time.monotonic()
                try:
                    if role == "search":
                        result = api(root + "/search", {"q": "host", "top_k": 3})
                        meta = result["retrieval"]
                        category = f"search_dense_{meta['dense_executed']}_rerank_{meta['reranker_status']}"
                    else:
                        _request_json(self.urls["ner"], "/ner", method="POST", body={"text": "synthetic host"})
                        category = "ner_ok"
                except (OSError, ValidationError) as err:
                    cause = err.__cause__
                    category = f"{role}_http_{cause.code}" if isinstance(cause, HTTPError) else role + "_unavailable"
                with self.lock:
                    self.outcomes[category] += 1
                    if role == "search":
                        self.times.append(time.monotonic() - start)
                self.stop.wait(0.5)

        self.threads = [threading.Thread(target=probe, args=(role,), daemon=True) for role in ("search", "ner")]
        for thread in self.threads:
            thread.start()

    def finish(self):
        self.stop.set()
        for thread in self.threads:
            thread.join()
        times = sorted(self.times)
        return {
            "synthetic_service_seconds": 0.025, "outcomes": dict(self.outcomes),
            "search_p95_seconds": times[ceil(len(times) * .95) - 1] if times else None,
            "role_calls": {k: e.calls - self.before[k] for k, e in self.engines.items()},
            "gate_rejections_cumulative": self.gate.rejections,
            "peak_concurrent_gate_acquisitions_cumulative": self.gate.high_water,
            "gate_wait_seconds_cumulative": self.gate.wait_seconds_total,
        }
