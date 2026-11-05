"""Admission limits for native Rust ingestion; legacy contracts remain readable."""
from __future__ import annotations
import json
from pathlib import Path
from .knowledge_event_v1 import SecurityKnowledgeEvent, SOURCE_CONTENT_CHECKSUM_VERSION, ContractError
from .storage_policy import minimize


def validate_native_event(event: SecurityKnowledgeEvent, *, allow_sensitive: bool = False) -> None:
    data = event.to_dict()
    def require(ok, code):
        if not ok:
            raise ContractError(code, 'event does not meet the native ingestion profile')
    require(event.content_checksum_version == SOURCE_CONTENT_CHECKSUM_VERSION, 'native_checksum_v3_required')
    ontology = json.loads((Path(__file__).parents[1] / 'ontology/soc_ontology_v1.yaml').read_text())
    kinds = {row['label'].replace(' ', '') for row in ontology['entity_types']}
    require(1 <= len(event.entities) <= 128, 'native_entity_count')
    for collection, bound in [('relations', 512), ('facts', 512), ('evidence', 256), ('source_references', 256)]:
        require(len(data.get(collection, [])) <= bound, 'native_collection_bound')
    for entity in event.entities:
        require(entity.entity_id.startswith('soorin:') and entity.entity_type in kinds, 'native_entity_type')
        require(type(entity.provisional) is bool, 'native_provisional_boolean')
        require(not entity.provisional or not entity.source_identifiers, 'native_provisional_authority')
        require(len(entity.source_identifiers) <= 16 and all(isinstance(k, str) and 0 < len(k.encode()) <= 128 and isinstance(v, str) and 0 < len(v.strip()) <= 512 for k,v in entity.source_identifiers.items()), 'native_authority_bound')
        require(len(entity.aliases) <= 128 and all(a.strip() and len(a) <= 512 for a in entity.aliases), 'native_alias_bound')
        require(entity.scope is None or bool(entity.scope.strip()) and len(entity.scope.encode()) <= 512, 'native_scope_bound')
    for row in (*event.relations, *event.facts):
        require(row.confidence_category in {'observed', 'asserted'}, 'native_review_required')
        require(len(row.evidence_ids) <= 256, 'native_evidence_bound')
    kinds_by_id = {entity.entity_id: next(row['key'] for row in ontology['entity_types'] if row['label'].replace(' ', '') == entity.entity_type) for entity in event.entities}
    normalize = lambda value: ''.join(c.lower() for c in value if c.isascii() and c.isalnum())
    relations = {normalize(row['key']): row for row in ontology['relation_types']}
    for row in event.relations:
        spec = relations.get(normalize(row.relation_type))
        require(spec is not None, 'soc_relation_type_unknown')
        require(kinds_by_id[row.subject_entity_id] in spec['domains'], 'soc_relation_domain_invalid')
        require(kinds_by_id[row.object_entity_id] in spec['ranges'], 'soc_relation_range_invalid')
        require(not spec.get('required_provenance') or bool(row.evidence_ids), 'soc_relation_evidence_required')
    for fact in event.facts:
        require(fact.invalidated_at is None, 'native_retraction_requires_review')
    if not allow_sensitive:
        require(not event.vendor_fields and all(not e.excerpt for e in event.evidence), 'soc_sensitive_payload_policy')
        for key in ('attributes', 'entities', 'relations', 'facts'):
            require(minimize(data[key]) == data[key], 'soc_sensitive_payload_policy')
