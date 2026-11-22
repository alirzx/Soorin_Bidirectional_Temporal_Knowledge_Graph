"""Exercise bounded HTTP admission and asynchronous binding in a disposable instance."""
import argparse
import concurrent.futures
import json
import os
import math
from pathlib import Path
import time
from uuid import uuid4
from urllib.error import URLError, HTTPError

from soorin.e2e.local_validation import _request_json, ValidationError
from soorin.e2e.native_validation import bootstrap_synthetic_workspace
from soorin.ontology.importer import OntologyImporter, load_and_validate
from soorin.tests.mock_splunk.scripts.curated_qa_dataset import PROFILE, make_record


def transport_interruption(error):
    return isinstance(error, (TimeoutError, ConnectionError)) or (
        isinstance(error.__cause__, URLError) and not isinstance(error.__cause__, HTTPError))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", choices=(10, 100, 500), default=[10, 100, 500])
    parser.add_argument("--deadline", type=int, default=1200)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--simulate-models", action="store_true")
    args = parser.parse_args()
    if os.getenv("SOORIN_ISOLATED_LOAD") != "1" or not 10000 <= args.port <= 65535:
        parser.error("requires an isolated loopback test port and SOORIN_ISOLATED_LOAD=1")
    if args.deadline < 1:
        parser.error("deadline must be positive")
    base = f"http://127.0.0.1:{args.port}"
    token, workspace = bootstrap_synthetic_workspace(base)

    def api(path, body=None, method=None):
        return _request_json(base, path, token=token, body=body,
                             method=method or ("POST" if body is not None else "GET"))

    ontology = load_and_validate(Path(__file__).parents[1] / "ontology/soc_ontology_v1.yaml")
    reports = []
    benchmark = None
    if args.simulate_models:
        from soorin.e2e.reliability_models import ModelBenchmark
        token, workspace = bootstrap_synthetic_workspace(base, token=token)
        # The first KB in a new workspace is its open default. Keep measured KBs restricted.
        api(f"/api/v1/workspaces/{workspace}/kbs", {"name": "Synthetic workspace default"})
        benchmark = ModelBenchmark()
        benchmark.configure(api, workspace)

    def save():
        temporary = args.report.with_suffix(".tmp")
        temporary.write_text(json.dumps(reports, indent=2))
        temporary.replace(args.report)

    for size in args.sizes:
        kb = api(f"/api/v1/workspaces/{workspace}/kbs", {
            "name": f"load-{size}-{uuid4()}", "visibility": "restricted",
        })["id"]
        root = f"/api/v1/kbs/{kb}"
        importer = OntologyImporter(base, kb, token, request=lambda method, path, body: api(root + path, body, method))
        importer.apply(ontology)
        api(root + "/knowledge/binding", {
            "tenant_id": "tenant-blue", "source_system": "splunk", "source_instance": "splunk-e2e",
        }, "PUT")
        source = api(root + "/sources", {"kind": "statements", "name": "load", "config": {}})
        path = f"/api/v1/sources/{source['source']['id']}/soc/ingest"
        report = {"size": size, "kb_id": kb, "accepted": 0, "poll_timeouts": 0}
        reports.append(report)
        save()
        if benchmark:
            benchmark.start(api, root)
        start = time.monotonic()

        def send(index):
            began = time.monotonic()
            # A timed-out response may follow a committed receipt. Replay the identical record.
            body = {"profile": PROFILE, "record": make_record(index)}
            for attempt in range(3):
                try:
                    admitted = _request_json(base, path, method="POST", token=source["ingest_token"], body=body)
                    return admitted["receipt_id"], time.monotonic() - began
                except (TimeoutError, ConnectionError, ValidationError) as error:
                    if attempt == 2 or not transport_interruption(error):
                        raise
                    time.sleep(1 + attempt)

        ids = []
        admission_latencies = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as threads:
            for receipt_id, seconds in threads.map(send, range(size)):
                ids.append(receipt_id)
                admission_latencies.append(seconds)
                report["accepted"] = len(ids)
        report["unique_receipts"] = len(set(ids))
        report["duplicate_replay_matched"] = send(0)[0] == ids[0]
        admission_latencies.sort()
        report["admission_latency_seconds"] = {f"p{p}": admission_latencies[math.ceil(p * size / 100) - 1] for p in (50, 95, 99)}
        if len(set(ids)) != size or not report["duplicate_replay_matched"]:
            raise RuntimeError("record identity or idempotent replay mismatch")
        report["admission_seconds"] = time.monotonic() - start
        save()
        while time.monotonic() - start < args.deadline:
            try:
                result = api(root + "/knowledge/receipts/summary")
            except (TimeoutError, ConnectionError, ValidationError) as error:
                if not transport_interruption(error):
                    raise
                if isinstance(error, TimeoutError):
                    report["poll_timeouts"] += 1
                else:
                    report["poll_disconnects"] = report.get("poll_disconnects", 0) + 1
            else:
                counts = {}
                delivery = {}
                classes = {}
                queued = 0
                oldest = 0
                for row in result["groups"]:
                    status, state, count = row["status"], row["delivery_state"], row["count"]
                    counts[status] = counts.get(status, 0) + count
                    delivery[state] = delivery.get(state, 0) + count
                    if row["failure_class"]:
                        key = row["failure_class"]
                        classes[key] = classes.get(key, 0) + count
                    if state in ("queued", "waiting_for_dependency"):
                        queued += count
                        oldest = max(oldest, row["oldest_age_seconds"])
                report.update(delivery_states=delivery, parent_failure_classes=classes,
                              queued_receipts=queued, peak_queued_receipts=max(queued, report.get("peak_queued_receipts", 0)),
                              peak_queue_age_seconds=max(oldest, report.get("peak_queue_age_seconds", 0)))
                report.update(durable=sum(counts.values()), counts=counts, elapsed_seconds=time.monotonic() - start)
                if counts == {"bound": size}:
                    report["materialization_after_admission_seconds"] = report["elapsed_seconds"] - report["admission_seconds"]
                    report["bound_per_second"] = size / report["elapsed_seconds"]
                    save()
                    break
                if counts.get("quarantined"):
                    save()
                    raise RuntimeError(f"unexpected quarantine for synthetic KB {kb}")
            save()
            time.sleep(2)
        else:
            raise TimeoutError(f"binding deadline exceeded for synthetic KB {kb}")
        if benchmark:
            report["model_benchmark"] = benchmark.finish()
            save()
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
