"""Controlled semantic text builders for SOC records."""

from __future__ import annotations

import json
from typing import Any, Mapping

ALLOWED_TOP_LEVEL = (
    "alert_id", "rule_name", "severity", "risk_score", "risk_object", "risk_object_type",
    "entity", "entity_type", "detection_type", "security_domain", "investigation_type",
)
ALLOWED_RULE = ("title", "description", "risk_message", "next_steps")


def alert_semantic_text(payload: Mapping[str, Any], *, max_chars: int = 12000) -> str:
    """Build compact embedding text without raw OCSF envelopes or SPL bodies."""

    lines: list[str] = []
    for key in ALLOWED_TOP_LEVEL:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{key.replace('_', ' ')}: {_compact(value)}")
    annotations = payload.get("annotations")
    if isinstance(annotations, Mapping):
        for key in ("mitre_attack", "analytic_story", "kill_chain_phases", "cve"):
            if annotations.get(key) not in (None, "", [], {}):
                lines.append(f"{key.replace('_', ' ')}: {_compact(annotations[key])}")
    rule = payload.get("rule")
    if isinstance(rule, Mapping):
        for key in ALLOWED_RULE:
            if rule.get(key) not in (None, ""):
                lines.append(f"rule {key}: {_compact(rule[key])}")
    alert_fields = payload.get("alert_fields")
    if isinstance(alert_fields, Mapping):
        safe = {key: value for key, value in alert_fields.items() if not _sensitive_key(str(key))}
        if safe:
            lines.append("selected alert fields: " + _compact(safe))
    return "\n".join(lines)[:max_chars]


def _compact(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return any(token in lowered for token in ("password", "secret", "token", "api_key", "credential", "authorization"))
