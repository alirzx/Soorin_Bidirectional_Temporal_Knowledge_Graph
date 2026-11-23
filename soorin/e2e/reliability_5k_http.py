#!/usr/bin/env python3
"""Bounded, resumable 5k+ synthetic SOC HTTP acceptance for isolated or explicitly approved TKG Compose.

Place in soorin/e2e/reliability_5k_http.py and invoke as:
  python3 -m soorin.e2e.reliability_5k_http --mode prepare --count 5500 --out /mnt/X/Soorin/tkg-acceptance-5k
  python3 -m soorin.e2e.reliability_5k_http --mode send --out /mnt/X/Soorin/tkg-acceptance-5k --source-id "$SOURCE_ID" --kb-id "$KB_ID"
  python3 -m soorin.e2e.reliability_5k_http --mode verify --out /mnt/X/Soorin/tkg-acceptance-5k --source-id "$SOURCE_ID" --kb-id "$KB_ID"

This never creates users, modifies Docker, deletes volumes or exposes secrets in reports.
Default mode accepts only a disposable loopback Compose target. An opt-in server
profile verifies the exact existing app/db ports and volumes, never changes Docker,
and verifies only receipt IDs from the current journal. Use unique test records.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib import error, parse, request

DEFAULT_PROJECT = "soorin-tkg-acceptance-5k"
DEFAULT_BASE = "http://127.0.0.1:2626"
RETRYABLE = {429, 502, 503, 504}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json(url: str, token: str, *, payload: bytes | None = None, timeout: float = 30, run_id: str | None = None) -> dict:
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if run_id:
        headers["X-Soorin-Acceptance-Run"] = run_id
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=payload, headers=headers,
                          method="POST" if payload is not None else "GET")
    with request.build_opener(request.ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
        result = json.loads(response.read(2_000_000))
        if not isinstance(result, dict):
            raise ValueError("non_object_response")
        return result


def _docker_inspect(project: str, service: str) -> dict:
    p = subprocess.run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
                        "--filter", f"label=com.docker.compose.service={service}"],
                       check=True, capture_output=True, text=True, timeout=10)
    ids = p.stdout.split()
    if len(ids) != 1:
        raise RuntimeError(f"expected one running {project}/{service} container; got {len(ids)}")
    data = subprocess.run(["docker", "inspect", ids[0]], check=True,
                          capture_output=True, text=True, timeout=10)
    return json.loads(data.stdout)[0]


def verify_disposable_target(base: str, project: str, db_port: int) -> None:
    u = parse.urlsplit(base)
    if (u.scheme != "http" or u.hostname != "127.0.0.1" or not u.port or
            u.port in {1516, 2516} or u.username or u.password or u.path not in {"", "/"}
            or u.query or u.fragment):
        raise RuntimeError("refusing non-loopback, established-lab or malformed API target")
    if not project.startswith("soorin-tkg-acceptance-"):
        raise RuntimeError("project name must begin with soorin-tkg-acceptance-")
    if db_port in {1517, 2517} or db_port == u.port:
        raise RuntimeError("invalid disposable database port")
    for service, target, container_port, expected_port in (
        ("app", "/app/data", "1516/tcp", u.port),
        ("db", "/var/lib/postgresql/data", "5432/tcp", db_port),
    ):
        obj = _docker_inspect(project, service)
        labels = obj.get("Config", {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
            raise RuntimeError(f"ownership mismatch: {service}")
        if not obj.get("State", {}).get("Running"):
            raise RuntimeError(f"not running: {service}")
        mapping = obj.get("NetworkSettings", {}).get("Ports", {}).get(container_port) or []
        if len(mapping) != 1 or mapping[0].get("HostIp") != "127.0.0.1" or int(mapping[0]["HostPort"]) != expected_port:
            raise RuntimeError(f"port mapping mismatch: {service}")
        mounts = [m for m in obj.get("Mounts", []) if m.get("Destination") == target]
        suffix = "data" if service == "app" else "db"
        required = f"{project}_soorin_sprint1_{suffix}"
        if len(mounts) != 1 or mounts[0].get("Type") != "volume" or mounts[0].get("Name") != required:
            raise RuntimeError(f"volume ownership mismatch: {service}")


def verify_server_target(base: str, project: str, db_port: int,
                         app_volume: str, db_volume: str) -> None:
    """Read-only ownership check for an explicitly selected existing TKG server."""
    u = parse.urlsplit(base)
    try:
        host = ipaddress.ip_address(u.hostname or "")
    except ValueError as exc:
        raise RuntimeError("server API must use a literal private IP") from exc
    if (u.scheme != "http" or host.version != 4 or not host.is_private or
            host.is_unspecified or host.is_link_local or not u.port or
            u.username or u.password or u.path not in {"", "/"} or u.query or u.fragment):
        raise RuntimeError("refusing public or malformed server API target")
    if not project.startswith("soorin-tkg-") or project.startswith("soorin-tkg-acceptance-"):
        raise RuntimeError("server profile requires an established soorin-tkg project")
    if not (1 <= db_port <= 65535) or db_port == u.port:
        raise RuntimeError("invalid server DB port")
    if (not app_volume.startswith(project + "_") or
            not db_volume.startswith(project + "_") or app_volume == db_volume):
        raise RuntimeError("server volumes must be distinct and owned by the selected project")
    for service, target, container_port, expected_host, expected_port, volume in (
        ("app", "/app/data", "1516/tcp", str(host), u.port, app_volume),
        ("db", "/var/lib/postgresql/data", "5432/tcp", "127.0.0.1", db_port, db_volume),
    ):
        obj = _docker_inspect(project, service)
        labels = obj.get("Config", {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
            raise RuntimeError(f"ownership mismatch: {service}")
        if not obj.get("State", {}).get("Running"):
            raise RuntimeError(f"not running: {service}")
        ports = obj.get("NetworkSettings", {}).get("Ports", {}).get(container_port) or []
        if len(ports) != 1 or ports[0].get("HostIp") != expected_host or int(ports[0]["HostPort"]) != expected_port:
            raise RuntimeError(f"port mapping mismatch: {service}")
        mounts = [m for m in obj.get("Mounts", []) if m.get("Destination") == target]
        if len(mounts) != 1 or mounts[0].get("Type") != "volume" or mounts[0].get("Name") != volume:
            raise RuntimeError(f"volume ownership mismatch: {service}")


def verify_source_in_kb(base: str, kb: str, source: str, session: str) -> None:
    """Fail closed if the supplied push token would target an unrelated KB."""
    response = _json(f"{base}/api/v1/kbs/{kb}/sources", session)
    sources = response.get("sources")
    if not isinstance(sources, list) or not any(
        row.get("id") == source and row.get("kind") == "statements"
        for row in sources if isinstance(row, dict)
    ):
        raise RuntimeError("source is not a Statements source in the selected KB")


def prepare(out: Path, count: int, revisions: int, start_index: int = 0) -> None:
    from soorin.tests.mock_splunk.scripts.curated_qa_dataset import generate
    if out.exists() and any(out.iterdir()):
        raise RuntimeError("output directory is not empty; use a new directory or --mode send")
    report = generate(out, count, revisions, start_index=start_index)
    print(json.dumps({"phase": "prepared", "alerts": report["alerts"],
                      "revisions": report["separate_revisions"], "start_index": start_index, "path": str(out)}))


def load_payloads(out: Path, include_revisions: bool) -> list[tuple[str, bytes]]:
    expected = json.loads((out / "manifest.json").read_text())
    names = ["alerts.jsonl"] + (["revisions.jsonl"] if include_revisions else [])
    rows = []
    for name in names:
        data = (out / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected["files_sha256"][name]:
            raise RuntimeError(f"fixture digest mismatch: {name}")
        for number, line in enumerate(data.splitlines()):
            if line.strip():
                rows.append((f"{name}:{number}", line))
    return rows


def existing_acceptances(path: Path) -> dict[str, str]:
    accepted = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line:
                row = json.loads(line)
                accepted[row["item"]] = row["receipt_id"]
    return accepted


class RateLimit:
    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0
        self.lock = threading.Lock()
        self.next_allowed = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_allowed)
            self.next_allowed = start + self.interval
        if start > now:
            time.sleep(start - now)


def send_one(item: str, payload: bytes, endpoint: str, token: str,
             attempts: int, rate: RateLimit, run_id: str | None = None) -> dict:
    history = []
    started = time.monotonic()
    result = {"item": item, "history": history}
    if run_id:
        result["run_id"] = run_id
    for attempt in range(1, attempts + 1):
        rate.wait()
        retry = False
        try:
            value = _json(endpoint, token, payload=payload, timeout=30, run_id=run_id)
            rid = value.get("receipt_id")
            if not isinstance(rid, str) or not rid:
                outcome = "invalid_ack"
            else:
                from uuid import UUID
                rid = str(UUID(rid))
                if value.get("schema_version") != "soorin.ingestion-receipt.v1" or (
                    run_id and not isinstance(value.get("replayed"), bool)
                ):
                    raise ValueError("unexpected receipt contract")
                outcome = "accepted"
                result.update(receipt_id=rid, replayed=value.get("replayed"),
                              status=value.get("status"), acknowledged_at=time.time())
        except error.HTTPError as exc:
            outcome = f"http_{exc.code}"
            retry = exc.code in RETRYABLE
            if exc.code == 409:
                # Only normalizer capacity/timeouts can be retried as conflicts.
                try:
                    detail = json.loads(exc.read(4096)).get("error")
                    retry = detail in ("soc_normalizer_busy", "soc_normalizer_timeout")
                except (ValueError, AttributeError):
                    pass
            result["code"] = exc.code
            exc.close()
        except (TimeoutError, error.URLError, OSError) as exc:
            outcome = "timeout" if isinstance(getattr(exc, "reason", exc), TimeoutError) else "network_error"
            retry = True
        except ValueError:
            outcome = "invalid_response"
        history.append(outcome)
        if not retry or attempt == attempts:
            return dict(result, outcome=outcome, attempt=attempt,
                        latency_seconds=round(time.monotonic() - started, 3))
        time.sleep(min(2 ** (attempt - 1), 10))
    raise AssertionError("unreachable")


def send(out: Path, base: str, source: str, token: str, workers: int,
         attempts: int, rps: float, include_revisions: bool, *, run_id: str | None = None, on_progress=None) -> None:
    rows = load_payloads(out, include_revisions)
    result_path = out / "accepted.jsonl"
    old = existing_acceptances(result_path)
    remaining = [(n, b) for n, b in rows if n not in old]
    endpoint = f"{base}/api/v1/sources/{source}/soc/ingest"
    started = time.monotonic()
    errors = Counter()
    newly_accepted = 0
    limiter = RateLimit(rps)
    print(json.dumps({"phase": "send", "total": len(rows), "previously_accepted": len(old),
                      "remaining": len(remaining), "workers": workers, "rps": rps}), flush=True)
    with result_path.open("a", encoding="utf8") as journal, \
         (out / "failed.jsonl").open("a", encoding="utf8") as bad, \
         ThreadPoolExecutor(max_workers=workers) as executor:
        def completed():
            pending = set()
            todo = iter(remaining)
            while True:
                for name, payload in todo:
                    pending.add(executor.submit(send_one, name, payload, endpoint, token,
                                                attempts, limiter, run_id))
                    if len(pending) >= workers:
                        break
                if not pending:
                    return
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()

        for result in completed():
            if result["outcome"] == "accepted":
                journal.write(json.dumps(result, separators=(",", ":")) + "\n")
                journal.flush()
                newly_accepted += 1
            else:
                bad.write(json.dumps(result, separators=(",", ":")) + "\n")
                bad.flush()
                errors[str(result.get("code", result["outcome"]))] += 1
            processed = newly_accepted + sum(errors.values())
            if on_progress:
                on_progress(processed)
            if processed % 250 == 0 or processed == len(remaining):
                print(json.dumps({"phase": "progress", "processed": processed,
                                  "accepted_new": newly_accepted, "errors": dict(errors),
                                  "seconds": round(time.monotonic() - started, 1)}), flush=True)
    receipts = existing_acceptances(result_path)
    distinct = len(set(receipts.values()))
    final = {"status": "PASS" if distinct == len(rows) == len(receipts) else "FAIL",
             "distinct_receipts": distinct, "phase": "send_final", "accepted_total": len(existing_acceptances(result_path)),
             "expected": len(rows), "errors": dict(errors),
             "seconds": round(time.monotonic() - started, 1)}
    (out / "send-report.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final), flush=True)
    if final["status"] != "PASS":
        raise RuntimeError("admission incomplete: inspect failed.jsonl and rerun --mode send")


def status_groups(value: dict) -> dict[str, int]:
    groups = value.get("groups")
    if not isinstance(groups, list):
        raise RuntimeError("receipt summary missing groups")
    return dict(Counter({key: sum(int(x.get("count", 0)) for x in groups if x.get("status") == key)
                         for key in {str(x.get("status")) for x in groups}}))



def journal_receipt_groups(base: str, kb: str, session: str,
                           receipt_ids: set[str], *, observe=None, until=None, run_id=None) -> tuple[dict[str, int], int, dict[str, int]]:
    """Page KB receipt metadata and count only IDs acknowledged in THIS run.

    A shared KB can contain old receipts; never use its global summary as a run
    acceptance oracle. This API is payload-free and paginated (100 per page).
    """
    found: dict[str, dict] = {}
    cursor = None
    cursors: set[str] = set()
    for _ in range(2000):
        suffix = "?limit=100"
        if run_id:
            suffix += "&acceptance_run=" + parse.quote(run_id, safe="")
        if cursor:
            suffix += "&before=" + parse.quote(cursor, safe="")
        timeout = 30 if until is None else min(30, until - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("receipt scan deadline")
        page = _json(f"{base}/api/v1/kbs/{kb}/knowledge/receipts{suffix}", session, timeout=timeout)
        rows = page.get("receipts")
        if not isinstance(rows, list):
            raise RuntimeError("receipt listing missing receipts")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("malformed receipt listing")
            rid = row.get("receipt_id")
            if rid in receipt_ids:
                found[rid] = row
                if observe:
                    observe(row)
        if len(found) == len(receipt_ids):
            break
        cursor = page.get("next_cursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or cursor in cursors:
            raise RuntimeError("invalid/repeated receipt page cursor")
        cursors.add(cursor)
    else:
        raise RuntimeError("receipt pagination safety limit exceeded")
    statuses = dict(Counter(str(row.get("status", "unknown")) for row in found.values()))
    deliveries = dict(Counter(str(row.get("delivery_state", "unknown")) for row in found.values()))
    return statuses, len(receipt_ids) - len(found), deliveries



def verify(out: Path, base: str, kb: str, session: str, include_revisions: bool,
           deadline: int, interval: float, sample: int, *, run_scoped: bool = False) -> None:
    expected = len(load_payloads(out, include_revisions))
    accepted = existing_acceptances(out / "accepted.jsonl")
    if len(accepted) != expected:
        raise RuntimeError(f"{len(accepted)} accepted vs {expected} expected; finish --mode send")
    receipt_ids = set(accepted.values())
    if len(receipt_ids) != expected:
        raise RuntimeError("multiple fixture records resolved to the same receipt; check replay/overlap")
    summary_url = f"{base}/api/v1/kbs/{kb}/knowledge/receipts/summary"
    started = time.monotonic()
    groups = {}
    missing = 0
    deliveries = {}
    while True:
        if run_scoped:
            groups, missing, deliveries = journal_receipt_groups(base, kb, session, receipt_ids)
        else:
            value = _json(summary_url, session, timeout=30)
            groups = status_groups(value)
        total = sum(groups.values())
        print(json.dumps({"phase": "materialization", "groups": groups, "total": total,
                          "missing": missing, "expected": expected,
                          "elapsed_seconds": round(time.monotonic()-started, 1)}), flush=True)
        if missing == 0 and total == expected and groups.get("bound", 0) == expected:
            break
        if time.monotonic() - started >= deadline:
            break
        time.sleep(interval)
    graph_checks = []
    if missing == 0 and groups.get("bound", 0) == expected:
        ids = list(dict.fromkeys(accepted.values()))
        for rid in ids[:sample]:
            detail = _json(f"{base}/api/v1/kbs/{kb}/knowledge/receipts/{rid}", session)
            doc = detail.get("document") or {}
            rels = detail.get("relations") or []
            healthy = (detail.get("status") == "bound" and doc.get("status") == "ready"
                       and doc.get("graph_status") == "done"
                       and not detail.get("entities_truncated")
                       and not detail.get("relations_truncated")
                       and all((r.get("binding") or {}).get("evidence_link_status") is True
                               for r in rels))
            graph_checks.append(healthy)
    result = {"schema_version": "soorin.local-5k-acceptance.v1", "synthetic": True,
              "admitted": len(accepted), "expected": expected, "groups": groups,
              "run_scoped": run_scoped, "missing_run_receipts": missing,
              "run_delivery_states": deliveries,
              "seconds_waited": round(time.monotonic() - started, 1),
              "sampled_graph_checks": len(graph_checks),
              "sampled_graph_checks_passed": sum(graph_checks),
              "receipt_binding_pass": missing == 0 and groups.get("bound", 0) == expected and sum(groups.values()) == expected,
              "sampled_graph_pass": len(graph_checks) == sample and all(graph_checks)}
    (out / "acceptance-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"phase": "verify_final", **result}), flush=True)
    if not result["receipt_binding_pass"] or not result["sampled_graph_pass"]:
        raise RuntimeError("acceptance failed; report saved with observed evidence")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["prepare", "send", "verify"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--count", type=int, default=5500)
    p.add_argument("--revisions", type=int, default=0)
    p.add_argument("--start-index", type=int, default=0, help="first synthetic alert index; use 1 on Server 55 after smoke alert zero")
    p.add_argument("--include-revisions", action="store_true")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--project", default=DEFAULT_PROJECT)
    p.add_argument("--db-port", type=int, default=2627)
    p.add_argument("--target-profile", choices=["disposable", "server"], default="disposable")
    p.add_argument("--allow-existing-server", action="store_true", help="explicit opt-in to the live TKG server lab")
    p.add_argument("--expected-app-volume", default="")
    p.add_argument("--expected-db-volume", default="")
    p.add_argument("--source-id", default=os.environ.get("SOURCE_ID", ""))
    p.add_argument("--kb-id", default=os.environ.get("KB_ID", ""))
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--rps", type=float, default=3.0)
    p.add_argument("--attempts", type=int, default=4)
    p.add_argument("--deadline", type=int, default=3600)
    p.add_argument("--interval", type=float, default=15)
    p.add_argument("--sample", type=int, default=20)
    args = p.parse_args()
    if not 1 <= args.workers <= 8 or not 1 <= args.attempts <= 8 or not 0 < args.rps <= 100:
        p.error("workers 1..8, attempts 1..8, rps 0..100 required")
    if args.mode == "prepare":
        if args.start_index < 0 or args.start_index + args.count > 100000:
            p.error("start-index must be >=0 and end index <=100000")
        prepare(args.out, args.count, args.revisions, args.start_index)
        return
    if args.target_profile == "server":
        if not args.allow_existing_server:
            p.error("server profile requires --allow-existing-server")
        if not (args.expected_app_volume and args.expected_db_volume):
            p.error("server profile requires both expected volume names")
        verify_server_target(args.base_url, args.project, args.db_port,
                             args.expected_app_volume, args.expected_db_volume)
        if not args.kb_id or not args.source_id or not os.environ.get("SESSION_TOKEN"):
            p.error("server profile requires KB_ID, SOURCE_ID and SESSION_TOKEN for scoped verification")
        verify_source_in_kb(args.base_url, args.kb_id, args.source_id, os.environ["SESSION_TOKEN"])
    else:
        verify_disposable_target(args.base_url, args.project, args.db_port)
    if args.mode == "send":
        if not args.source_id or not os.environ.get("INGEST_TOKEN"):
            p.error("SOURCE_ID/--source-id and INGEST_TOKEN are required")
        send(args.out, args.base_url, args.source_id, os.environ["INGEST_TOKEN"],
             args.workers, args.attempts, args.rps, args.include_revisions)
    else:
        if not args.kb_id or not os.environ.get("SESSION_TOKEN"):
            p.error("KB_ID/--kb-id and SESSION_TOKEN are required")
        if not 1 <= args.sample <= 100:
            p.error("sample must be 1..100")
        verify(args.out, args.base_url, args.kb_id, os.environ["SESSION_TOKEN"],
               args.include_revisions, args.deadline, args.interval, args.sample,
               run_scoped=args.target_profile == "server")


if __name__ == "__main__":
    main()
