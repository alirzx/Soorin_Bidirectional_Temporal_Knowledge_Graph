"""Deterministic synthetic Splunk / Agentic_SOC curated SOC fixture generator.

Only uses reserved documentation networks and invented domains. Never contacts
Splunk or the QA API. Source-reviewed projection, NOT copied customer data.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

PROFILE = "agentic-soc.splunk-curated.v1"
SCENARIOS = (
    ("Password Spray Detection", "authentication", "T1110.003", "high"),
    ("Unusual Privileged Login", "authentication", "T1078", "high"),
    ("Suspicious Remote Service", "lateral_movement", "T1021", "medium"),
    ("DNS Beaconing Pattern", "command_and_control", "T1071.004", "high"),
    ("PowerShell Execution Anomaly", "execution", "T1059.001", "medium"),
    ("Multiple Failed Logons", "authentication", "T1110", "medium"),
)


def iso(t):
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def make_record(i: int, revision: int = 1) -> dict:
    if i < 0 or revision < 1:
        raise ValueError("invalid sample or revision")
    title, domain, technique, severity = SCENARIOS[i % len(SCENARIOS)]
    event_time = datetime(2026, 10, 20, tzinfo=timezone.utc) + timedelta(minutes=i * 2)
    changed_at = event_time + timedelta(minutes=revision)
    hostname = f"srv-{i % 24:02d}.soc.example"
    user = f"user{i % 40:03d}@soc.example"
    src_ip = f"192.0.2.{1 + i % 200}"
    dest_ip = f"198.51.100.{1 + i % 200}"
    alert = f"soc-alert-synthetic-{i:05d}"
    notable = f"splunk-notable-synthetic-{i:05d}"
    event_ids = [f"synthetic-event-{i:05d}-a", f"synthetic-event-{i:05d}-b"]
    rule_id = f"rule-{i % 6 + 1:02d}"
    case_id = f"CASE-SYN-{i % 6:04d}"
    score = min(99, 60 + i % 30 + revision - 1)
    llm_payload = {
        "_meta": {"provider": "splunk", "mode": "enriched_from_api",
                  "caveats": ["synthetic_source_record"]},
        "alert_id": alert, "event_time": iso(event_time),
        "alert_time": iso(changed_at), "event_time_source": "first_event",
        "rule_name": title, "severity": severity, "risk_score": score,
        "risk_object": user, "risk_object_type": "user",
        "entity": hostname, "entity_type": "host",
        "security_domain": domain, "finding_count": 2,
        "annotations": {"mitre_attack": [technique]},
        "rule": {"title": title, "title_template": title,
                 "description": "Synthetic SOC acceptance evidence",
                 "spl": None, "macro_definitions": []},
        "alert_fields": {"src_ip": src_ip, "dest": hostname, "user": user,
                         "action": "detected"},
        "time_window": {"earliest": iso(event_time - timedelta(minutes=5)),
                        "latest": iso(event_time), "search_time": iso(changed_at),
                        "source": "notable_info"},
    }
    nested = {"raw_event": {
        "index": "notable", "sourcetype": "stash", "src_ip": src_ip,
        "dest_ip": dest_ip, "hostname": hostname, "username": user,
        "source_event_ids": event_ids,
        "finding": {"uid": f"synthetic-finding-{i:05d}", "rule_uid": rule_id},
        "action": "detected",
    }}
    return {
        "alert_row_id": alert, "source_guid": notable, "notable_id": notable,
        "source_event_ids": event_ids, "source_revision_id": f"rev-{revision}-{i:05d}",
        "source_updated_at": iso(changed_at),
        "event_time": iso(event_time), "_time": iso(changed_at),
        "firstTime": iso(event_time),
        "hostname": hostname, "src_ip": src_ip, "dest_ip": dest_ip,
        "user": user, "risk_object": user, "risk_object_type": "user",
        "severity": severity, "urgency": severity, "risk_score": score,
        "rule_id": rule_id, "search_name": title, "orig_rule_title": title,
        "security_domain": domain, "case_id": case_id,
        "investigation_run_id": f"run-synthetic-{i:05d}",
        "entity": hostname, "entity_type": "host",
        "network_scope": "synthetic-corp-net",
        "affected_hosts": [hostname], "affected_ips": [src_ip, dest_ip],
        "affected_users": [user],
        "entities": [{"type": "host", "value": hostname},
                     {"type": "user", "value": user}],
        "iocs": [{"type": "ip", "value": src_ip},
                 {"type": "domain", "value": f"ioc-{i}.soc.example"}],
        "llm_payload": llm_payload,
        "raw_data": json.dumps(nested, sort_keys=True, separators=(",", ":")),
    }


def to_line(i, revision=1):
    return json.dumps({"profile": PROFILE, "record": make_record(i, revision)},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generate(destination: Path, count: int, revision_count: int):
    if not 1 <= count <= 10000 or not 0 <= revision_count <= count:
        raise ValueError("requires 1..10000 alerts and revisions within alert count")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("output directory is not empty; refusing to replace QA fixtures")
    destination.mkdir(parents=True, exist_ok=True)
    rows = {
        "alerts.jsonl": [to_line(i) for i in range(count)],
        "revisions.jsonl": [to_line(i, 2) for i in range(revision_count)],
    }
    digests = {}
    for name, lines in rows.items():
        blob = ("\n".join(lines) + "\n").encode()
        (destination / name).write_bytes(blob)
        digests[name] = hashlib.sha256(blob).hexdigest()
    manifest = {
        "schema_version": "soorin.synthetic-splunk-curated-dataset.v1",
        "synthetic": True,
        "profile": PROFILE,
        "source_system": "splunk", "source_instance": "splunk-e2e",
        "tenant_id": "tenant-blue", "alerts": count,
        "separate_revisions": revision_count,
        "scenarios": [s[0] for s in SCENARIOS],
        "files_sha256": digests,
        "notes": "No real SIEM records. Source clocks, identities and revised events are deterministic.",
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--count", type=int, default=240)
    p.add_argument("--revisions", type=int, default=12)
    args = p.parse_args(argv)
    result = generate(args.out, args.count, args.revisions)
    print(json.dumps({"status": "GENERATED", "directory": str(args.out),
                      "alerts": result["alerts"],
                      "revisions": result["separate_revisions"]}))


if __name__ == "__main__":
    main()
