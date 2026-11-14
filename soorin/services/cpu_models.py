"""Download-once CPU models and bounded OpenAI/TEI-compatible inference.

Run `python -m soorin.services.cpu_models download --role embedding` explicitly.
Normal `serve` startup is offline and fails if that exact snapshot is missing.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any

MODELS = {
    "embedding": ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181"),
    "reranker": ("BAAI/bge-reranker-v2-m3", "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"),
    "ner": ("bnsapa/cybersecurity-ner", "1ad52f1a7686a58da2a427c0706d8b868df47181"),
}
MAX_BATCH = 16
MAX_CHARS = 16000
MAX_BYTES = 300000


def texts(value: Any) -> list[str]:
    rows = [value] if isinstance(value, str) else value
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH:
        raise ValueError("batch must contain 1..16 strings")
    if any(not isinstance(row, str) or not row.strip() or len(row) > MAX_CHARS for row in rows):
        raise ValueError("texts must be nonempty and at most 16000 characters")
    return rows


class Engine:
    def __init__(self, role: str, cache: str, *, model: Any = None):
        self.role = role
        self.model_id, self.revision = MODELS[role]
        self.name = f"{self.model_id}@{self.revision}"
        self.cache = cache
        self.model = model
        self.calls = 0
        self.total_seconds = 0.0
        self.lock = threading.Lock()

    def load(self) -> None:
        if self.model is not None:
            return
        from huggingface_hub import snapshot_download
        import torch
        torch.set_num_threads(int(os.environ.get("SOORIN_MODEL_THREADS", "2")))
        path = snapshot_download(self.model_id, revision=self.revision, cache_dir=self.cache, local_files_only=True)
        if self.role == "embedding":
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(path, device="cpu", local_files_only=True, trust_remote_code=False)
            self.model.max_seq_length = 512
        elif self.role == "reranker":
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(path, device="cpu", local_files_only=True, trust_remote_code=False, max_length=512)
        else:
            from soorin.extraction.cpu_cyber_ner import CpuCyberNer
            self.model = CpuCyberNer(model=path, local_files_only=True)
            self.model._load()

    def infer(self, path: str, body: dict[str, Any]) -> Any:
        if body.get("model", self.name) not in {self.name, self.model_id}:
            raise ValueError("requested model does not match this service")
        with self.lock:
            self.load()
            started = time.perf_counter()
            try:
                if path == "/v1/embeddings" and self.role == "embedding":
                    rows = texts(body.get("input"))
                    vectors = self.model.encode(rows, batch_size=4, normalize_embeddings=True, show_progress_bar=False).tolist()
                    if len(vectors) != len(rows) or any(len(v) != 1024 or any(not math.isfinite(x) for x in v) for v in vectors):
                        raise ValueError("model returned invalid embedding dimensions")
                    return {"object": "list", "model": self.name, "data": [
                        {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
                    ]}
                if path == "/rerank" and self.role == "reranker":
                    query = texts(body.get("query"))[0]
                    rows = texts(body.get("texts"))
                    scores = self.model.predict([(query, row) for row in rows], batch_size=4, show_progress_bar=False).tolist()
                    if len(scores) != len(rows) or any(not math.isfinite(float(score)) for score in scores):
                        raise ValueError("model returned invalid scores")
                    return sorted([{"index": i, "score": float(score)} for i, score in enumerate(scores)], key=lambda row: (-row["score"], row["index"]))
                if path == "/ner" and self.role == "ner":
                    text = texts(body.get("text"))[0]
                    proposals = [dict(asdict(row), model_version=self.name) for row in self.model.extract(text)]
                    return {"model": self.name, "review_required": True, "proposals": proposals}
                raise ValueError("endpoint does not match service role")
            finally:
                self.calls += 1
                self.total_seconds += time.perf_counter() - started


def initialize(role: str, cache: str) -> str:
    # Compatibility alias: artifact preparation must never load weights.
    from .artifacts import download
    return download(role, cache)["cache"]


def serve(engine: Engine, host: str, port: int,
          shared_gate: threading.BoundedSemaphore | None = None) -> None:
    engine.load()  # Missing weights fail at startup, never on a first real request.
    gate = shared_gate or threading.BoundedSemaphore(1)
    token = os.environ.get("SOORIN_MODEL_API_KEY", "")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass  # Do not log URLs, payloads, tokens or model exception bodies.

        def respond(self, status: int, value: Any) -> None:
            raw = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/v1/models":
                self.respond(200, {"object": "list", "data": [{"id": engine.name, "object": "model", "owned_by": "soorin-local"}]})
            elif self.path in {"/health", "/ready"}:
                self.respond(200, {"ready": True, "role": engine.role, "model": engine.name,
                    "device": "cpu", "dimension": 1024 if engine.role == "embedding" else None,
                    "max_batch": MAX_BATCH, "max_tokens": 512,
                    "calls": engine.calls, "inference_seconds": engine.total_seconds})
            else:
                self.respond(404, {"error": "not_found"})

        def do_POST(self) -> None:
            import hmac
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.respond(401, {"error": "unauthorized"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BYTES:
                    raise ValueError("invalid request size")
                if not gate.acquire(blocking=False):
                    self.respond(429, {"error": "busy"})
                    return
                try:
                    self.connection.settimeout(15)
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError("body must be an object")
                    self.respond(200, engine.infer(self.path, body))
                finally:
                    gate.release()
            except (ValueError, KeyError):
                self.respond(422, {"error": "invalid_model_request"})
            except Exception:
                self.respond(503, {"error": "inference_failed"})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.serve_forever()


def serve_all(cache_root: str, host: str) -> None:
    """Serve all three pinned CPU models in one process on isolated role ports.

    Load from three read-only caches before binding any port. Any missing or
    incompatible snapshot prevents partial service readiness.
    """
    from concurrent.futures import ThreadPoolExecutor

    ports = {"embedding": 8080, "reranker": 8081, "ner": 8082}
    engines: dict[str, Engine] = {}
    for role in ports:
        from .artifacts import verify
        cache = str(Path(cache_root) / role)
        result = verify(role, cache, hashes=True)
        if result["status"] != "PASS":
            raise RuntimeError(f"{role}: artifact verification failed: {result['status']}")
        engine = Engine(role, cache)
        engine.load()
        engines[role] = engine
    # A common semaphore prevents simultaneous heavy inference on a CPU host.
    gate = threading.BoundedSemaphore(1)
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="soorin-model") as pool:
        futures = [
            pool.submit(serve, engines[role], host, port, gate)
            for role, port in ports.items()
        ]
        for future in futures:
            future.result()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "download", "verify-artifacts", "serve", "serve-all"])
    parser.add_argument("--role", choices=list(MODELS), required=False)
    parser.add_argument("--cache", default=os.environ.get("HF_HOME", "/models"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--hashes", action="store_true", help="Verify available SHA256 checksums without loading weights")
    args = parser.parse_args()
    if args.command != "serve-all" and not args.role:
        parser.error("--role is required except for serve-all")
    if args.command in {"init", "download", "verify-artifacts"}:
        from .artifacts import download, verify
        result = (verify(args.role, args.cache, hashes=args.hashes)
                  if args.command == "verify-artifacts" else download(args.role, args.cache))
        print(json.dumps(result, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(2)
    elif args.command == "serve-all":
        serve_all(args.cache, args.host)
    else:
        serve(Engine(args.role, args.cache), args.host, args.port)


if __name__ == "__main__":
    main()
