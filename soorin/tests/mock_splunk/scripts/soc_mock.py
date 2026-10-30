#!/usr/bin/env python3
"""Offline validation/render and optional push for the synthetic Soorin SOC lab.

No third-party dependencies and no real SIEM queries. Utopia rc9 Statements
API accepts open e/s/n contracts, not direct typed graph assertions.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "fixtures" / "synthetic_splunk_soc.json"
ALLOWED_KINDS = {"notable", "alert", "event", "case", "jira"}
KIND_WORD = {
    "notable": "splunk notable",
    "alert": "security alert",
    "event": "windows security event",
    "case": "soc incident case",
    "jira": "jira issue",
}
SCALAR_FIELDS = (
    "severity", "status", "description", "summary", "title", "attempt_count",
    "success_count", "first_seen", "last_seen", "search_name", "orig_sid",
    "rule_name", "EventCode", "EventID", "index", "sourcetype", "search_id",
    "action", "issue_type",
)
LINK_FIELDS = {
    "notable_id": ("correlated with notable", "splunk notable"),
    "case_id": ("linked to case", "soc incident case"),
    "jira_key": ("tracked by ticket", "jira issue"),
    "linked_alerts": ("correlated with alert", "security alert"),
    "linked_notables": ("related to notable", "splunk notable"),
    "linked_events": ("supported by event", "windows security event"),
    "mitre_techniques": ("mapped to technique", "mitre attack technique"),
}


def first(row: dict, *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def load_records(path: Path = DEFAULT_DATASET) -> list[dict]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("synthetic") is not True:
        raise ValueError("Refusing to use a dataset not explicitly labeled synthetic")
    records = dataset.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a nonempty array")
    seen = set()
    for row in records:
        if not isinstance(row, dict) or row.get("kind") not in ALLOWED_KINDS:
            raise ValueError("Unsupported or missing record kind")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError(f"Missing or duplicate record id: {identifier!r}")
        seen.add(identifier)
        when = row.get("_time")
        if not isinstance(when, str):
            raise ValueError(f"Missing _time for {identifier}")
        datetime.fromisoformat(when.replace("Z", "+00:00"))
        if not row.get("tenant_id"):
            raise ValueError(f"Missing tenant_id for {identifier}")
    return records


def to_statements(row: dict) -> dict:
    """Translate Splunk/Agentic SOC-shaped records into Utopia open statements."""
    identifier = row["id"]
    when = row["_time"]
    tenant = str(row["tenant_id"])
    entities: dict[str, str] = {identifier: KIND_WORD[row["kind"]]}
    statements = []
    qualifier = {"tenant_id": tenant, "source_system": str(row.get("source_system", "lab"))}

    def entity(name: str, kind: str) -> None:
        entities.setdefault(str(name), kind)

    def linked(phrase: str, target: str | None, kind: str) -> None:
        if not target:
            return
        target = str(target)
        entity(target, kind)
        statements.append([None, identifier, phrase, target, None, dict(qualifier), when, None])

    def literal(phrase: str, value: object) -> None:
        if value is None or value == "":
            return
        statements.append([None, identifier, phrase, None, str(value), dict(qualifier), when, None])

    host = first(row, "host", "hostname", "Computer")
    ip = first(row, "src_ip", "src", "source_ip", "ClientIP", "IpAddress")
    user = first(row, "user", "username", "user_name", "AccountName", "User")
    linked("observed on host", host, "host")
    linked("observed source ip", ip, "ip address")
    linked("involves user", user, "user account")
    rule = first(row, "search_name", "rule_name")
    linked("detected by rule", rule, "detection rule")
    for field, (phrase, kind) in LINK_FIELDS.items():
        value = row.get(field)
        if isinstance(value, list):
            for item in value:
                linked(phrase, str(item), kind)
        elif isinstance(value, str):
            linked(phrase, value, kind)
    for field in SCALAR_FIELDS:
        if field in row:
            literal("has " + field.replace("_", " ").lower(), row[field])
    literal("recorded by source", row.get("source_system"))
    literal("belongs to tenant", tenant)
    if not statements:
        literal("has record kind", row["kind"])
    return {
        "external_id": identifier,
        "doc_time": when,
        "e": [[name, kind, True] for name, kind in entities.items()],
        "s": statements,
        "n": [],
    }


def validate_contract(payload: dict) -> None:
    allowed = {"external_id", "doc_time", "deleted", "e", "s", "n"}
    if set(payload) - allowed:
        raise ValueError("Unknown Utopia Statements fields")
    if not isinstance(payload.get("external_id"), str) or not payload["external_id"]:
        raise ValueError("Invalid external_id")
    if not isinstance(payload.get("e"), list) or not isinstance(payload.get("n"), list):
        raise ValueError("e and n must be arrays")
    rows = payload.get("s")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("Invalid number of statements")
    names = {x[0].strip().casefold() for x in payload["e"]}
    for item in payload["e"]:
        if len(item) != 3 or not isinstance(item[2], bool):
            raise ValueError("Invalid entity triple")
    for item in rows:
        if not isinstance(item, list) or len(item) != 8 or item[0] is not None:
            raise ValueError("Invalid statement octuple")
        if item[1].strip().casefold() not in names:
            raise ValueError("Unlisted statement subject")
        if item[3] is not None and item[3].strip().casefold() not in names:
            raise ValueError("Unlisted statement object")
        if (item[3] is None) == (item[4] is None):
            raise ValueError("Exactly one of object or value required")
        if not isinstance(item[5], dict) or any(not isinstance(v, str) for v in item[5].values()):
            raise ValueError("Invalid qualifiers")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 65536:
        raise ValueError("Payload exceeds 64KiB")


def send_one(base_url: str, source_id: str, token: str, payload: dict, timeout: int) -> str:
    url = base_url.rstrip("/") + "/api/v1/sources/" + source_id + "/statements"
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        encoded,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {payload['external_id']}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connection failed for {payload['external_id']}: {exc.reason}") from exc
    action = data.get("action")
    if action not in {"created", "updated", "unchanged", "marked_missing"}:
        raise RuntimeError(f"Unexpected response for {payload['external_id']}: {data!r}")
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "render", "push"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/soorin-soc-statements"))
    parser.add_argument("--base-url", default=os.environ.get("UTOPIA_BASE_URL", "http://127.0.0.1:1516"))
    parser.add_argument("--source-id", default=os.environ.get("UTOPIA_SOURCE_ID"))
    parser.add_argument("--replay", action="store_true", help="Send records twice to inspect unchanged actions")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args(argv)
    try:
        records = load_records(args.dataset)
        payloads = [to_statements(row) for row in records]
        for payload in payloads:
            validate_contract(payload)
        print(f"Validated {len(payloads)} synthetic records, {sum(len(p['s']) for p in payloads)} open statements")
        if args.command == "validate":
            print("Kinds:", dict(Counter(row["kind"] for row in records)))
            return 0
        if args.command == "render":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for payload in payloads:
                target = args.output_dir / (payload["external_id"] + ".json")
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("Generated statement documents:", args.output_dir)
            return 0
        if not args.source_id or not os.environ.get("UTOPIA_INGEST_TOKEN"):
            parser.error("push requires UTOPIA_SOURCE_ID and UTOPIA_INGEST_TOKEN")
        token = os.environ["UTOPIA_INGEST_TOKEN"]
        for pass_no in range(2 if args.replay else 1):
            counts = Counter()
            for payload in payloads:
                action = send_one(args.base_url, args.source_id, token, payload, args.timeout)
                counts[action] += 1
                print(f"pass={pass_no + 1} {payload['external_id']} -> {action}")
            print(f"pass={pass_no + 1} summary={dict(counts)}")
        print("Ingestion verified. Check document graph_status and actual Graph UI separately.")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
