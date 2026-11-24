"""Operator-run synthetic BGE CPU timing probe for an already running local model service."""
import argparse
import http.client
import json
import math
from time import perf_counter

from soorin.evaluation.retrieval_benchmark import rerank_window_benchmark
from soorin.services.cpu_models import MODELS


def benchmark(port, timeout):
    model, revision = MODELS["reranker"]
    expected = f"{model}@{revision}"
    reports = []
    for batch in (4, 8, 16):
        for chars in (500, 1800, 3500):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            start = perf_counter()
            try:
                connection.connect()
                connection.request("GET", "/ready")
                response = connection.getresponse()
                health = json.loads(response.read(16384))
                if response.status != 200 or health.get("model") != expected:
                    raise RuntimeError("unexpected reranker")
                rows = [
                    (f"Synthetic event {i}. Account change followed by repeated authentication attempts. " * chars)[:chars]
                    for i in range(batch)
                ]
                body = json.dumps({"model": expected, "query": "Repeated authentication attempts after account change",
                                   "texts": rows}).encode()
                # The local provider may close /ready. Time the POST connection explicitly.
                connection.close()
                begin = perf_counter()
                connection.connect()
                connected = perf_counter()
                connection.request("POST", "/rerank", body=body, headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                data = response.read(16_384)
                scores = json.loads(data) if response.status == 200 else []
                valid = isinstance(scores, list) and len(scores) == batch
                if valid:
                    valid = (sorted(row["index"] for row in scores) == list(range(batch))
                             and all(math.isfinite(row["score"]) for row in scores))
                reports.append({"batch": batch, "characters_each": chars, "status": response.status,
                                "connect_ms": round((connected-begin)*1000, 2),
                                "request_ms": round((perf_counter()-connected)*1000, 2),
                                "total_probe_ms": round((perf_counter()-start)*1000, 2),
                                "queue_rejection": response.getheader("X-Soorin-Rejection"),
                                "valid": valid})
            finally:
                connection.close()
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="print synthetic ranking and work estimates only")
    parser.add_argument("--existing-server-model", action="store_true", help="explicit opt-in to CPU requests on loopback")
    parser.add_argument("--port", type=int, default=2812)
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()
    if args.offline:
        print(json.dumps(rerank_window_benchmark(), indent=2))
    elif args.existing_server_model and 1 <= args.port <= 65535 and 1 <= args.timeout <= 60:
        for row in benchmark(args.port, args.timeout):
            print(json.dumps(row))
    else:
        parser.error("select offline or explicitly opt in to an existing model on loopback")


if __name__ == "__main__":
    main()
