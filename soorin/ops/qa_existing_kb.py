#!/usr/bin/env python3
"""QA operator for an EXISTING Soorin SOC KB. Never deletes workspaces, KBs or sources.

Run from the Soorin TKG repository root. Requires UTOPIA_SESSION_TOKEN in the
process environment and local QA containers with verified Docker ownership for writes.
All payloads are synthetic; persisted receipts contain only metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time
from urllib import error, request
import uuid

BASE = "http://127.0.0.1:2526"
PROJECT = "soorin-tkg-v1-qa"
SOURCE_NAME = "Soorin Splunk Synthetic Alerts"
PROFILE = "agentic-soc.splunk-curated.v1"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTP = request.build_opener(NoRedirect())


def die(message: str):
    raise SystemExit("ERROR: " + message)


def api(method: str, path: str, token: str, data=None, *, content_type="application/json", timeout=20):
    url = BASE + path
    hdr = {"Authorization": "Bearer " + token, "Content-Type": content_type}
    wire = None if data is None else json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    req = request.Request(url, data=wire, headers=hdr, method=method)
    for i in range(4):
        try:
            with HTTP.open(req, timeout=timeout) as response:
                payload = response.read(2_000_000)
                return json.loads(payload) if payload else {}
        except error.HTTPError as ex:
            if ex.code in {409, 429} and method == "POST" and i < 3:
                time.sleep((i + 1) * 2)
                continue
            die(f"HTTP {ex.code}, {method} {path}; response body deliberately hidden")
        except (error.URLError, TimeoutError) as ex:
            die(f"Transport failure ({type(ex).__name__}), {method} {path}; not claiming success")
    die(f"Unreachable HTTP retry state for {path}")


def session_token():
    token = os.environ.get("UTOPIA_SESSION_TOKEN", "").strip()
    if token:
        return token
    try:
        from soorin.ops.qa_login import load_token
        return load_token()
    except (ValueError, OSError, KeyError, json.JSONDecodeError):
        die("No valid QA session: run python3 -m soorin.ops.qa_login directly in your terminal.")


def find_existing_kb(token: str, kb_name: str):
    candidates = []
    workspaces = api("GET", "/api/v1/workspaces", token)
    if not isinstance(workspaces, list):
        die("Unexpected /workspaces response")
    for ws in workspaces:
        for kb in api("GET", f"/api/v1/workspaces/{ws['id']}/kbs", token):
            if kb.get("name") == kb_name:
                candidates.append((ws, kb))
    if len(candidates) != 1:
        die(f"Expected one already-existing KB named {kb_name!r}, found {len(candidates)}; refusing to create or modify any KB")
    return candidates[0]


def qa_guard():
    if os.environ.get("SOORIN_DISPOSABLE_ACCEPTANCE") != "1":
        die("Explicit QA opt-in required: export SOORIN_DISPOSABLE_ACCEPTANCE=1")
    try:
        from soorin.e2e.qa_target import verify_qa_target
        verify_qa_target(BASE, PROJECT)
    except Exception as ex:
        die(f"QA ownership verification failed ({type(ex).__name__}); no HTTP mutation")


def sources(token: str, kb_id: str):
    rows = api("GET", f"/api/v1/kbs/{kb_id}/sources", token)
    return rows["sources"]


def choose_source(token, kb_id, create=False):
    rows = [s for s in sources(token, kb_id) if s.get("name") == SOURCE_NAME]
    if len(rows) > 1:
        die("Duplicate candidate QA sources; refusing to choose one")
    if rows and rows[0].get("kind") != "statements":
        die("Existing QA source has wrong kind; do not modify it")
    if not rows:
        if not create:
            die("Dedicated Statements source does not exist. Run prepare first.")
        created = api("POST", f"/api/v1/kbs/{kb_id}/sources", token,
                      {"kind": "statements", "name": SOURCE_NAME, "config": {}})
        if not created.get("source", {}).get("id"):
            die("Source creation returned no UUID")
        rows = [created["source"]]
    return rows[0]


def source_key(token, kb_id, source_id):
    result = api("GET", f"/api/v1/kbs/{kb_id}/sources/{source_id}/token", token)
    key = result.get("ingest_token")
    if not key or not isinstance(key, str):
        die("Missing source ingestion token")
    return key


def read_records(path: Path, offset: int, count: int):
    if offset < 0 or count <= 0 or count > 500:
        die("offset must be >=0 and count 1..500")
    if not path.is_file():
        die(f"Dataset file not found: {path}")
    records = []
    with path.open(encoding="utf-8") as stream:
        for i, line in enumerate(stream):
            if i < offset:
                continue
            if len(records) >= count:
                break
            item = json.loads(line)
            if set(item) != {"profile", "record"} or item["profile"] != PROFILE or not isinstance(item["record"], dict):
                die(f"Unsupported curated envelope at row {i}")
            records.append((i, item))
    if not records:
        die("No dataset rows in selected range")
    return records


def state_file():
    root = Path.home() / ".local" / "state" / "soorin-tkg-v1-qa"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return root / "receipt-ids.jsonl"


def append_receipt(kb, source, dataset, index, obj):
    path = state_file()
    event = {"kb_id": kb, "source_id": source, "dataset": dataset,
             "index": index, "receipt_id": obj["receipt_id"], "job_id": obj.get("job_id")}
    with path.open("a", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(json.dumps(event, separators=(",", ":")) + "\n")


def tracked_receipts(kb, dataset, offset, count):
    path = state_file()
    if not path.is_file():
        die("No receipt records; ingest a batch first")
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("kb_id") == kb and record.get("dataset") == dataset and offset <= record.get("index", -1) < offset + count:
            records[record["index"]] = record
    if len(records) != count:
        die(f"Expected {count} receipt rows for {dataset} range [{offset},{offset+count}), found {len(records)}. Run ingestion or inspect state before claiming PASS")
    return records


def receipt_summary(token, kb, tracked):
    counts = Counter()
    failures = []
    for i, record in tracked.items():
        path = f"/api/v1/kbs/{kb}/knowledge/receipts/{record['receipt_id']}"
        detail = api("GET", path, token)
        status = detail.get("status", "missing")
        counts[status] += 1
        if status != "bound" and len(failures) < 8:
            doc = detail.get("document") or {}
            failures.append({"row": i, "status": status,
                             "failure": detail.get("failure_code"),
                             "doc_status": doc.get("status"),
                             "graph_status": doc.get("graph_status"),
                             "jobs": [{"kind": x.get("kind"), "status": x.get("status"),
                                       "attempts": x.get("attempts")} for x in detail.get("jobs", [])[:4]]})
    return counts, failures


def check_core(token, kb, source, sample_record, source_token, *, strict=False):
    q = "Password Spray Detection"
    search = api("POST", f"/api/v1/kbs/{kb}/search", token, {"q": q, "top_k": 10})
    rmeta = search.get("retrieval", {})
    print("SEARCH", json.dumps({"query": q, "count": len(search.get("results", [])),
          "retrieval": rmeta}, ensure_ascii=False))
    alert_id = sample_record["record"].get("alert_row_id")
    if not alert_id:
        die("Sample record has no alert_row_id")
    resolved = api("POST", f"/api/v1/kbs/{kb}/knowledge/resolve", token,
        {"tenant_id": "tenant-blue", "source_system": "splunk", "source_instance": "splunk-e2e",
         "entity_type": "SecurityAlert", "authority_name": "soc_alert_row_id", "source_identifier": alert_id})
    print("EXACT", json.dumps({"alert_row_id": alert_id, "status": resolved.get("status"),
          "candidates": len(resolved.get("candidates", []))}, ensure_ascii=False))
    context = None
    if resolved.get("status") == "resolved":
        entity_id = resolved["candidates"][0]["entity_id"]
        context = api("POST", f"/api/v1/kbs/{kb}/knowledge/context", token,
                      {"tenant_id": "tenant-blue", "entity": entity_id, "limit": 30})
        print("CONTEXT", json.dumps({"entity_id": entity_id,
              "fact_count": len(context.get("facts", [])),
              "evidence_count": len(context.get("evidence_references", [])),
              "retrieval_status": context.get("retrieval_status")}, ensure_ascii=False))
    overview = api("GET", f"/api/v1/kbs/{kb}/graph/overview?limit=100", token)
    print("GRAPH", json.dumps({"total_nodes": overview.get("total_nodes"),
                                 "total_edges": overview.get("total_edges")}, ensure_ascii=False))
    if strict and (not search.get("results") or resolved.get("status") != "resolved" or not context or not context.get("facts")):
        die("Core E2E acceptance incomplete; inspect receipt status and model/search diagnostics")
    if rmeta.get("dense_executed") is not True:
        print("NOTE: Dense inference NOT VERIFIED by current search. Configure CPU embeddings before hybrid acceptance.")
    if rmeta.get("reranker_status") != "complete":
        print("NOTE: Native reranker execution NOT VERIFIED by current search.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=["ids", "inspect", "prepare", "validate", "preview", "ingest", "status", "search", "replay"])
    ap.add_argument("--kb-name", default="Soorin SOC Synthetic Lab")
    ap.add_argument("--file", type=Path, default=Path.home()/".local/share/soorin-tkg-qa/soorin_tkg_synthetic_dataset/alerts.jsonl")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--deadline", type=int, default=600)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    token = session_token()
    ws, kb = find_existing_kb(token, args.kb_name)
    kb_id, ws_id = str(uuid.UUID(kb["id"])), str(uuid.UUID(ws["id"]))
    if args.phase == "ids":
        print(f"export UTOPIA_WORKSPACE_ID='{ws_id}'")
        print(f"export UTOPIA_KB_ID='{kb_id}'")
        return
    if args.phase == "inspect":
        print(json.dumps({"workspace_id": ws_id, "workspace": ws["name"], "kb_id": kb_id,
                         "kb": kb["name"], "sources": [{"id": s.get("id"), "name": s.get("name"),
                         "kind": s.get("kind")} for s in sources(token,kb_id)]}, indent=2, ensure_ascii=False))
        return
    if args.phase == "prepare":
        if not args.execute: die("prepare is a write operation; pass --execute")
        qa_guard()
        out = api("PUT", f"/api/v1/kbs/{kb_id}/knowledge/binding", token,
                  {"tenant_id": "tenant-blue", "source_system": "splunk", "source_instance": "splunk-e2e"})
        src = choose_source(token, kb_id, create=True)
        print(json.dumps({"binding": out, "workspace_id": ws_id, "kb_id": kb_id,
                          "source_id": src["id"], "source_kind": src["kind"],
                          "token": "not displayed or written"}, indent=2))
        return
    if args.phase == "validate":
        from soorin.ops.preview import preview
        rows = read_records(args.file, args.offset, args.count)
        for idx, item in rows:
            event, _ = preview(json.dumps(item["record"]), tenant_id="tenant-blue", source_instance="splunk-e2e")
            print(f"VALIDATE row={idx} entities={len(event.entities)} relations={len(event.relations)}")
        print(f"PASS {len(rows)} synthetic rows locally; no DB writes")
        return
    if args.phase == "status":
        tracked = tracked_receipts(kb_id, args.file.name, args.offset, args.count)
        deadline = time.monotonic() + args.deadline
        while True:
            counts, failures = receipt_summary(token, kb_id, tracked)
            print("RECEIPTS", json.dumps({"tracked":len(tracked), "counts": dict(counts),
                                         "non_bound_samples": failures}, ensure_ascii=False))
            if not args.wait:
                return
            if counts.get("bound", 0) == len(tracked):
                print("PASS all tracked receipts are bound")
                return
            if any(counts.get(k, 0) for k in ("quarantined", "failed")):
                die("A receipt is terminal or quarantined; inspect before resuming")
            if time.monotonic() >= deadline:
                die("Deadline exceeded; receipts are not all bound. No cleanup or retry attempted")
            time.sleep(8)
    src = choose_source(token, kb_id)
    key = source_key(token, kb_id, src["id"])
    if args.phase in {"preview", "ingest", "replay"}:
        qa_guard()
    if args.phase in {"ingest", "replay"} and not args.execute:
        die("HTTP writes require --execute")
    if args.phase in {"preview", "ingest", "replay"}:
        rows = read_records(args.file, args.offset, args.count if args.phase != "replay" else 1)
        for idx, item in rows:
            path = f"/api/v1/sources/{src['id']}/soc/" + ("preview" if args.phase=="preview" else "ingest")
            result = api("POST", path, key, item)
            if args.phase == "preview":
                event = result.get("canonical_event") or {}
                print(f"PREVIEW row={idx} entities={len(event.get('entities', []))} relations={len(event.get('relations', []))} no_db_write=True")
            else:
                receipt = result.get("receipt_id")
                if not receipt: die(f"No receipt_id after request for row {idx}")
                if args.phase == "replay":
                    past = tracked_receipts(kb_id,args.file.name,idx,1)[idx]
                    if past["receipt_id"] != receipt: die("Replay ID differs from original; deduplication regression")
                    print(f"PASS replay row={idx}, same receipt_id={receipt}")
                else:
                    append_receipt(kb_id, src["id"], args.file.name, idx, result)
                    print(f"INGEST row={idx} receipt={receipt} status={result.get('status')} (not yet graph-bound)")
                time.sleep(0.15)
        return
    if args.phase == "search":
        rows = read_records(args.file, args.offset, 1)
        check_core(token, kb_id, src["id"], rows[0][1], key, strict=args.strict)
        return

if __name__ == "__main__":
    main()