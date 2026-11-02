"""Canonical ``soorin.soc.knowledge-event.v1`` domain contracts.

Only the Python standard library is used.  The classes reject unknown
top-level contract fields; vendor extensions belong in ``vendor_fields`` or
``attributes`` and are therefore retained deliberately rather than silently
dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "soorin.soc.knowledge-event.v1"
LEGACY_CHECKSUM_VERSION = "soorin.event-content.sha256.v1"
SOURCE_CONTENT_CHECKSUM_V2 = "soorin.source-content.sha256.v2"
SOURCE_CONTENT_CHECKSUM_VERSION = "soorin.source-content.sha256.v3"
MAX_EVENT_BYTES = 1024 * 1024
MAX_IDENTIFIER_LENGTH = 512
MAX_EVIDENCE_EXCERPT = 4096


class ContractError(ValueError):
    """A stable, machine-readable contract validation error."""

    def __init__(self, code: str, message: str, *, path: str = "$") -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ContractError("unexpected_type", f"{name} must be a string", path=f"$.{name}")
    value = value.strip()
    if not value:
        raise ContractError("empty_identifier", f"{name} cannot be empty", path=f"$.{name}")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise ContractError("identifier_too_long", f"{name} exceeds {MAX_IDENTIFIER_LENGTH} characters", path=f"$.{name}")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractError("unexpected_type", f"{name} must be a string", path=f"$.{name}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ContractError("unexpected_type", f"{name} must be a string", path=f"$.{name}")
    return value


def normalize_timestamp(value: str | datetime | None, name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ContractError("missing_required_field", f"{name} is required", path=f"$.{name}")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ContractError("invalid_timestamp", f"{name} must be RFC3339", path=f"$.{name}") from exc
    else:
        raise ContractError("unexpected_type", f"{name} must be an RFC3339 string", path=f"$.{name}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("timezone_required", f"{name} must include a timezone", path=f"$.{name}")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("invalid_number", "NaN and infinity are not JSON values", path=path)
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_value(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    raise ContractError("unexpected_type", f"unsupported JSON value {type(value).__name__}", path=path)


def canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize deterministically for checksums, replay, and signatures."""

    return json.dumps(_json_value(value, "$"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    source_record_id: str
    field_path: str | None = None
    source_uri: str | None = None
    checksum: str | None = None
    excerpt: str | None = None
    observed_at: str | None = None
    source_system: str | None = None
    source_instance: str | None = None
    source_event_ids: tuple[str, ...] = ()
    source_revision_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "source_record_id", _identifier(self.source_record_id, "source_record_id"))
        if self.excerpt is not None and len(self.excerpt) > MAX_EVIDENCE_EXCERPT:
            raise ContractError("evidence_excerpt_too_large", "excerpt exceeds 4096 characters", path="$.excerpt")
        for name in ("field_path", "source_uri", "checksum", "excerpt"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "observed_at", normalize_timestamp(self.observed_at, "observed_at"))
        for name in ("source_system", "source_instance", "source_revision_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _identifier(value, name))
        event_ids = tuple(_identifier(value, "source_event_id") for value in self.source_event_ids)
        object.__setattr__(self, "source_event_ids", event_ids)

    def to_dict(self) -> dict[str, Any]:
        return _without_none({
            "evidence_id": self.evidence_id,
            "source_record_id": self.source_record_id,
            "field_path": self.field_path,
            "source_uri": self.source_uri,
            "checksum": self.checksum,
            "excerpt": self.excerpt,
            "observed_at": self.observed_at,
            "source_system": self.source_system,
            "source_instance": self.source_instance,
            "source_event_ids": list(self.source_event_ids),
            "source_revision_id": self.source_revision_id,
        })


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    entity_id: str
    entity_type: str
    normalized_value: str
    source_identifiers: Mapping[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    scope: str | None = None
    provisional: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id"))
        object.__setattr__(self, "entity_type", _identifier(self.entity_type, "entity_type"))
        object.__setattr__(self, "normalized_value", _identifier(self.normalized_value, "normalized_value"))
        for key, value in self.source_identifiers.items():
            _identifier(str(key), "source_identifier_key")
            _identifier(value, "source_identifier")
        aliases = tuple(_text(value, "alias") for value in self.aliases)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "scope", _optional_text(self.scope, "scope"))
        _json_value(self.attributes, "$.attributes")

    def to_dict(self) -> dict[str, Any]:
        return _without_none({
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "normalized_value": self.normalized_value,
            "source_identifiers": dict(sorted(self.source_identifiers.items())),
            "aliases": list(self.aliases),
            "scope": self.scope,
            "provisional": self.provisional,
            "attributes": dict(self.attributes),
        })


@dataclass(frozen=True, slots=True)
class KnowledgeRelation:
    relation_id: str
    relation_type: str
    subject_entity_id: str
    object_entity_id: str
    confidence_category: str = "observed"
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("relation_id", "relation_type", "subject_entity_id", "object_entity_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.confidence_category not in {"observed", "asserted", "inferred", "model_proposed"}:
            raise ContractError("invalid_confidence_category", self.confidence_category, path="$.confidence_category")
        object.__setattr__(self, "evidence_ids", tuple(_identifier(value, "evidence_id") for value in self.evidence_ids))
        object.__setattr__(self, "valid_from", normalize_timestamp(self.valid_from, "valid_from"))
        object.__setattr__(self, "valid_to", normalize_timestamp(self.valid_to, "valid_to"))
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ContractError("invalid_time_range", "valid_to precedes valid_from", path="$.valid_to")
        _json_value(self.attributes, "$.attributes")

    def to_dict(self) -> dict[str, Any]:
        return _without_none({
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "subject_entity_id": self.subject_entity_id,
            "object_entity_id": self.object_entity_id,
            "confidence_category": self.confidence_category,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "evidence_ids": list(self.evidence_ids),
            "attributes": dict(self.attributes),
        })


@dataclass(frozen=True, slots=True)
class TemporalFact:
    fact_id: str
    subject_entity_id: str
    predicate: str
    recorded_at: str
    object_entity_id: str | None = None
    object_value: Any = None
    valid_from: str | None = None
    valid_to: str | None = None
    invalidated_at: str | None = None
    evidence_ids: tuple[str, ...] = ()
    confidence_category: str = "observed"

    def __post_init__(self) -> None:
        for name in ("fact_id", "subject_entity_id", "predicate"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if (self.object_entity_id is None) == (self.object_value is None):
            raise ContractError("invalid_fact_object", "exactly one fact object is required", path="$")
        if self.object_entity_id is not None:
            object.__setattr__(self, "object_entity_id", _identifier(self.object_entity_id, "object_entity_id"))
        else:
            _json_value(self.object_value, "$.object_value")
        if self.confidence_category not in {"observed", "asserted", "inferred", "model_proposed"}:
            raise ContractError("invalid_confidence_category", self.confidence_category, path="$.confidence_category")
        object.__setattr__(self, "evidence_ids", tuple(_identifier(value, "evidence_id") for value in self.evidence_ids))
        for name, required in (("recorded_at", True), ("valid_from", False), ("valid_to", False), ("invalidated_at", False)):
            object.__setattr__(self, name, normalize_timestamp(getattr(self, name), name, required=required))
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ContractError("invalid_time_range", "valid_to precedes valid_from", path="$.valid_to")

    def to_dict(self) -> dict[str, Any]:
        return _without_none({
            "fact_id": self.fact_id,
            "subject_entity_id": self.subject_entity_id,
            "predicate": self.predicate,
            "object_entity_id": self.object_entity_id,
            "object_value": self.object_value,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "recorded_at": self.recorded_at,
            "invalidated_at": self.invalidated_at,
            "evidence_ids": list(self.evidence_ids),
            "confidence_category": self.confidence_category,
        })


@dataclass(frozen=True, slots=True)
class AlertRevision:
    revision_id: str
    alert_entity_id: str
    revision_number: int
    change_type: str
    event_time: str
    recorded_at: str
    checksum: str
    previous_revision_id: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        for name in ("revision_id", "alert_entity_id", "checksum"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.revision_number < 1:
            raise ContractError("invalid_revision_number", "revision_number must be positive", path="$.revision_number")
        if self.change_type not in {"new_occurrence", "correction", "state_change", "supersession", "retraction", "late_arrival"}:
            raise ContractError("invalid_revision_type", self.change_type, path="$.change_type")
        object.__setattr__(self, "event_time", normalize_timestamp(self.event_time, "event_time", required=True))
        object.__setattr__(self, "recorded_at", normalize_timestamp(self.recorded_at, "recorded_at", required=True))

    def to_dict(self) -> dict[str, Any]:
        return _without_none({
            "revision_id": self.revision_id,
            "alert_entity_id": self.alert_entity_id,
            "revision_number": self.revision_number,
            "change_type": self.change_type,
            "event_time": self.event_time,
            "recorded_at": self.recorded_at,
            "checksum": self.checksum,
            "previous_revision_id": self.previous_revision_id,
            "status": self.status,
        })


@dataclass(frozen=True, slots=True)
class SecurityKnowledgeEvent:
    tenant_id: str
    source_system: str
    source_instance: str
    source_record_id: str
    event_id: str
    event_type: str
    event_time: str
    observed_at: str
    recorded_at: str
    entities: tuple[CanonicalEntity, ...] = ()
    relations: tuple[KnowledgeRelation, ...] = ()
    facts: tuple[TemporalFact, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    vendor_fields: Mapping[str, Any] = field(default_factory=dict)
    source_references: tuple[str, ...] = ()
    source_revision_id: str | None = None
    delivery_id: str | None = None
    processed_at: str | None = None
    curated_payload_version: str | None = None
    content_checksum_version: str = SOURCE_CONTENT_CHECKSUM_VERSION
    content_checksum: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("unsupported_version", self.schema_version, path="$.schema_version")
        for name in ("tenant_id", "source_system", "source_instance", "source_record_id", "event_id", "event_type"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("event_time", "observed_at", "recorded_at"):
            object.__setattr__(self, name, normalize_timestamp(getattr(self, name), name, required=True))
        object.__setattr__(self, "processed_at", normalize_timestamp(self.processed_at, "processed_at"))
        for name in ("source_revision_id", "delivery_id", "curated_payload_version"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(
            self, "source_references",
            tuple(_text(value, "source_reference") for value in self.source_references),
        )
        if self.content_checksum_version not in {
            LEGACY_CHECKSUM_VERSION, SOURCE_CONTENT_CHECKSUM_V2, SOURCE_CONTENT_CHECKSUM_VERSION,
        }:
            raise ContractError("unsupported_checksum_version", self.content_checksum_version, path="$.content_checksum_version")
        _json_value(self.attributes, "$.attributes")
        _json_value(self.vendor_fields, "$.vendor_fields")
        entity_ids = [entity.entity_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ContractError("duplicate_entity", "event contains duplicate entity_id", path="$.entities")
        known = set(entity_ids)
        relation_ids = [relation.relation_id for relation in self.relations]
        fact_ids = [fact.fact_id for fact in self.facts]
        evidence_ids = [item.evidence_id for item in self.evidence]
        for values, code, path in (
            (relation_ids, "duplicate_relation", "$.relations"),
            (fact_ids, "duplicate_fact", "$.facts"),
            (evidence_ids, "duplicate_evidence", "$.evidence"),
        ):
            if len(values) != len(set(values)):
                raise ContractError(code, f"event contains duplicate {code.removeprefix('duplicate_')}_id", path=path)
        known_evidence = set(evidence_ids)
        for index, relation in enumerate(self.relations):
            if relation.subject_entity_id not in known or relation.object_entity_id not in known:
                raise ContractError("invalid_entity_reference", "relation references an entity outside this event", path=f"$.relations[{index}]")
            if not set(relation.evidence_ids) <= known_evidence:
                raise ContractError("invalid_evidence_reference", "relation references evidence outside this event", path=f"$.relations[{index}]")
        for index, fact in enumerate(self.facts):
            if fact.subject_entity_id not in known or (fact.object_entity_id and fact.object_entity_id not in known):
                raise ContractError("invalid_entity_reference", "fact references an entity outside this event", path=f"$.facts[{index}]")
            if not set(fact.evidence_ids) <= known_evidence:
                raise ContractError("invalid_evidence_reference", "fact references evidence outside this event", path=f"$.facts[{index}]")
        calculated = self.calculate_checksum()
        if self.content_checksum is not None and self.content_checksum != calculated:
            raise ContractError("checksum_mismatch", "content_checksum does not match canonical event content", path="$.content_checksum")
        object.__setattr__(self, "content_checksum", calculated)
        if len(self.to_json().encode("utf-8")) > MAX_EVENT_BYTES:
            raise ContractError("payload_too_large", f"event exceeds {MAX_EVENT_BYTES} bytes")

    @property
    def source_key(self) -> tuple[str, str, str, str]:
        return self.tenant_id, self.source_system, self.source_instance, self.source_record_id

    def _payload(self, *, include_checksum: bool) -> dict[str, Any]:
        data = _without_none({
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "source_system": self.source_system,
            "source_instance": self.source_instance,
            "source_record_id": self.source_record_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_time": self.event_time,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "source_revision_id": self.source_revision_id,
            "delivery_id": self.delivery_id,
            "processed_at": self.processed_at,
            "source_references": list(self.source_references),
            "entities": [item.to_dict() for item in self.entities],
            "relations": [item.to_dict() for item in self.relations],
            "facts": [item.to_dict() for item in self.facts],
            "evidence": [item.to_dict() for item in self.evidence],
            "attributes": dict(self.attributes),
            "vendor_fields": dict(self.vendor_fields),
            "curated_payload_version": self.curated_payload_version,
            "content_checksum_version": self.content_checksum_version,
        })
        if include_checksum:
            data["content_checksum"] = self.content_checksum
        if self.content_checksum_version == SOURCE_CONTENT_CHECKSUM_VERSION:
            _canonicalize_v3_collections(data)
        return data

    def calculate_checksum(self) -> str:
        payload = self._payload(include_checksum=False)
        if self.content_checksum_version == LEGACY_CHECKSUM_VERSION:
            # Exact compatibility with events serialized before checksum
            # algorithms were named.  New fields did not exist in that form.
            for key in ("source_revision_id", "delivery_id", "processed_at", "content_checksum_version"):
                payload.pop(key, None)
            encoded = canonical_json(payload).encode("utf-8")
        else:
            # Knowledge/delivery time changes on a replay and is not source
            # content.  Source occurrence/observation time remains included.
            for key in ("recorded_at", "delivery_id", "processed_at", "content_checksum_version"):
                payload.pop(key, None)
            for fact in payload.get("facts", []):
                fact.pop("recorded_at", None)
            encoded = (self.content_checksum_version + "\0" + canonical_json(payload)).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return self._payload(include_checksum=True)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SecurityKnowledgeEvent":
        allowed = {
            "schema_version", "tenant_id", "source_system", "source_instance", "source_record_id",
            "event_id", "event_type", "event_time", "observed_at", "recorded_at", "entities",
            "relations", "facts", "evidence", "attributes", "vendor_fields", "source_references",
            "curated_payload_version", "content_checksum",
            "source_revision_id", "delivery_id", "processed_at", "content_checksum_version",
        }
        extras = sorted(set(data) - allowed)
        if extras:
            raise ContractError("unknown_contract_field", f"move vendor fields under vendor_fields: {extras}")
        required = ("tenant_id", "source_system", "source_instance", "source_record_id", "event_id", "event_type", "event_time", "observed_at", "recorded_at")
        for name in required:
            if name not in data:
                raise ContractError("missing_required_field", f"{name} is required", path=f"$.{name}")
        try:
            checksum_version = data.get("content_checksum_version")
            if checksum_version is None:
                checksum_version = LEGACY_CHECKSUM_VERSION if data.get("content_checksum") else SOURCE_CONTENT_CHECKSUM_VERSION
            return cls(
                schema_version=data.get("schema_version", SCHEMA_VERSION),
                tenant_id=data["tenant_id"], source_system=data["source_system"], source_instance=data["source_instance"],
                source_record_id=data["source_record_id"], event_id=data["event_id"], event_type=data["event_type"],
                event_time=data["event_time"], observed_at=data["observed_at"], recorded_at=data["recorded_at"],
                entities=tuple(CanonicalEntity(**x) for x in data.get("entities", [])),
                relations=tuple(KnowledgeRelation(**x) for x in data.get("relations", [])),
                facts=tuple(TemporalFact(**x) for x in data.get("facts", [])),
                evidence=tuple(EvidenceReference(**x) for x in data.get("evidence", [])),
                attributes=data.get("attributes", {}), vendor_fields=data.get("vendor_fields", {}),
                source_references=tuple(data.get("source_references", [])),
                source_revision_id=data.get("source_revision_id"), delivery_id=data.get("delivery_id"),
                processed_at=data.get("processed_at"), curated_payload_version=data.get("curated_payload_version"),
                content_checksum_version=checksum_version, content_checksum=data.get("content_checksum"),
            )
        except (TypeError, KeyError) as exc:
            raise ContractError("malformed_contract", str(exc)) from exc

    @classmethod
    def from_json(cls, raw: str | bytes) -> "SecurityKnowledgeEvent":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ContractError("malformed_json", str(exc)) from exc
        if not isinstance(data, dict):
            raise ContractError("unexpected_type", "knowledge event must be a JSON object")
        return cls.from_dict(data)


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    tenant_id: str
    text: str
    exact_identifiers: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ()
    valid_at: str | None = None
    known_as_of: str | None = None
    top_k: int = 10

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        if not self.text.strip() and not self.exact_identifiers:
            raise ContractError("empty_query", "text or an exact identifier is required", path="$.text")
        if not 1 <= self.top_k <= 100:
            raise ContractError("invalid_top_k", "top_k must be 1..100", path="$.top_k")
        object.__setattr__(self, "valid_at", normalize_timestamp(self.valid_at, "valid_at"))
        object.__setattr__(self, "known_as_of", normalize_timestamp(self.known_as_of, "known_as_of"))


@dataclass(frozen=True, slots=True)
class KnowledgeContext:
    query_id: str
    tenant_id: str
    status: str
    items: tuple[Mapping[str, Any], ...]
    retrieval_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        if self.status not in {"complete", "partial", "fallback", "unavailable"}:
            raise ContractError("invalid_retrieval_status", self.status, path="$.status")
        _json_value(self.retrieval_metadata, "$.retrieval_metadata")


@dataclass(frozen=True, slots=True)
class DuplicateObservation:
    source_key: tuple[str, str, str, str]
    first_event_id: str
    second_event_id: str
    disposition: str


def validate_event_batch(events: Iterable[SecurityKnowledgeEvent]) -> list[DuplicateObservation]:
    """Detect exact replays and source-key conflicts without discarding either."""

    seen: dict[tuple[str, str, str, str], SecurityKnowledgeEvent] = {}
    duplicates: list[DuplicateObservation] = []
    for event in events:
        previous = seen.get(event.source_key)
        if previous is None:
            seen[event.source_key] = event
            continue
        duplicates.append(DuplicateObservation(
            source_key=event.source_key,
            first_event_id=previous.event_id,
            second_event_id=event.event_id,
            disposition="exact_replay" if previous.content_checksum == event.content_checksum else "changed_revision",
        ))
    return duplicates


def _without_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _canonicalize_v3_collections(payload: dict[str, Any]) -> None:
    """Normalize set-like v3 collections without changing legacy v1/v2 bytes."""

    payload["source_references"] = sorted(set(payload.get("source_references", [])))
    for entity in payload.get("entities", []):
        entity["aliases"] = sorted(set(entity.get("aliases", [])))
    for relation in payload.get("relations", []):
        relation["evidence_ids"] = sorted(set(relation.get("evidence_ids", [])))
    for fact in payload.get("facts", []):
        fact["evidence_ids"] = sorted(set(fact.get("evidence_ids", [])))
    for evidence in payload.get("evidence", []):
        evidence["source_event_ids"] = sorted(set(evidence.get("source_event_ids", [])))
    payload["entities"].sort(key=lambda row: row["entity_id"])
    payload["relations"].sort(key=lambda row: row["relation_id"])
    payload["facts"].sort(key=lambda row: row["fact_id"])
    payload["evidence"].sort(key=lambda row: row["evidence_id"])
