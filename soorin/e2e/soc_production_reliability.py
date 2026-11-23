"""Run-scoped synthetic acceptance. Run on the target Docker host. See SERVER55_PRODUCTION_RELEASE.md."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from urllib.error import HTTPError, URLError
from uuid import UUID, uuid4

from soorin.e2e import reliability_5k_http as http
from soorin.evaluation.retrieval_benchmark import _metrics


SERVER = "soorin-tkg-server55"
SERVER_URL = "http://192.168.0.55:2516"
MODEL = "BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181"
DB_VOLUME = SERVER + "_fresh_db_20261123"
APP_VOLUME = SERVER + "_fresh_data_20261123"
REPORTS = ("send-report", "acceptance-report", "job-metrics", "retrieval-report", "resource-summary")
NETWORK_ERRORS = (OSError, URLError, ValueError)
INVALID_RESPONSE = NETWORK_ERRORS + (KeyError, TypeError, IndexError)


def read(out, name):
    return json.loads((out / (name + ".json")).read_text())


def save(out, name, obj):
    tmp = out / (name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    tmp.replace(out / (name + ".json"))


def file_digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def evidence_inputs(out):
    return {name: file_digest(out / name)
            for name in ("manifest.json", "alerts.jsonl", "accepted.jsonl", "failed.jsonl", "run-target.json",
                         *(name + ".json" for name in REPORTS))}


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return {f"p{p}": values[math.ceil(len(values) * p / 100) - 1] for p in (50, 95, 99)}


def db(container, sql, **params):
    # SQL is static source. psql quotes variables as SQL literals via :'name'.
    cmd = ["docker", "exec", "-i", "-e",
           "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000",
           container, "psql", "-XAtq", "-v", "ON_ERROR_STOP=1", "-U", "utopia", "-d", "utopia"]
    for key, value in params.items():
        cmd.extend(["-v", f"{key}={value}"])
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError("read-only PostgreSQL measurement failed")
    return json.loads(result.stdout)


def profile(a):
    if a.target_profile == "server":
        if not a.allow_existing_server:
            raise ValueError("server requires --allow-existing-server")
        if (a.base_url, a.project, a.db_port) != (SERVER_URL, SERVER, 2517):
            raise ValueError("Server 55 host, project or DB port mismatch")
        http.verify_server_target(a.base_url, a.project, a.db_port, APP_VOLUME, DB_VOLUME)
        app = http._docker_inspect(a.project, "app")
        checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                           cwd=Path(__file__).resolve().parents[2], timeout=5).strip()
        if (app["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") != checkout:
            raise ValueError("running Server 55 image revision differs from harness checkout")
        models = http._docker_inspect(a.project, "models")
        if models["Config"]["Image"] != "soorin-tkg-v1-qa-models:latest":
            raise ValueError("unexpected Server 55 model image")
        for internal, port in [(8080, 2811), (8081, 2812), (8082, 2813)]:
            if models["NetworkSettings"]["Ports"].get(f"{internal}/tcp") != [
                {"HostIp": "127.0.0.1", "HostPort": str(port)}
            ]:
                raise ValueError("unexpected model port mapping")
    else:
        http.verify_disposable_target(a.base_url, a.project, a.db_port)


def scope(a):
    return {"kb": str(UUID(a.kb_id)), "source": str(UUID(a.source_id)),
            "tenant_id": a.tenant_id, "source_system": "splunk", "source_instance": a.source_instance,
            "project": a.project, "url": a.base_url, "db_port": a.db_port, "profile": a.target_profile}


def prepare(a):
    target = scope(a)
    http.prepare(a.out, a.count, 0, a.start_index)
    m = read(a.out, "manifest")
    m.update(status="PASS", run_id=str(uuid4()), scope=target, tenant_id=a.tenant_id,
             source_instance=a.source_instance, workload={"workers": a.workers, "rps": a.rps,
             "attempts": a.attempts, "sample": min(a.count, a.sample)})
    save(a.out, "manifest", m)
    for name in REPORTS:
        save(a.out, name, {"status": "NOT_TESTED"})
    for name in ("accepted.jsonl", "failed.jsonl"):
        (a.out / name).touch()
    report(a.out)


def preflight(a, m):
    if scope(a) != m["scope"]:
        raise ValueError("manifest target mismatch")
    profile(a)
    source, kb = m["scope"]["source"], m["scope"]["kb"]
    http.verify_source_in_kb(a.base_url, kb, source, os.environ["SESSION_TOKEN"])
    w = m["workload"]
    if not (1 <= w["workers"] <= 8 and 1 <= w["attempts"] <= 8 and 0 < w["rps"] <= 100
            and 1 <= w["sample"] <= min(m["alerts"], 100) and 1 <= m["alerts"] <= 10000):
        raise ValueError("manifest workload outside bounds")
    rows = http.load_payloads(a.out, False)
    if len(rows) != m["alerts"] or not rows:
        raise ValueError("manifest count mismatch")
    preview = http._json(f"{a.base_url}/api/v1/sources/{source}/soc/preview",
                         os.environ["INGEST_TOKEN"], payload=rows[0][1])
    event = preview["canonical_event"]
    if (preview.get("supports_acceptance_run") is not True or preview.get("persistent_writes") is not False or
            any(event[k] != m["scope"][k] for k in ("tenant_id", "source_instance", "source_system"))):
        raise ValueError("source scope or guarded-admission capability mismatch")
    database = http._docker_inspect(a.project, "db")["Id"]
    app = http._docker_inspect(a.project, "app")
    target = {"database_id": database, "app_container_id": app["Id"], "image_id": app["Image"],
              "revision": (app["Config"].get("Labels") or {}).get("org.opencontainers.image.revision")}
    bound = a.out / "run-target.json"
    identity = {"target": target, "manifest_digest": file_digest(a.out / "manifest.json")}
    if bound.exists() and read(a.out, "run-target") != identity:
        save(a.out, "verified-inputs", {})
        report(a.out)
        raise ValueError("run inputs or deployed target changed; use a new run directory")
    if a.mode == "verify" and not bound.exists():
        raise ValueError("send the dataset on this target before verifying")
    first, last = (json.loads(rows[i][1])["record"]["alert_row_id"] for i in (0, -1))
    occupied = db(database, """
        SELECT count(*) FROM soorin_ingestion_receipts WHERE source_id=:'source'::uuid
        AND acceptance_run IS DISTINCT FROM :'run'::uuid
        AND payload->>'source_record_id' BETWEEN :'first' AND :'last';
    """, source=source, run=str(UUID(m["run_id"])), first=first, last=last)
    if occupied:
        raise ValueError("synthetic record range occupied by another run")
    if a.mode == "send" and not bound.exists():
        if any((a.out / name).stat().st_size for name in ("accepted.jsonl", "failed.jsonl")):
            raise ValueError("existing journals lack target provenance; use a new run directory")
        save(a.out, "run-target", identity)
    return database


def snapshot(a, database):
    app = http._docker_inspect(a.project, "app")
    pg = db(database, """
        SELECT json_build_object('queue_depth',count(*) FILTER(WHERE status='queued'),
          'oldest_due_seconds',extract(epoch FROM now()-min(run_at) FILTER(WHERE status='queued' AND run_at<=now())),
          'running_jobs',count(*) FILTER(WHERE status='running'),
          'worker_limit',(SELECT worker_concurrency FROM deployment_settings LIMIT 1),
          'db_connections',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()),
          'db_max_connections',current_setting('max_connections')::int) FROM jobs;
    """)
    stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}",
                            app["Id"], database], check=True, capture_output=True, text=True, timeout=15)
    values = {"timestamp": time.time(), "deployment": pg, "image_id": app["Image"],
              "revision": (app["Config"].get("Labels") or {}).get("org.opencontainers.image.revision"), "app_db_cpu_memory": stats.stdout.splitlines(),
              "root_free_bytes": shutil.disk_usage("/").free}
    if a.target_profile == "server":
        values["models"] = {}
        for role, port in (("embedding", 2811), ("reranker", 2812)):
            try:
                health = http._json(f"http://127.0.0.1:{port}/ready", "", timeout=3)
                values["models"][role] = {k: health.get(k) for k in
                                          ("ready", "model", "calls", "inference_seconds", "queue_capacity")}
            except NETWORK_ERRORS:
                values["models"][role] = {"ready": False}
    return values


def coverage(database, m):
    cfg = db(database, """
        SELECT json_build_array(s.embed_base_url,s.embed_model,s.embed_dim) FROM knowledge_bases k
        JOIN llm_settings s ON s.workspace_id=k.workspace_id WHERE k.id=:'kb'::uuid;
    """, kb=m["scope"]["kb"])
    digest = hashlib.sha256(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    fingerprint = "sha256:" + digest
    counts = db(database, """
        WITH docs AS (
          SELECT d.id FROM soorin_ingestion_receipts r JOIN documents d ON
          d.kb_id=r.kb_id AND d.source_id=r.source_id AND d.external_key=
          'statements:soorin-soc-v2:'||(r.payload->>'tenant_id')||':'||
          left(encode(sha256(convert_to(r.source_key,'UTF8')),'hex'),24)
          WHERE r.kb_id=:'kb'::uuid AND r.source_id=:'source'::uuid AND r.acceptance_run=:'run'::uuid
          AND d.deleted_at IS NULL)
        SELECT json_build_object('documents_with_chunks',count(DISTINCT c.document_id),
          'active',count(*),'embedded',count(*) FILTER(WHERE c.embedding IS NOT NULL AND
          vector_dims(c.embedding)=1024 AND vector_norm(c.embedding)>0 AND c.embedding_model=:'fingerprint'),
          'incompatible',count(*) FILTER(WHERE c.embedding IS NOT NULL AND
          (vector_dims(c.embedding)<>1024 OR vector_norm(c.embedding)=0 OR c.embedding_model IS DISTINCT FROM :'fingerprint')))
          FROM docs JOIN chunks c ON docs.id=c.document_id WHERE c.superseded_at IS NULL;
    """, kb=m["scope"]["kb"], source=m["scope"]["source"], run=m["run_id"], fingerprint=fingerprint)
    counts.update(model=cfg[1] if cfg[1] == MODEL else "unexpected", dimension=cfg[2],
                  fingerprint=fingerprint, missing=counts["active"] - counts["embedded"],
                  ratio=counts["embedded"] / counts["active"] if counts["active"] else 0)
    ok = (cfg[1:] == [MODEL, 1024] and counts["documents_with_chunks"] == m["alerts"]
          and counts["ratio"] == 1 and not counts["incompatible"])
    return dict(counts, status="PASS" if ok else "FAIL")


def probe(a, q, *, expected=None, as_of=None, topic=None):
    body = {"q": q, "top_k": 10}
    if as_of:
        body["as_of"] = as_of
    started = time.monotonic()
    try:
        r = http._json(f"{a.base_url}/api/v1/kbs/{a.kb_id}/search",
                       os.environ.get("SCOPED_READ_TOKEN") or os.environ["SESSION_TOKEN"],
                       payload=json.dumps(body).encode(), timeout=245)
        meta = r["retrieval"]
        ids = list(dict.fromkeys(str(UUID(row["document_id"])) for row in r["results"]))
        result = {"ok": True, "lexical": meta["lexical_method"], "dense": meta["dense_executed"] is True,
                  "reranker": meta["reranker_status"], "returned": len(ids)}
        if expected and not as_of:
            rel = {expected}
            recall, mrr, ndcg = _metrics(ids, rel, 10)
            result.update(recall5=_metrics(ids, rel, 5)[0], recall10=recall, mrr10=mrr, ndcg10=ndcg)
        if topic:
            result["topic_found"] = any(topic.casefold() in row["text"].casefold() for row in r["results"])
        if as_of:
            result["temporal_pass"] = not ids and meta["lexical_method"] == "postgres_versioned_lexical"
    except INVALID_RESPONSE:
        result = {"ok": False}
    return dict(result, seconds=time.monotonic() - started)


def graph_ok(d, m, rid):
    doc = d.get("document") or {}
    return (d.get("receipt_id") == rid and d.get("source_id") == m["scope"]["source"]
            and all((d.get("source_scope") or {}).get(k) == m["scope"][k]
                    for k in ("tenant_id", "source_system", "source_instance"))
            and d.get("status") == "bound" and doc.get("status") == "ready"
            and doc.get("graph_status") == "done" and (doc.get("document_version") or 0) > 0
            and d.get("evidence_view") == "current_document_version"
            and d.get("unsupported_relation_count") == 0
            and not d.get("relations_truncated") and not d.get("entities_truncated")
            and bool(d.get("entities")) and all(e.get("type_matches") and e.get("authority_linked")
                and e.get("entity_id") for e in d["entities"])
            and bool(d.get("relations")) and all((r.get("binding") or {}).get("evidence_link_status") is True
                                                for r in d["relations"]))


def admission_report(out, elapsed):
    accepted = http.existing_acceptances(out / "accepted.jsonl")
    expected = {item for item, _ in http.load_payloads(out, False)}
    histories, latency, first, replays = Counter(), [], 0, 0
    run = read(out, "manifest")["run_id"]
    previous_failures = set()
    for name in ("failed.jsonl", "accepted.jsonl"):
        with (out / name).open() as journal:
            for line in journal:
                row = json.loads(line)
                if row.get("run_id") != run or row["item"] not in expected:
                    raise ValueError("journal entry outside this dataset")
                histories.update(row["history"])
                if name == "failed.jsonl":
                    previous_failures.add(row["item"])
                else:
                    latency.append(row["latency_seconds"])
                    first += row["attempt"] == 1 and row["item"] not in previous_failures
                    replays += row.get("replayed") is True
    unique = len(set(accepted.values()))
    passed = expected == accepted.keys() and unique == len(expected) == len(latency)
    return {"status": "PASS" if passed else "FAIL", "attempts": histories.total(),
            "retries": histories.total() - len(set(accepted) | previous_failures),
            "outcomes": dict(histories), "first_attempt_successes": first,
            "acknowledged": len(latency), "distinct_receipts": unique, "replayed": replays,
            "duplicate_acknowledgments": len(latency) - unique, "final_failures": len(expected - accepted.keys()),
            "latency_seconds": distribution(latency), "latest_send_seconds": elapsed}


def send(a, m, database):
    settings = m["workload"]
    previous = read(a.out, "send-report")
    journal = admission_report(a.out, 0)
    if previous["status"] == "PASS" and journal["status"] == "PASS":
        return
    before = read(a.out, "resource-summary").get("before") or snapshot(a, database)
    probe_results = read(a.out, "retrieval-report").get("during", [])
    during_resources = read(a.out, "resource-summary").get("during", [])
    # Invalidate a prior verdict before new observations. Keep append-only admissions.
    for name in REPORTS:
        save(a.out, name, {"status": "NOT_TESTED"})
    report(a.out)
    save(a.out, "resource-summary", {"status": "INCONCLUSIVE", "before": before})
    with ThreadPoolExecutor(max_workers=1) as sampler:
        tasks = []
        def sample():
            return (probe(a, f"soc-alert-synthetic-{m['start_index']:05d}"), snapshot(a, database))

        def progress(n):
            if n in {1, max(2, m["alerts"] // 2)} and all(t.done() for t in tasks):
                tasks.append(sampler.submit(sample))
        started = time.monotonic()
        old = len(http.existing_acceptances(a.out / "accepted.jsonl"))
        try:
            http.send(a.out, a.base_url, a.source_id, os.environ["INGEST_TOKEN"], settings["workers"],
                      settings["attempts"], settings["rps"], False, run_id=m["run_id"], on_progress=progress)
        finally:
            elapsed = max(time.monotonic() - started, .001)
            result = admission_report(a.out, elapsed)
            result["accepted_per_second_latest_send"] = (result["acknowledged"] - old) / elapsed
            save(a.out, "send-report", result)
            for task in tasks:
                p, resources = task.result()
                probe_results.append(p)
                during_resources.append(resources)
            save(a.out, "resource-summary", {"status": "INCONCLUSIVE", "before": before,
                                            "during": during_resources[-8:]})
            save(a.out, "retrieval-report", {"status": "INCONCLUSIVE", "during": probe_results[-8:]})


def context_check(a, m, index):
    token = os.environ.get("SCOPED_READ_TOKEN") or os.environ["SESSION_TOKEN"]
    url = f"{a.base_url}/api/v1/kbs/{a.kb_id}/knowledge"
    key = f"soc-alert-synthetic-{index:05d}"
    authority = {k: m["scope"][k] for k in ("tenant_id", "source_system", "source_instance")}
    authority.update(entity_type="SecurityAlert", authority_name="soc_alert_row_id", source_identifier=key)
    try:
        r = http._json(url + "/resolve", token, payload=json.dumps(authority).encode())
        if r["status"] != "resolved" or len(r["candidates"]) != 1 or r["knowledge_base_id"] != a.kb_id:
            return False
        entity = str(UUID(r["candidates"][0]["entity_id"]))
        c = http._json(url + "/context", token, payload=json.dumps({
            "tenant_id": m["scope"]["tenant_id"], "entity": entity, "limit": 10}).encode())
        return bool(c["knowledge_base_id"] == a.kb_id and c["tenant_id"] == m["scope"]["tenant_id"]
                    and c["facts"] and c["evidence_references"])
    except INVALID_RESPONSE:
        return False


def isolation(a, m, rid):
    token = os.environ.get("SCOPED_READ_TOKEN")
    other = os.environ.get("OTHER_KB_ID")
    if not token or not other:
        return "NOT_TESTED"
    other = str(UUID(other))
    if other == a.kb_id:
        return "FAIL"
    for kb, route, body in [(other, "search", {"q": "synthetic"}),
                            (a.kb_id, "knowledge/context", {"tenant_id": "mismatch-" + m["tenant_id"],
                                                           "entity": "synthetic"})]:
        try:
            http._json(f"{a.base_url}/api/v1/kbs/{kb}/{route}", token, payload=json.dumps(body).encode())
        except HTTPError as exc:
            if exc.code in (403, 404):
                continue
        return "FAIL"
    try:
        http._json(f"{a.base_url}/api/v1/kbs/{a.kb_id}/knowledge/receipts/{rid}", token)
    except HTTPError as exc:
        return "PASS" if exc.code in (401, 403, 404) else "FAIL"
    return "FAIL"


def verify(a, m, database):
    out = a.out
    admissions = admission_report(out, read(out, "send-report").get("latest_send_seconds", 0))
    if admissions["status"] != "PASS" or read(out, "send-report")["status"] != "PASS":
        raise RuntimeError("finish successful run-scoped admission first")
    journal = http.existing_acceptances(out / "accepted.jsonl")
    wanted = set(journal.values())
    until = time.monotonic() + a.deadline
    rows, seen_states, jobs = {}, Counter(), []
    def observe(row):
        if row.get("source_id") != a.source_id:
            raise ValueError("journal receipt source mismatch")
        rows[row["receipt_id"]] = row
    groups, missing, delivery = {}, len(wanted), {}
    while time.monotonic() < until:
        try:
            groups, missing, delivery = http.journal_receipt_groups(a.base_url, a.kb_id, os.environ["SESSION_TOKEN"],
                wanted, observe=observe, until=until, run_id=m["run_id"])
        except TimeoutError:
            break
        seen_states.update(groups.keys())
        if len(jobs) < 32:
            jobs.append(snapshot(a, database)["deployment"])
        if ((not missing and groups.get("bound") == len(wanted)) or groups.get("quarantined")
                or delivery.get("terminal_failure") or delivery.get("failed_recoverable")):
            break
        time.sleep(max(0, min(a.interval, until - time.monotonic())))
    url = f"{a.base_url}/api/v1/kbs/{a.kb_id}/knowledge/receipts"
    keys = sorted(journal, key=lambda k: int(k.split(":")[1]))
    sampled = [keys[i * len(keys) // m["workload"]["sample"]] for i in range(m["workload"]["sample"])]
    graph, post, blockers = [], [], Counter()
    pending = [k for k in keys if rows.get(journal[k], {}).get("status") != "bound"]
    for k in dict.fromkeys(pending[:3] + sampled):
        rid = journal[k]
        try:
            detail = http._json(f"{url}/{rid}", os.environ["SESSION_TOKEN"])
        except HTTPError as exc:
            if exc.code != 404:
                raise
            detail = {}
        if k in pending[:3]:
            for j in detail.get("jobs", []):
                if j.get("status") != "done":
                    blockers[(j["kind"], j.get("failure_class") or j["status"])] += 1
        if k in sampled:
            graph.append(bool(graph_ok(detail, m, rid)))
            if len(post) < 5 and graph[-1]:
                index = m["start_index"] + int(k.split(":")[1])
                post.append(probe(a, f"soc-alert-synthetic-{index:05d}", expected=detail["document"]["document_id"]))
    passed = not missing and groups.get("bound") == len(wanted) and all(graph)
    def latency(row):
        return (datetime.fromisoformat(row["updated_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds()
    save(out, "job-metrics", {"status": "PASS" if passed else "FAIL", "deployment_samples": jobs,
          "receipt_states": groups, "delivery_states": delivery, "polls_observing_state": seen_states,
          "missing": missing, "failed": delivery.get("failed_recoverable", 0) + delivery.get("terminal_failure", 0),
          "terminal_failure_rate": (delivery.get("terminal_failure", 0) + groups.get("quarantined", 0)) / len(wanted),
          "unbound_at_deadline": len(pending) if time.monotonic() >= until else 0,
          "bound_latency_seconds": distribution([latency(r) for r in rows.values() if r["status"] == "bound"]),
          "blocked_sample": [{"kind": k, "class": c, "count": n} for (k,c), n in blockers.items()]})
    vectors = coverage(database, m)
    initial_vectors = vectors.copy()
    while passed and vectors["status"] != "PASS" and time.monotonic() < until:
        time.sleep(max(0, min(a.interval, until - time.monotonic())))
        vectors = coverage(database, m)
    save(out, "acceptance-report", {"status": "PASS" if passed and vectors["status"] == "PASS" else "FAIL",
         "bound": groups.get("bound", 0), "expected": len(wanted), "graph_sample": len(graph),
         "graph_pass": sum(graph), "embedding_first_observation": initial_vectors, "embedding": vectors})
    during = read(out, "retrieval-report").get("during", [])
    historical = probe(a, "synthetic", as_of="1970-01-01T00:00:00Z")
    from soorin.tests.mock_splunk.scripts.curated_qa_dataset import SCENARIOS
    topic = SCENARIOS[m["start_index"] % len(SCENARIOS)][0]
    semantic = probe(a, topic, topic=topic)
    context = context_check(a, m, m["start_index"])
    security = isolation(a, m, journal[keys[0]])
    ok = (bool(post) and all(p["ok"] and p["dense"] and p["reranker"] == "complete" and p["recall10"]
                             and p["lexical"] == "tantivy_bm25" for p in post)
          and historical.get("temporal_pass") and context and semantic.get("topic_found")
          and semantic.get("reranker") == "complete" and semantic.get("dense") and all(p["ok"] for p in during))
    overall = "FAIL" if not ok or security == "FAIL" else "PASS" if during and security == "PASS" else "INCONCLUSIVE"
    probes = during + post + [semantic]
    save(out, "retrieval-report", {"status": overall, "during": during, "after": post, "isolation": security,
         "historical": historical, "topic_query": semantic, "resolved_evidence": context, "latency_seconds": distribution([p["seconds"] for p in probes]),
         "success_rate": sum(p["ok"] for p in probes) / len(probes) if probes else None,
         "reranker_complete_rate": sum(p.get("reranker") == "complete" for p in probes) / len(probes) if probes else None,
         "reranker_fallback_rate": sum(p.get("reranker") == "fallback" for p in probes) / len(probes) if probes else None,
         "relevance": {k: statistics.mean(p.get(k, 0) for p in post) if post else None
                       for k in ("recall5", "recall10", "mrr10", "ndcg10")}})
    resource = read(out, "resource-summary")
    resource.update(after=snapshot(a, database), status="PASS" if "before" in resource else "INCONCLUSIVE")
    target = read(out, "run-target")["target"]
    final_app = http._docker_inspect(a.project, "app")
    final_db = http._docker_inspect(a.project, "db")
    if (final_app["Id"] != target["app_container_id"] or final_db["Id"] != target["database_id"] or
            any(sample["image_id"] != target["image_id"] or sample["revision"] != target["revision"]
                for sample in [resource.get("before", {}), resource["after"], *resource.get("during", [])]
                if sample)):
        resource["status"] = "FAIL"
    if a.target_profile == "server" and "before" in resource:
        before, after = resource["before"], resource["after"]
        resource["root_space_used_delta_bytes"] = before["root_free_bytes"] - after["root_free_bytes"]
        duration = after["timestamp"] - before["timestamp"]
        resource["model_busy_fraction"] = {}
        for role in ("embedding", "reranker"):
            start, end = before["models"][role], after["models"][role]
            if (not start.get("ready") or not end.get("ready") or duration <= 0
                    or not isinstance(start.get("inference_seconds"), (float, int))
                    or not isinstance(end.get("inference_seconds"), (float, int))
                    or end["inference_seconds"] < start["inference_seconds"]):
                resource["status"] = "INCONCLUSIVE"
            else:
                resource["model_busy_fraction"][role] = (end["inference_seconds"] - start["inference_seconds"]) / duration
    save(out, "resource-summary", resource)
    save(out, "verified-inputs", evidence_inputs(out))


def report(out):
    states = {name: read(out, name)["status"] for name in REPORTS}
    values = set(states.values())
    status = ("PASS" if values == {"PASS"} else "FAIL" if "FAIL" in values else
              "NOT_TESTED" if values == {"NOT_TESTED"} else "INCONCLUSIVE")
    if status == "PASS":
        proof = out / "verified-inputs.json"
        if not proof.exists() or read(out, "verified-inputs") != evidence_inputs(out):
            status = "INCONCLUSIVE"
            states["verified_inputs"] = "INCONCLUSIVE"
    manifest = read(out, "manifest")
    before = read(out, "resource-summary").get("before", {})
    result = {"status": status, "gates": states, "run_id": manifest["run_id"], "count": manifest["alerts"],
              "scope": manifest["scope"], "revision": before.get("revision"), "image_id": before.get("image_id")}
    save(out, "production-readiness", result)
    summary = [f"# Synthetic acceptance for {manifest['alerts']} alerts", "", f"Overall **{status}**", "",
               f"Run `{manifest['run_id']}` on `{manifest['scope']['project']}`", "",
               *[f"- {k}  {v}" for k, v in states.items()]]
    send_result, accepted, searches = (read(out, name) for name in
                                       ("send-report", "acceptance-report", "retrieval-report"))
    if "distinct_receipts" in send_result:
        summary.extend(["", f"{send_result['distinct_receipts']} distinct receipts from "
                        f"{send_result.get('attempts', 'unknown')} attempts."])
    if "bound" in accepted:
        v = accepted["embedding"]
        summary.append(f"{accepted['bound']} bound. {accepted['graph_pass']}/{accepted['graph_sample']} graph "
                       f"samples passed. Vector coverage {v.get('embedded', '?')}/{v.get('active', '?')}.")
    if searches.get("latency_seconds"):
        summary.append(f"Search p95 {searches['latency_seconds']['p95']:.3f} s. Reranker completion "
                       f"{searches['reranker_complete_rate']:.1%}, fallback {searches['reranker_fallback_rate']:.1%}.")
    (out / "summary.md").write_text("\n".join(summary) + "\n")
    return status


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["prepare", "preflight", "send", "verify", "report"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--target-profile", choices=["disposable", "server"], default="disposable")
    p.add_argument("--allow-existing-server", action="store_true")
    p.add_argument("--base-url")
    p.add_argument("--project")
    p.add_argument("--db-port", type=int)
    p.add_argument("--kb-id", default=os.environ.get("KB_ID", ""))
    p.add_argument("--source-id", default=os.environ.get("SOURCE_ID", ""))
    p.add_argument("--tenant-id", default="tenant-blue")
    p.add_argument("--source-instance", default="splunk-e2e")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--start-index", type=int, default=0)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--attempts", type=int, default=4)
    p.add_argument("--rps", type=float, default=3)
    p.add_argument("--sample", type=int, default=10)
    p.add_argument("--deadline", type=int, default=3600)
    p.add_argument("--interval", type=int, default=20)
    a = p.parse_args(argv)
    server = a.target_profile == "server"
    a.base_url = a.base_url or (SERVER_URL if server else http.DEFAULT_BASE)
    a.project = a.project or (SERVER if server else http.DEFAULT_PROJECT)
    a.db_port = a.db_port or (2517 if server else 2627)
    if not (1 <= a.workers <= 8 and 1 <= a.attempts <= 8 and 0 < a.rps <= 100 and
            1 <= a.sample <= 100 and 1 <= a.deadline <= 86400 and 1 <= a.interval <= 300):
        p.error("workload or polling limit out of range")
    os.umask(0o077)
    if a.mode == "prepare":
        prepare(a)
        return
    with (a.out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if a.mode == "report":
            print(report(a.out))
            return
        a.kb_id, a.source_id = str(UUID(a.kb_id)), str(UUID(a.source_id))
        m = read(a.out, "manifest")
        if a.mode == "verify":
            for name in ("acceptance-report", "job-metrics"):
                save(a.out, name, {"status": "NOT_TESTED"})
            previous = read(a.out, "retrieval-report")
            save(a.out, "retrieval-report", {"status": "INCONCLUSIVE", "during": previous.get("during", [])})
            resource = read(a.out, "resource-summary")
            save(a.out, "resource-summary", {k: v for k, v in dict(resource, status="INCONCLUSIVE").items()
                                            if k in ("status", "before", "during")})
            report(a.out)
        database = preflight(a, m)
        if a.mode == "preflight":
            print("PASS")
            return
        try:
            if a.mode == "send":
                send(a, m, database)
            else:
                verify(a, m, database)
        finally:
            status = report(a.out)
        if a.mode == "verify" and status != "PASS":
            raise SystemExit(status)


if __name__ == "__main__":
    main()
