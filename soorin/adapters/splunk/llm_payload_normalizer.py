"""Normalize Agentic SOC Splunk ``llm_payload`` into the v1 knowledge event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Mapping

from soorin.contracts import CanonicalEntity, EvidenceReference, KnowledgeRelation, SecurityKnowledgeEvent
from soorin.extraction import extract_entities
from soorin.identity import IdentityInput, resolve_identity

SOURCE_ID_FIELDS = ("notable_id", "source_guid", "source_event_id", "detection_id", "event_id")


class NormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class NormalizedSplunkEvent:
    event: SecurityKnowledgeEvent
    verified_source_metadata: Mapping[str, Any]
    reported_observations: Mapping[str, Any]
    inferred_relationships: tuple[Mapping[str, Any], ...]
    analyst_assertions: Mapping[str, Any]
    model_generated_conclusions: tuple[Mapping[str, Any], ...]
    retrieval_hints: Mapping[str, Any]
    warnings: tuple[str, ...] = ()


def _mapping(value: Any, name: str, *, allow_missing: bool = False) -> dict[str, Any]:
    if value in (None, "") and allow_missing:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            if allow_missing:
                return {}
            raise NormalizationError("malformed_llm_payload", str(exc)) from exc
        if isinstance(decoded, Mapping):
            return dict(decoded)
    raise NormalizationError("invalid_llm_payload_type", f"{name} must be a JSON object or encoded object")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _first(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _unwrap_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    current = dict(record)
    # Agentic SOC envelopes may nest connector data in raw_event, OCSF raw_data,
    # or an inner canonical envelope. Keep outer fields while unwrapping.
    for key in ("raw_event", "ocsf_event", "raw_data", "data"):
        nested = current.get(key)
        if isinstance(nested, Mapping):
            current = {**nested, **current}
    return current


def normalize_llm_payload(
    value: Mapping[str, Any] | str | None,
    *, tenant_id: str, source_instance: str,
    raw_record: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> NormalizedSplunkEvent:
    raw = _unwrap_record(raw_record)
    warnings: list[str] = []
    try:
        payload = _mapping(value, "llm_payload", allow_missing=False)
    except NormalizationError as exc:
        if not raw:
            raise
        payload = {}
        warnings.append(exc.code)
    if not payload:
        warnings.append("missing_llm_payload_compact_fallback")
    merged = {**raw, **payload}
    source_record_id = _first(raw, *SOURCE_ID_FIELDS) or _first(payload, "alert_id")
    if not source_record_id:
        raise NormalizationError("missing_source_identity", "no notable, event, detection, or alert identifier")
    event_time = _first(payload, "event_time") or _first(raw, "event_time")
    alert_time = _first(payload, "alert_time") or _first(raw, "_time", "created_at") or event_time
    if not event_time:
        if not alert_time:
            raise NormalizationError("missing_timestamp", "event_time and alert_time are both absent")
        event_time = alert_time
        warnings.append("event_time_fell_back_to_alert_time")
    observed_at = observed_at or _now()

    extracted = extract_entities(merged, source_record_reference=source_record_id, timestamp_context=event_time)
    warnings.extend(f"extraction:{error}" for error in extracted.errors)
    entity_rows: list[CanonicalEntity] = []
    entity_by_pair: dict[tuple[str, str], CanonicalEntity] = {}

    alert_decision = resolve_identity(IdentityInput(
        tenant_id=tenant_id, source_system="splunk", source_instance=source_instance,
        entity_type="SplunkNotable", observed_value=source_record_id,
        authoritative_id=source_record_id,
    ))
    alert_entity = CanonicalEntity(
        entity_id=alert_decision.canonical_key, entity_type="SplunkNotable",
        normalized_value=alert_decision.normalized_value,
        source_identifiers={"splunk_notable_id": source_record_id},
        attributes={"identity_status": alert_decision.status},
    )
    entity_rows.append(alert_entity)
    entity_by_pair[("SplunkNotable", alert_entity.normalized_value)] = alert_entity
    for result in extracted.entities:
        pair = result.entity_type, result.normalized_value
        if pair in entity_by_pair:
            continue
        authoritative = result.original_value if result.entity_type in {"SecurityAlert", "SplunkNotable", "SecurityEvent", "DetectionRule", "SOCCase", "Ticket"} else None
        decision = resolve_identity(IdentityInput(
            tenant_id=tenant_id, source_system="splunk", source_instance=source_instance,
            entity_type=result.entity_type, observed_value=result.normalized_value,
            authoritative_id=authoritative,
            scope=_first(raw, "network_scope", "index") if result.entity_type == "IPAddress" else None,
        ))
        entity = CanonicalEntity(
            entity_id=decision.canonical_key, entity_type=result.entity_type,
            normalized_value=decision.normalized_value,
            source_identifiers={"source_value": result.original_value} if authoritative else {},
            provisional=not decision.automatic,
            attributes={"source_field": result.source_field, "identity_status": decision.status},
        )
        entity_rows.append(entity)
        entity_by_pair[pair] = entity

    relation_map = {
        "Host": "OBSERVED_ON", "IPAddress": "ORIGINATED_FROM", "UserAccount": "INVOLVES_USER",
        "DetectionRule": "DETECTED_BY", "MITRETechnique": "MAPPED_TO_TECHNIQUE",
        "SOCCase": "PART_OF_CASE", "Ticket": "TRACKED_BY_TICKET", "SecurityEvent": "SUPPORTED_BY",
    }
    relations: list[KnowledgeRelation] = []
    for entity in entity_rows[1:]:
        relation_type = relation_map.get(entity.entity_type)
        if not relation_type:
            continue
        relation_seed = f"{alert_entity.entity_id}|{relation_type}|{entity.entity_id}"
        relations.append(KnowledgeRelation(
            relation_id="rel:" + hashlib.sha256(relation_seed.encode()).hexdigest(),
            relation_type=relation_type,
            subject_entity_id=alert_entity.entity_id,
            object_entity_id=entity.entity_id,
            confidence_category="observed" if entity.attributes.get("source_field") else "asserted",
            valid_from=event_time,
            evidence_ids=(f"splunk:{source_record_id}",),
        ))

    source_ids = {key: raw.get(key) for key in SOURCE_ID_FIELDS + ("orig_sid", "orig_rid", "rule_id") if raw.get(key) not in (None, "")}
    verified = {
        "tenant_id": tenant_id,
        "source_system": "splunk",
        "source_instance": source_instance,
        "source_record_id": source_record_id,
        "identifiers": source_ids,
        "event_time": event_time,
        "alert_time": alert_time,
        "event_time_source": payload.get("event_time_source") or raw.get("event_time_source") or "unknown",
    }
    reported_keys = (
        "severity", "finding_count", "risk_score", "risk_object", "risk_object_type", "entity", "entity_type",
        "detection_type", "security_domain", "investigation_type", "date_context", "time_window", "annotations", "alert_fields",
    )
    reported = {key: payload[key] for key in reported_keys if key in payload}
    analyst = _mapping(raw.get("analyst_labels"), "analyst_labels", allow_missing=True)
    retrieval_hints = {"investigation_hint": payload.get("investigation_hint")} if payload.get("investigation_hint") else {}
    attributes = {
        "verified_source_metadata": verified,
        "reported_observations": reported,
        "analyst_assertions": analyst,
        "rule_configuration": payload.get("rule") or {},
        "retrieval_hints": retrieval_hints,
        "semantic_caveats": {
            "risk_score": "vendor accumulated risk; not a probability",
            "rule_configuration": "current configuration may differ from fire-time configuration",
            "investigation_hint": "retrieval guidance; not evidence",
        },
    }
    evidence = EvidenceReference(
        evidence_id=f"splunk:{source_record_id}", source_record_id=source_record_id,
        field_path="llm_payload" if payload else "raw_record", observed_at=observed_at,
        checksum=hashlib.sha256(json.dumps(merged, sort_keys=True, default=str).encode()).hexdigest(),
    )
    event = SecurityKnowledgeEvent(
        tenant_id=tenant_id, source_system="splunk", source_instance=source_instance,
        source_record_id=source_record_id,
        event_id=f"splunk:{tenant_id}:{source_instance}:{source_record_id}",
        event_type="splunk_notable", event_time=event_time, observed_at=observed_at, recorded_at=observed_at,
        entities=tuple(entity_rows), relations=tuple(relations), evidence=(evidence,),
        attributes=attributes,
        vendor_fields={key: value for key, value in raw.items() if key not in {"llm_payload", "analyst_labels"}},
        source_references=tuple(str(value) for value in source_ids.values()),
        curated_payload_version="agentic-soc.splunk.llm-payload.v1" if payload else None,
    )
    return NormalizedSplunkEvent(
        event=event, verified_source_metadata=verified, reported_observations=reported,
        inferred_relationships=(), analyst_assertions=analyst, model_generated_conclusions=(),
        retrieval_hints=retrieval_hints, warnings=tuple(dict.fromkeys(warnings)),
    )
