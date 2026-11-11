#!/usr/bin/env python3
"""Validate the foundation offline or against an explicitly approved QA project.

Live execution verifies Docker ownership and project-specific volumes,
requires separate source-ingest and session credentials, and
never prints either credential or provider response bodies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import subprocess
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request
import uuid

from soorin.adapters.splunk import normalize_llm_payload
from soorin.adapters.utopia import StatementsAdapter, StatementsClient, StatementsError
from soorin.contracts import EvidenceReference, SecurityKnowledgeEvent
from soorin.identity import IdentityInput, resolve_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "soc_e2e_scenarios_v1.json"
DEFAULT_BASE_URL = "http://127.0.0.1:2516"
STATUSES = {"PASS", "FAIL", "SKIPPED", "BLOCKED", "NOT RUN"}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def progress(stage: str, **values: Any) -> None:
    """Content-free progress on stderr; stdout remains one JSON report."""
    print(json.dumps({"stage": stage, **values}, sort_keys=True), file=sys.stderr, flush=True)
REQUIRED_ENTITY_TYPES = {
    "SecurityAlert", "SplunkNotable", "SecurityEvent", "DetectionRule", "Host",
    "IPAddress", "UserAccount", "MITRETechnique", "EvidenceReference", "SOCCase", "Ticket",
}
EXPECTED_LIVE_RELATIONS = {
    "correlated with", "supported by", "detected by", "observed on", "originated from",
    "involves user", "mapped to technique", "part of case", "tracked by ticket",
}


class ValidationError(ValueError):
    """A redacted validation error safe to include in reports."""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unsupported status: {self.status}")


def _check(name: str, status: str, detail: str, **evidence: Any) -> Check:
    return Check(name, status, detail, evidence or None)


def select_isolated_api(base_url: str, *, qa_project: str | None = None, approved_port: int | None = None) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValidationError("live E2E accepts only an HTTP loopback API")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("invalid API port") from exc
    if port == 1516:
        raise ValidationError("refusing the existing Utopia/SOC lab on port 1516")
    if qa_project is not None:
        from .qa_target import PROJECT
        if (qa_project != PROJECT or type(approved_port) is not int
                or not 1024 <= approved_port <= 65535 or approved_port in {1516, 1517, 2516, 2517}
                or port != approved_port or parsed.hostname != "127.0.0.1"):
            raise ValidationError("explicit disposable QA project and unused loopback port required")
    elif port != 2516:
        raise ValidationError("legacy selection requires port 2516; other ports require explicit QA approval")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("API URL must not contain credentials, query parameters, or fragments")
    path = parsed.path.rstrip("/")
    if path:
        raise ValidationError("API URL must not contain a path")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _load_fixture(path: Path) -> list[Mapping[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("synthetic") is not True:
        raise ValidationError("fixture must be explicitly labeled synthetic=true")
    records = value.get("records")
    if not isinstance(records, list) or not records:
        raise ValidationError("fixture records must be a nonempty array")
    scenarios: set[str] = set()
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise ValidationError(f"records[{index}] must be an object")
        scenario = row.get("scenario")
        if not isinstance(scenario, str) or not scenario or scenario in scenarios:
            raise ValidationError(f"records[{index}] has a missing or duplicate scenario")
        if not isinstance(row.get("raw_record"), Mapping):
            raise ValidationError(f"records[{index}].raw_record must be an object")
        scenarios.add(scenario)
    return records


def _with_second_evidence(event: SecurityKnowledgeEvent) -> SecurityKnowledgeEvent:
    first = event.evidence[0]
    second_id = first.evidence_id + ":secondary"
    second = EvidenceReference(
        second_id,
        first.source_record_id,
        field_path="raw_record.source_event_ids",
        checksum=first.checksum,
        observed_at=first.observed_at,
        source_system=first.source_system,
        source_instance=first.source_instance,
        source_event_ids=first.source_event_ids,
        source_revision_id=first.source_revision_id,
    )
    relations = tuple(
        replace(relation, evidence_ids=tuple(dict.fromkeys((*relation.evidence_ids, second_id))))
        for relation in event.relations
    )
    return replace(
        event,
        relations=relations,
        evidence=(*event.evidence, second),
        content_checksum=None,
    )


def normalize_fixture(records: list[Mapping[str, Any]]) -> list[tuple[str, SecurityKnowledgeEvent]]:
    output: list[tuple[str, SecurityKnowledgeEvent]] = []
    for row in records:
        normalized = normalize_llm_payload(
            row.get("llm_payload"),
            tenant_id=str(row.get("tenant_id", "")),
            source_instance=str(row.get("source_instance", "")),
            raw_record=row["raw_record"],
            observed_at="2026-11-02T00:00:00Z",
            recorded_at="2026-11-02T00:00:00Z",
            delivery_id="synthetic-e2e",
        )
        event = normalized.event
        if row.get("multiple_evidence") is True:
            event = _with_second_evidence(event)
        output.append((str(row["scenario"]), event))
    return output


def _offline_checks(events: list[tuple[str, SecurityKnowledgeEvent]]) -> tuple[list[Check], dict[str, dict[str, Any]]]:
    checks: list[Check] = []
    adapter = StatementsAdapter()
    rendered: dict[str, dict[str, Any]] = {}
    try:
        for scenario, event in events:
            rendered[scenario] = adapter.render(event)
        checks.append(_check(
            "normalize_and_render", "PASS", "synthetic records normalized and rendered",
            events=len(events), statements=sum(len(item["s"]) for item in rendered.values()),
        ))
    except (ValueError, StatementsError) as exc:
        checks.append(_check("normalize_and_render", "FAIL", f"{type(exc).__name__}: {exc}"))
        return checks, rendered

    observed_types = {
        str(entity[1])
        for payload in rendered.values()
        for entity in payload["e"]
    }
    missing_types = sorted(REQUIRED_ENTITY_TYPES - observed_types)
    checks.append(_check(
        "required_entity_coverage", "PASS" if not missing_types else "FAIL",
        "all required synthetic entity kinds are represented" if not missing_types else "fixture misses required entity kinds",
        observed=sorted(observed_types), missing=missing_types,
    ))

    baseline = dict(events)["initial_ingestion"]
    replay_payload = adapter.dumps(adapter.render(baseline))
    replay_again = adapter.dumps(adapter.render(replace(
        baseline,
        delivery_id="synthetic-e2e-retry",
        recorded_at="2026-11-02T00:05:00Z",
        processed_at="2026-11-02T00:05:00Z",
        content_checksum=None,
    )))
    checks.append(_check(
        "exact_replay_payload", "PASS" if replay_payload == replay_again else "FAIL",
        "processing-only replay metadata does not alter serialized Statements",
    ))

    by_scenario = dict(events)
    initial_id = adapter.external_id(by_scenario["initial_ingestion"])
    changed_id = adapter.external_id(by_scenario["changed_status"])
    checks.append(_check(
        "revision_identity", "PASS" if initial_id == changed_id and baseline.content_checksum != by_scenario["changed_status"].content_checksum else "FAIL",
        "lifecycle revisions retain document identity while changing source-content checksum",
    ))

    blue = resolve_identity(IdentityInput("tenant-blue", "splunk", "splunk-e2e", "Host", "shared.e2e.example"))
    red = resolve_identity(IdentityInput("tenant-red", "splunk", "splunk-e2e", "Host", "shared.e2e.example"))
    scope_a = resolve_identity(IdentityInput("tenant-blue", "splunk", "splunk-e2e", "IPAddress", "10.20.30.40", scope="vpc-a"))
    scope_b = resolve_identity(IdentityInput("tenant-blue", "splunk", "splunk-e2e", "IPAddress", "10.20.30.40", scope="vpc-b"))
    checks.append(_check(
        "identity_isolation", "PASS" if blue.canonical_key != red.canonical_key and scope_a.canonical_key != scope_b.canonical_key else "FAIL",
        "tenant and network scope remain part of canonical identity",
    ))
    checks.append(_check(
        "persistent_identity_conflict", "BLOCKED",
        "this legacy offline harness does not exercise the active native registry; use native SOC and PostgreSQL acceptance tests",
    ))
    return checks, rendered


def _request_json(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    timeout: float = 15.0,
) -> Mapping[str, Any]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValidationError(f"HTTP {exc.code} for {method} {path.split('?')[0]}") from exc
    except urllib.error.URLError as exc:
        raise ValidationError(f"API unavailable for {method} {path.split('?')[0]}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(f"non-JSON response for {method} {path.split('?')[0]}") from exc
    if not isinstance(value, Mapping):
        raise ValidationError(f"non-object response for {method} {path.split('?')[0]}")
    return value


def _graph_assertions(graph: Mapping[str, Any]) -> Check:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return _check("graph_assertions", "FAIL", "graph overview lacks nodes or edges arrays")
    type_keys = {
        str(node.get("type_key", "")).casefold()
        for node in nodes if isinstance(node, Mapping) and node.get("type_key")
    }
    # Open graph labels/said_as do not establish a typed ontology binding.
    relation_text = {
        str(value).casefold()
        for edge in edges if isinstance(edge, Mapping)
        for value in (edge.get("predicate"),)
        if value and edge.get("inferred") is False and not edge.get("derived", False)
    }
    expected_type_keys = {
        "security_alert", "splunk_notable", "security_event", "detection_rule", "host",
        "ip_address", "user_account", "mitre_technique", "evidence_reference", "soc_case", "ticket",
    }
    missing_types = sorted(expected_type_keys - type_keys)
    missing_relations = sorted({word.replace(" ", "_") for word in EXPECTED_LIVE_RELATIONS} - relation_text)
    status = "PASS" if not missing_types and not missing_relations else "FAIL"
    return _check(
        "graph_assertions", status,
        "actual graph contains the expected typed entities and relations" if status == "PASS" else "actual graph is missing expected materialization",
        missing_types=missing_types, missing_relations=missing_relations,
        returned_nodes=len(nodes), returned_edges=len(edges),
        total_nodes=graph.get("total_nodes"), total_edges=graph.get("total_edges"),
    )


def _live_checks(
    base_url: str,
    kb_id: str,
    source_id: str,
    ingest_token: str,
    session_token: str,
    events: list[tuple[str, SecurityKnowledgeEvent]],
    rendered: Mapping[str, Mapping[str, Any]],
    *,
    timeout: float,
    poll_seconds: float,
    semantic_enabled: bool,
    journal: list[Check] | None = None,
) -> list[Check]:
    checks: list[Check] = journal if journal is not None else []
    try:
        health = _request_json(base_url, "/api/v1/health", timeout=timeout)
        checks.append(_check("api_health", "PASS", "isolated API returned JSON health", keys=sorted(health)))
        before_graph = _request_json(base_url, f"/api/v1/kbs/{kb_id}/graph/overview?limit=1000", token=session_token, timeout=timeout)
        before_failed = _request_json(base_url, f"/api/v1/kbs/{kb_id}/jobs/failed", token=session_token, timeout=timeout)
        inventory = _request_json(base_url, f"/api/v1/kbs/{kb_id}/sources", token=session_token, timeout=timeout)
        sources = inventory.get("sources", [])
        selected = next((row for row in sources if row.get("id") == source_id), None)
        if selected is None or selected.get("kind") != "statements":
            checks.append(_check("source_preflight", "BLOCKED", "selected source must belong to this KB and have kind=statements"))
            return checks
        documents = _request_json(base_url, f"/api/v1/kbs/{kb_id}/documents?source={source_id}&limit=200", token=session_token, timeout=timeout)
        checks.append(_check("source_preflight", "PASS", "Statements source inventoried before mutation", source_name=selected.get("name"), documents=documents.get("total")))
        progress("source_preflight", documents=documents.get("total"), source_kind=selected.get("kind"))
        checks.append(_check("session_credentials", "PASS", "session credential can read the selected knowledge base"))
    except ValidationError as exc:
        checks.append(_check("session_credentials", "FAIL", str(exc)))
        return checks

    client = StatementsClient(base_url, source_id, ingest_token, timeout_seconds=timeout)
    push_order = [
        "initial_ingestion", "initial_ingestion", "changed_status", "corrected_source_event",
        "late_arriving_event", "same_host_second_alert", "same_ip_scope_a", "same_ip_scope_b",
    ]
    actions: list[tuple[str, str]] = []
    knowledge_before = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        for scenario in push_order:
            actions.append((scenario, client.push(rendered[scenario])))
            progress("statements_push", scenario=scenario, action=actions[-1][1])
    except StatementsError as exc:
        checks.append(_check("statements_push", "FAIL", f"{exc.code}: Statements push failed"))
        return checks
    replay_action = actions[1][1]
    checks.append(_check(
        "statements_push", "PASS" if replay_action == "unchanged" else "FAIL",
        "source credential accepted synthetic Statements and exact replay was inspected",
        action_counts=dict(Counter(action for _, action in actions)), replay_action=replay_action,
    ))

    deadline = time.monotonic() + poll_seconds
    graph = before_graph
    poll_error: str | None = None
    fetched_after_push = False
    attempts = 0
    while True:
        attempts += 1
        try:
            graph = _request_json(base_url, f"/api/v1/kbs/{kb_id}/graph/overview?limit=1000", token=session_token, timeout=timeout)
            fetched_after_push = True
            assertion = _graph_assertions(graph)
            progress("materialization", attempt=attempts, remaining_seconds=round(max(0, deadline-time.monotonic()), 1), **dict(assertion.evidence or {}))
            if assertion.status == "PASS":
                break
        except (ValidationError, TypeError, ValueError) as exc:
            poll_error = str(exc)
        if time.monotonic() >= deadline:
            break
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
    try:
        after_failed = _request_json(base_url, f"/api/v1/kbs/{kb_id}/jobs/failed", token=session_token, timeout=timeout)
        before_count = int(before_failed.get("failed", 0))
        after_count = int(after_failed.get("failed", 0))
        # A stable failed count is not completion and existing failures matter.
        status = "PASS" if after_count == 0 else "BLOCKED"
        checks.append(_check(
            "background_jobs", status,
            "KB-wide failed-job inventory; per-document completion is checked separately",
            failed_before=before_count, failed_after=after_count,
        ))
    except (ValidationError, TypeError, ValueError) as exc:
        checks.append(_check("background_jobs", "BLOCKED", str(exc)))
    if poll_error and not fetched_after_push:
        checks.append(_check("graph_fetch", "BLOCKED", poll_error))
    else:
        checks.append(_check(
            "graph_fetch", "PASS", "actual graph overview fetched after ingestion",
            total_nodes=graph.get("total_nodes"), total_edges=graph.get("total_edges"),
        ))
        checks.append(_graph_assertions(graph))
        docs = _request_json(base_url, f"/api/v1/kbs/{kb_id}/documents?source={source_id}&limit=200", token=session_token, timeout=timeout)
        rows = docs.get("docs", [])
        states = Counter(str(row.get("graph_status")) for row in rows)
        checks.append(_check("document_completion", "PASS" if rows and all(row.get("graph_status") == "done" for row in rows) else "BLOCKED", "source document graph completion", states=dict(states), total=docs.get("total")))

    try:
        at = urllib.parse.quote("2026-10-20T10:00:00Z")
        # Use actual run knowledge time; fixture event dates are world time.
        as_of = urllib.parse.quote(knowledge_before)
        historical = _request_json(
            base_url, f"/api/v1/kbs/{kb_id}/graph/overview?limit=1000&at={at}&as_of={as_of}",
            token=session_token, timeout=timeout,
        )
        checks.append(_check(
            "temporal_historical_query", "BLOCKED",
            "historical response captured at actual pre-ingest knowledge time; lifecycle fact/value assertions require an isolated clean source",
            total_nodes=historical.get("total_nodes"), total_edges=historical.get("total_edges"),
        ))
    except ValidationError as exc:
        checks.append(_check("temporal_historical_query", "BLOCKED", str(exc)))

    for name, query in (
        ("identifier_lexical_search", "SOC-E2E-ALERT-001"),
        ("bm25_search", "synthetic e2e password spray"),
    ):
        try:
            result = _request_json(
                base_url, f"/api/v1/kbs/{kb_id}/search", token=session_token, method="POST",
                body={"q": query, "top_k": 10}, timeout=timeout,
            )
            rows = result.get("results")
            ok = isinstance(rows, list) and bool(rows)
            checks.append(_check(name, "PASS" if ok else "FAIL", "search returned actual indexed chunks", result_count=len(rows) if isinstance(rows, list) else None))
        except ValidationError as exc:
            checks.append(_check(name, "BLOCKED", str(exc)))

    if semantic_enabled:
        try:
            result = _request_json(
                base_url, f"/api/v1/kbs/{kb_id}/search", token=session_token, method="POST",
                body={"q": "credential guessing behavior", "top_k": 10}, timeout=timeout,
            )
            rows = result.get("results")
            ok = isinstance(rows, list) and bool(rows)
            diagnostics = result.get("retrieval", {})
            executed = diagnostics.get("dense_executed") is True
            checks.append(_check(
                "semantic_search", "PASS" if ok and executed else "BLOCKED" if ok else "FAIL",
                "native retrieval channel diagnostics checked",
                result_count=len(rows) if isinstance(rows, list) else None,
                dense_executed=executed, reranker_status=diagnostics.get("reranker_status", "unknown"),
            ))
        except ValidationError as exc:
            checks.append(_check("semantic_search", "BLOCKED", str(exc)))
    else:
        checks.append(_check("semantic_search", "SKIPPED", "embedding availability was not declared with --semantic-enabled"))
    checks.append(_check(
        "live_identity_conflict", "BLOCKED",
        "this legacy Statements harness does not submit native knowledge-events receipts; native DB/API tests exercise registry activation and conflicts",
    ))
    return checks


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    checks: list[Check] = []
    try:
        base_url = select_isolated_api(args.base_url, qa_project=getattr(args, "qa_project", None), approved_port=getattr(args, "approved_port", None))
        checks.append(_check("isolated_api_selection", "PASS", "selected loopback Soorin source-build API", base_url=base_url))
        records = _load_fixture(args.fixture)
        events = normalize_fixture(records)
        offline, rendered = _offline_checks(events)
        checks.extend(offline)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        checks.append(_check("offline_preflight", "FAIL", f"{type(exc).__name__}: {exc}"))
        base_url = args.base_url
        events, rendered = [], {}

    if args.execute and not any(check.status == "FAIL" for check in checks):
        ingest_token = os.environ.get("UTOPIA_INGEST_TOKEN", "")
        session_token = os.environ.get("UTOPIA_SESSION_TOKEN", "")
        source_id = os.environ.get("UTOPIA_SOURCE_ID", "")
        kb_id = os.environ.get("UTOPIA_KB_ID", "")
        try:
            from .qa_target import verify_qa_target
            verify_qa_target(base_url, getattr(args, "qa_project", None))
            uuid.UUID(source_id)
            uuid.UUID(kb_id)
            if not ingest_token or not session_token:
                raise ValueError("both credential variables are required")
        except (ValueError, OSError, subprocess.SubprocessError):
            checks.append(_check(
                "credential_presence", "FAIL",
                "--execute requires a verified disposable QA target plus valid UTOPIA_SOURCE_ID, UTOPIA_KB_ID, UTOPIA_INGEST_TOKEN, and UTOPIA_SESSION_TOKEN",
            ))
        else:
            checks.append(_check("credential_presence", "PASS", "required credential variables are present and identifiers are UUIDs"))
            live_journal: list[Check] = []
            try:
                _live_checks(
                    base_url, kb_id, source_id, ingest_token, session_token, events, rendered,
                    timeout=args.timeout, poll_seconds=args.poll_seconds, semantic_enabled=args.semantic_enabled,
                    journal=live_journal,
                )
            except KeyboardInterrupt:
                checks.append(_check("interrupted", "BLOCKED", "operator interrupted live execution; partial ingestion may have succeeded; inventory before retry"))
            except (ValidationError, TimeoutError) as exc:
                checks.append(_check("live_transport", "BLOCKED", str(exc)))
            finally:
                checks.extend(live_journal)
    elif not args.execute:
        for name in (
            "credential_presence", "api_health", "session_credentials", "statements_push", "background_jobs",
            "graph_fetch", "graph_assertions", "temporal_historical_query", "identifier_lexical_search", "bm25_search",
        ):
            checks.append(_check(name, "NOT RUN", "live execution requires explicit --execute"))
        checks.append(_check("semantic_search", "SKIPPED", "live execution and an available embedding model are required"))

    counts = Counter(check.status for check in checks)
    passed = counts.get("FAIL", 0) == 0 and (not args.execute or counts.get("BLOCKED", 0) == 0)
    report = {
        "schema_version": "soorin.soc.e2e-report.v1",
        "synthetic": True,
        "started_at": started,
        "mode": "live-isolated" if args.execute else "offline-preflight",
        "fixture": str(args.fixture),
        "checks": [asdict(check) for check in checks],
        "summary": {status: counts.get(status, 0) for status in sorted(STATUSES)},
        "passed": passed,
    }
    return report, 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--base-url", default=os.environ.get("UTOPIA_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--qa-project")
    parser.add_argument("--approved-port", type=int)
    parser.add_argument("--execute", action="store_true", help="mutate only the isolated synthetic source")
    parser.add_argument("--semantic-enabled", action="store_true", help="operator confirms the workspace embedding model is configured")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--poll-seconds", type=float, default=45.0)
    parser.add_argument("--report", type=Path, help="also write the JSON report to this path")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or not 0 <= args.poll_seconds <= 60:
        parser.error("--timeout must be positive and --poll-seconds must be between 0 and 60")
    report, exit_code = build_report(args)
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
