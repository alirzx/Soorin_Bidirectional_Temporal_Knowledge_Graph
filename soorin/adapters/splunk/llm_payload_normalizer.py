"""Normalize Agentic SOC Splunk ``llm_payload`` into the v1 knowledge event.

Durable SOC alert, Splunk notable, source event/finding, rule, run, case, and
report identifiers remain separate. Display names are aliases, not IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from soorin.contracts import CanonicalEntity, EvidenceReference, KnowledgeRelation, SecurityKnowledgeEvent
from soorin.extraction import extract_entities
from soorin.identity import IdentityInput, resolve_identity


class NormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class SourceRecordClassification:
    primary_type: str
    primary_id: str
    event_type: str
    soc_alert_id: str | None = None
    notable_id: str | None = None
    source_event_ids: tuple[str, ...] = ()
    finding_uid: str | None = None
    rule_id: str | None = None
    investigation_run_id: str | None = None
    case_id: str | None = None
    report_id: str | None = None


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
        if value not in (None, "") and not isinstance(value, (Mapping, list, tuple, set)):
            return str(value).strip()
    return None


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _strings(item)
    elif value not in (None, "") and not isinstance(value, Mapping):
        yield str(value).strip()


def _unwrap_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    outer = dict(record)
    current = dict(outer)
    alert = outer.get("alert")
    if isinstance(alert, Mapping):
        current = {**alert, **current}
        durable_id = _first(outer, "alert_row_id", "soc_alert_id", "id") or _first(alert, "alert_row_id", "soc_alert_id", "id")
        if durable_id:
            current["alert_row_id"] = durable_id
    for key in ("raw_alert", "raw_event", "ocsf_event", "raw_data", "data"):
        nested = current.get(key)
        if isinstance(nested, Mapping):
            current = {**nested, **current}
    return current


def _nested_first(mapping: Mapping[str, Any], container: str, *keys: str) -> str | None:
    nested = mapping.get(container)
    return _first(nested, *keys) if isinstance(nested, Mapping) else None


def classify_source_record(raw: Mapping[str, Any], payload: Mapping[str, Any]) -> SourceRecordClassification:
    soc_alert_id = _first(raw, "alert_row_id", "soc_alert_id")
    notable_id = _first(raw, "notable_id", "source_guid") or _first(payload, "alert_id")
    finding_uid = _nested_first(raw, "finding", "uid", "id")
    source_events: list[str] = []
    for key in ("source_event_ids", "source_event_id", "event_id"):
        source_events.extend(_strings(raw.get(key)))
    if finding_uid:
        source_events.append(finding_uid)
    source_event_ids = tuple(dict.fromkeys(value for value in source_events if value))
    rule_id = (_first(raw, "rule_id", "detection_id") or _nested_first(raw, "rule", "uid", "id")
               or _nested_first(raw, "finding", "rule_uid", "rule_id"))
    investigation_run_id = _first(raw, "investigation_run_id", "run_id")
    case_id = _first(raw, "case_id", "soc_case_id")
    report_id = _first(raw, "report_id")
    candidates = (
        ("SecurityAlert", soc_alert_id, "security_alert"),
        ("SplunkNotable", notable_id, "splunk_notable"),
        ("SecurityEvent", source_event_ids[0] if source_event_ids else None, "security_event"),
        ("InvestigationRun", investigation_run_id, "investigation_run"),
        ("SOCCase", case_id, "soc_case"),
        ("Report", report_id, "report"),
        ("DetectionRule", rule_id, "detection_rule"),
    )
    for entity_type, identifier, event_type in candidates:
        if identifier:
            return SourceRecordClassification(
                entity_type, identifier, event_type, soc_alert_id, notable_id, source_event_ids,
                finding_uid, rule_id, investigation_run_id, case_id, report_id,
            )
    raise NormalizationError("missing_source_identity", "no durable alert, notable, event, run, case, report, or rule identifier")


def _source_content(value: Any) -> Any:
    delivery_fields = {"delivery_id", "processed_at", "processing_time", "received_at", "ingested_at", "ingestion_time"}
    if isinstance(value, Mapping):
        return {str(key): _source_content(item) for key, item in value.items() if str(key).casefold() not in delivery_fields}
    if isinstance(value, (list, tuple)):
        return [_source_content(item) for item in value]
    return value


def normalize_llm_payload(
    value: Mapping[str, Any] | str | None, *, tenant_id: str, source_instance: str,
    raw_record: Mapping[str, Any] | None = None, observed_at: str | None = None,
    recorded_at: str | None = None, delivery_id: str | None = None,
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

    classification = classify_source_record(raw, payload)
    source_record_id = classification.primary_id
    merged = {**raw, **payload}
    event_time = _first(payload, "event_time") or _first(raw, "event_time")
    alert_time = _first(payload, "alert_time") or _first(raw, "alert_time", "_time", "created_at") or event_time
    if not event_time:
        if not alert_time:
            raise NormalizationError("missing_timestamp", "event_time and alert_time are both absent")
        event_time = alert_time
        warnings.append("event_time_fell_back_to_alert_time")
    # Stable occurrence time is not a source revision clock. Prefer an explicit
    # source update timestamp; delivery/processing time never establishes order.
    source_observed_at = (_first(raw, "source_updated_at", "updated_at", "last_modified")
                          or _first(payload, "source_updated_at", "updated_at", "last_modified")
                          or alert_time or event_time)
    processing_time = recorded_at or observed_at or _now()
    source_revision_id = _first(raw, "source_revision_id", "revision_id", "revision", "_version")

    extracted = extract_entities(merged, source_record_reference=source_record_id, timestamp_context=event_time)
    warnings.extend(f"extraction:{error}" for error in extracted.errors)
    entity_rows: list[CanonicalEntity] = []
    entity_by_pair: dict[tuple[str, str, str | None], CanonicalEntity] = {}

    def add_entity(entity_type: str, identifier: str, authority_name: str) -> CanonicalEntity:
        decision = resolve_identity(IdentityInput(tenant_id, "splunk", source_instance, entity_type, identifier, identifier))
        pair = entity_type, decision.normalized_value, None
        if pair in entity_by_pair:
            return entity_by_pair[pair]
        entity = CanonicalEntity(
            decision.canonical_key, entity_type, decision.normalized_value,
            source_identifiers={authority_name: identifier}, attributes={"identity_status": decision.status},
        )
        entity_rows.append(entity)
        entity_by_pair[pair] = entity
        return entity

    explicit: dict[str, CanonicalEntity] = {}
    explicit_values = (
        ("SecurityAlert", classification.soc_alert_id, "soc_alert_row_id"),
        ("SplunkNotable", classification.notable_id, "splunk_notable_id"),
        ("InvestigationRun", classification.investigation_run_id, "investigation_run_id"),
        ("SOCCase", classification.case_id, "soc_case_id"),
        ("Report", classification.report_id, "report_id"),
        ("DetectionRule", classification.rule_id, "splunk_rule_id"),
    )
    for entity_type, identifier, authority_name in explicit_values:
        if identifier:
            explicit[entity_type] = add_entity(entity_type, identifier, authority_name)
    event_entities = [add_entity("SecurityEvent", identifier, "source_event_id") for identifier in classification.source_event_ids]
    if classification.primary_type not in explicit and classification.primary_type != "SecurityEvent":
        explicit[classification.primary_type] = add_entity(classification.primary_type, classification.primary_id, "source_record_id")
    anchor = explicit.get(classification.primary_type) or event_entities[0]

    authoritative_fields = {
        "notable_id", "source_guid", "source_event_id", "event_id", "detection_id", "rule_id", "case_id",
        "soc_case_id", "investigation_run_id", "run_id", "report_id", "ticket_id", "jira_key",
    }
    for result in extracted.entities:
        scopes = raw.get("network_scopes", {})
        scope = None
        if result.entity_type == "IPAddress":
            if isinstance(scopes, Mapping):
                scope = scopes.get(result.source_field) or scopes.get(result.source_field.rsplit(".", 1)[-1])
            scope = scope or _first(raw, "network_scope", "network_id", "vpc_id", "subnet_id")
            if scope is not None and not isinstance(scope, str):
                raise NormalizationError("invalid_network_scope", "network scope must be a string")
        pair = result.entity_type, result.normalized_value, scope
        if pair in entity_by_pair:
            continue
        leaf = result.source_field.rsplit(".", 1)[-1].casefold()
        # In Agentic's Splunk llm_payload, alert_id is the notable identifier;
        # the durable SOC alert row is carried separately by the envelope.
        if leaf == "alert_id":
            continue
        authoritative = result.original_value if leaf in authoritative_fields else None
        decision = resolve_identity(IdentityInput(
            tenant_id, "splunk", source_instance, result.entity_type, result.normalized_value, authoritative, scope,
        ))
        entity = CanonicalEntity(
            decision.canonical_key, result.entity_type, decision.normalized_value,
            source_identifiers={leaf: result.original_value} if authoritative else {},
            aliases=(result.original_value,) if not authoritative and result.original_value != decision.normalized_value else (),
            scope=scope, provisional=not decision.automatic,
            attributes={"source_field": result.source_field, "identity_status": decision.status},
        )
        entity_rows.append(entity)
        entity_by_pair[pair] = entity

    evidence_id = f"splunk:{source_record_id}"
    relations: list[KnowledgeRelation] = []

    def relate(subject: CanonicalEntity, relation_type: str, obj: CanonicalEntity) -> None:
        if subject.entity_id == obj.entity_id:
            return
        seed = f"{subject.entity_id}|{relation_type}|{obj.entity_id}"
        relations.append(KnowledgeRelation(
            "rel:" + hashlib.sha256(seed.encode()).hexdigest(), relation_type, subject.entity_id, obj.entity_id,
            confidence_category="asserted" if relation_type in {"CORRELATED_WITH", "MAPPED_TO_TECHNIQUE", "PART_OF_CASE"} else "observed",
            valid_from=event_time, evidence_ids=(evidence_id,),
        ))

    notable = explicit.get("SplunkNotable")
    if anchor.entity_type == "SecurityAlert" and notable:
        relate(anchor, "CORRELATED_WITH", notable)
    case = explicit.get("SOCCase")
    if case and anchor.entity_type in {"SecurityAlert", "SplunkNotable", "InvestigationRun", "Report"}:
        relate(anchor, "PART_OF_CASE", case)
    evidence_anchor = anchor if anchor.entity_type in {"SecurityAlert", "SplunkNotable"} else (notable or anchor)
    for source_event in event_entities:
        relate(evidence_anchor, "SUPPORTED_BY", source_event)
    if explicit.get("DetectionRule") and evidence_anchor.entity_type in {"SecurityAlert", "SplunkNotable"}:
        relate(evidence_anchor, "DETECTED_BY", explicit["DetectionRule"])
    relation_map = {
        "Host": "OBSERVED_ON", "IPAddress": "ORIGINATED_FROM", "UserAccount": "INVOLVES_USER",
        "MITRETechnique": "MAPPED_TO_TECHNIQUE", "SOCCase": "PART_OF_CASE",
    }
    already_linked = {entity.entity_id for entity in explicit.values()} | {entity.entity_id for entity in event_entities}
    for entity in entity_rows:
        if entity.entity_id not in already_linked and entity.entity_type in relation_map:
            relate(evidence_anchor, relation_map[entity.entity_type], entity)

    for ticket in [entity for entity in entity_rows if entity.entity_type == "Ticket"]:
        ticket_subject = case or explicit.get("SecurityAlert")
        if ticket_subject:
            relate(ticket_subject, "TRACKED_BY_TICKET", ticket)
        else:
            # A notable is not an alert/case. Retain the ticket identity and
            # report the unmappable association; never invent a broader axiom.
            warnings.append("ticket_link_requires_alert_or_case")

    identifiers = {
        "soc_alert_id": classification.soc_alert_id, "notable_id": classification.notable_id,
        "source_event_id": classification.source_event_ids[0] if classification.source_event_ids else None,
        "source_event_ids": list(classification.source_event_ids), "finding_uid": classification.finding_uid,
        "rule_id": classification.rule_id, "investigation_run_id": classification.investigation_run_id,
        "case_id": classification.case_id, "report_id": classification.report_id,
    }
    verified = {
        "tenant_id": tenant_id, "source_system": "splunk", "source_instance": source_instance,
        "source_record_id": source_record_id, "source_record_type": classification.primary_type,
        "identifiers": {key: value for key, value in identifiers.items() if value not in (None, [], ())},
        "event_time": event_time, "alert_time": alert_time,
        "event_time_source": payload.get("event_time_source") or raw.get("event_time_source") or "unknown",
    }
    reported_keys = (
        "severity", "finding_count", "risk_score", "risk_object", "risk_object_type", "entity", "entity_type",
        "detection_type", "security_domain", "investigation_type", "date_context", "time_window",
    )
    reported = {key: payload[key] for key in reported_keys if key in payload}
    analyst = _mapping(raw.get("analyst_labels"), "analyst_labels", allow_missing=True)
    retrieval_hints = {"investigation_hint": payload.get("investigation_hint")} if payload.get("investigation_hint") else {}
    from soorin.contracts.storage_policy import minimize
    attributes = minimize({
        "verified_source_metadata": verified, "reported_observations": reported, "analyst_assertions": analyst,
        "retrieval_hints": retrieval_hints,
        "semantic_caveats": {
            "risk_score": "vendor accumulated risk; not a probability",
            "rule_configuration": "current configuration may differ from fire-time configuration",
            "investigation_hint": "retrieval guidance; not evidence",
        },
    })
    if "ticket_link_requires_alert_or_case" in warnings:
        attributes["normalization_warnings"] = ["ticket_link_requires_alert_or_case"]
    evidence_content = _source_content({"raw_record": raw, "llm_payload": payload})
    evidence = EvidenceReference(
        evidence_id=evidence_id, source_record_id=source_record_id,
        field_path="llm_payload" if payload else "raw_record", source_uri=_first(raw, "source_uri", "record_uri"),
        observed_at=source_observed_at, source_system="splunk", source_instance=source_instance,
        source_event_ids=classification.source_event_ids, source_revision_id=source_revision_id,
        checksum=hashlib.sha256(json.dumps(evidence_content, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
    )
    source_references = tuple(dict.fromkeys(identifier for identifier in (
        classification.soc_alert_id, classification.notable_id, *classification.source_event_ids,
        classification.rule_id, classification.investigation_run_id, classification.case_id, classification.report_id,
    ) if identifier))
    event = SecurityKnowledgeEvent(
        tenant_id=tenant_id, source_system="splunk", source_instance=source_instance,
        source_record_id=source_record_id,
        event_id=f"splunk:{tenant_id}:{source_instance}:{classification.primary_type}:{source_record_id}",
        event_type=classification.event_type, event_time=event_time, observed_at=source_observed_at,
        recorded_at=processing_time, processed_at=processing_time, source_revision_id=source_revision_id,
        delivery_id=delivery_id, entities=tuple(entity_rows), relations=tuple(relations), evidence=(evidence,),
        attributes=attributes,
        vendor_fields={},  # Source bytes remain at their authority; checksum preserves provenance.
        source_references=source_references,
        curated_payload_version="agentic-soc.splunk.llm-payload.v1" if payload else None,
    )
    return NormalizedSplunkEvent(
        event, verified, reported, (), analyst, (), retrieval_hints, tuple(dict.fromkeys(warnings)),
    )
