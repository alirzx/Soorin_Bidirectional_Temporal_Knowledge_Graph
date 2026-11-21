"""Exercise bounded HTTP admission and asynchronous binding in a disposable instance."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from soorin.e2e.local_validation import _request_json
from soorin.e2e.native_validation import bootstrap_synthetic_workspace
from soorin.ontology.importer import OntologyImporter, load_and_validate
from soorin.tests.mock_splunk.scripts.curated_qa_dataset import PROFILE, make_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", choices=(10, 100, 500), default=[10, 100, 500])
    parser.add_argument("--deadline", type=int, default=1200)
    parser.add_argument("--report", type=Path, required=True)
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
        start = time.monotonic()

        def send(index):
            # A timed-out response may follow a committed receipt. Replay the identical record.
            body = {"profile": PROFILE, "record": make_record(index)}
            for attempt in range(3):
                try:
                    admitted = _request_json(base, path, method="POST", token=source["ingest_token"], body=body)
                    return admitted["receipt_id"]
                except TimeoutError:
                    if attempt == 2:
                        raise
                    time.sleep(1 + attempt)

        ids = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as threads:
            for receipt_id in threads.map(send, range(size)):
                ids.append(receipt_id)
                report["accepted"] = len(ids)
        if len(set(ids)) != size or send(0) != ids[0]:
            raise RuntimeError("record identity or idempotent replay mismatch")
        report["admission_seconds"] = time.monotonic() - start
        save()
        while time.monotonic() - start < args.deadline:
            try:
                result = api(root + "/knowledge/receipts")
            except TimeoutError:
                report["poll_timeouts"] += 1
            else:
                counts = {row["status"]: row["count"] for row in result["counts"]}
                report.update(durable=sum(counts.values()), counts=counts, elapsed_seconds=time.monotonic() - start)
                if counts == {"bound": size}:
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
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
