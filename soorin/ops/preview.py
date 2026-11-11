"""Side-effect-free structured Splunk/curated SOC preview, not arbitrary JSON interpretation."""
from dataclasses import asdict
from soorin.adapters.splunk import normalize_llm_payload
from soorin.contracts.json_input import load_object
from soorin.contracts.native_profile import validate_native_event
from soorin.extraction.enrichment import enrich_entities


def preview(raw: str | bytes, *, tenant_id: str, source_instance: str, ner=None):
    record = load_object(raw)
    # Scope is an operator assertion, never inferred from arbitrary input fields.
    for key, expected in [('tenant_id', tenant_id), ('source_instance', source_instance)]:
        if key in record and record[key] != expected:
            raise ValueError('source_scope_mismatch')
    payload = record.get('llm_payload')
    if isinstance(payload, str):
        payload = load_object(payload)
    if payload is not None and not isinstance(payload, dict):
        raise ValueError('invalid_llm_payload_type')
    normalized = normalize_llm_payload(payload, tenant_id=tenant_id,
        source_instance=source_instance, raw_record=record)
    validate_native_event(normalized.event)
    proposals, errors = [], []
    if ner is not None:
        batch = enrich_entities(record, source_record_reference=normalized.event.source_record_id,
            timestamp_context=normalized.event.event_time, ner=ner)
        known = {(e.entity_type, e.normalized_value.casefold()) for e in normalized.event.entities}
        proposals = [asdict(p) for p in batch.ner_proposals if (p.entity_type, p.value.casefold()) not in known]
        errors = list(batch.errors)
    return normalized.event, {
        'schema_version': 'soorin.ingestion-preview.v1',
        'canonical_event': normalized.event.to_dict(),
        'warnings': list(normalized.warnings) + errors,
        'ner_status': 'disabled' if ner is None else 'review_only',
        'ner_proposals': proposals,
        'persistent_writes': False,
        'submission_status': 'NOT RUN',
    }
