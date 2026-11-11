"""SOC extraction types and field families."""

from __future__ import annotations

FIELD_TYPES: dict[str, str] = {
    "host": "Host", "hostname": "Host", "computer": "Host", "device": "Host", "asset": "Host",
    "dvc": "Host", "dest": "Host", "entity": "Host",
    "src_ip": "IPAddress", "source_ip": "IPAddress", "clientip": "IPAddress", "ipaddress": "IPAddress",
    "dst_ip": "IPAddress", "dest_ip": "IPAddress", "destination_ip": "IPAddress", "remote_ip": "IPAddress",
    "user": "UserAccount", "username": "UserAccount", "user_name": "UserAccount", "accountname": "UserAccount",
    "principal": "UserAccount", "risk_object": "UserAccount",
    "alert_id": "SecurityAlert", "notable_id": "SplunkNotable", "source_guid": "SplunkNotable",
    "source_event_id": "SecurityEvent", "event_id": "SecurityEvent", "case_id": "SOCCase",
    "detection_id": "DetectionRule", "rule_id": "DetectionRule", "rule_name": "DetectionRule", "search_name": "DetectionRule",
    "ticket": "Ticket", "ticket_id": "Ticket", "jira_key": "Ticket", "change_ticket": "Ticket",
    "mitre_attack": "MITRETechnique", "mitre_techniques": "MITRETechnique", "technique_id": "MITRETechnique",
    "file_hash": "Indicator", "hash": "Indicator", "sha256": "Indicator", "sha1": "Indicator", "md5": "Indicator",
    "domain": "Indicator", "fqdn": "Indicator", "url": "Indicator",
    "process": "Indicator", "process_name": "Indicator", "image": "Indicator", "process_path": "Indicator",
    "file_path": "Indicator", "path": "Indicator",
}

UNSTRUCTURED_FIELDS = {
    "title", "description", "summary", "analyst_note", "analyst_notes", "report_text", "message",
}

SKIP_REGEX_FIELDS = {
    "spl", "rule_spl", "macro_definitions", "macro_definition", "investigation_hint",
    "description_template", "title_template",
}
