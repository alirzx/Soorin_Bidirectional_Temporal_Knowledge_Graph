"""Convert canonical SOC knowledge events to Utopia's open e/s/n contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from soorin.contracts import SecurityKnowledgeEvent

MAX_BYTES = 64 * 1024
MAX_STATEMENTS = 200
ALLOWED_RESPONSE_ACTIONS = {"created", "updated", "unchanged", "marked_missing"}


class StatementsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _phrase(value: str) -> str:
    return value.strip().replace("_", " ").casefold()


def _qualifiers(event: SecurityKnowledgeEvent, *, evidence: str = "", confidence: str = "observed") -> dict[str, str]:
    values = {
        "schema_version": event.schema_version,
        "tenant_id": event.tenant_id,
        "source_system": event.source_system,
        "source_instance": event.source_instance,
        "source_record_id": event.source_record_id,
        "confidence_category": confidence,
    }
    if evidence:
        values["evidence_id"] = evidence
    return values


@dataclass(slots=True)
class StatementsAdapter:
    max_bytes: int = MAX_BYTES
    max_statements: int = MAX_STATEMENTS

    def external_id(self, event: SecurityKnowledgeEvent) -> str:
        raw = "|".join(event.source_key)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"soorin-soc-v1:{event.tenant_id}:{digest}"

    def render(self, event: SecurityKnowledgeEvent) -> dict[str, Any]:
        entities = [[entity.entity_id, entity.entity_type, True] for entity in event.entities]
        aliases = [[entity.entity_id, entity.normalized_value, None] for entity in event.entities if entity.normalized_value != entity.entity_id]
        statements: list[list[Any]] = []

        for relation in event.relations:
            evidence = relation.evidence_ids[0] if relation.evidence_ids else ""
            statements.append([
                None, relation.subject_entity_id, _phrase(relation.relation_type), relation.object_entity_id, None,
                _qualifiers(event, evidence=evidence, confidence=relation.confidence_category),
                relation.valid_from or event.event_time, relation.valid_to,
            ])
        for fact in event.facts:
            evidence = fact.evidence_ids[0] if fact.evidence_ids else ""
            statements.append([
                None, fact.subject_entity_id, _phrase(fact.predicate), fact.object_entity_id,
                None if fact.object_entity_id else _literal(fact.object_value),
                _qualifiers(event, evidence=evidence, confidence=fact.confidence_category),
                fact.valid_from or event.event_time, fact.valid_to,
            ])

        if not entities:
            raise StatementsError("missing_entities", "the Statements contract requires at least one subject entity")
        subject = event.entities[0].entity_id
        core_literals = {
            "has event type": event.event_type,
            "has source record id": event.source_record_id,
            "has content checksum": event.content_checksum,
            "observed at": event.observed_at,
            "recorded at": event.recorded_at,
        }
        for phrase, value in core_literals.items():
            statements.append([None, subject, phrase, None, str(value), _qualifiers(event), event.event_time, None])
        # Preserve structured event attributes in one bounded literal. The
        # canonical event remains the source of truth; this literal supports
        # search without inventing graph relations.
        if event.attributes:
            attributes = json.dumps(event.attributes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            statements.append([None, subject, "has structured attributes", None, attributes, _qualifiers(event), event.event_time, None])

        payload = {
            "external_id": self.external_id(event),
            "doc_time": event.event_time,
            "e": entities,
            "s": statements,
            "n": aliases,
        }
        self.validate(payload)
        return payload

    def validate(self, payload: Mapping[str, Any]) -> None:
        allowed = {"external_id", "doc_time", "deleted", "e", "s", "n"}
        extra = set(payload) - allowed
        if extra:
            raise StatementsError("unknown_fields", str(sorted(extra)))
        if not isinstance(payload.get("external_id"), str) or not payload["external_id"].strip():
            raise StatementsError("invalid_external_id", "external_id is required")
        entities = payload.get("e")
        statements = payload.get("s")
        names = payload.get("n")
        if not all(isinstance(value, list) for value in (entities, statements, names)):
            raise StatementsError("invalid_array", "e, s and n must be arrays")
        if not 1 <= len(statements) <= self.max_statements:
            raise StatementsError("invalid_statement_count", f"expected 1..{self.max_statements}, got {len(statements)}")
        declared: set[str] = set()
        for index, row in enumerate(entities):
            if not isinstance(row, list) or len(row) != 3 or not isinstance(row[2], bool):
                raise StatementsError("invalid_entity", f"e[{index}] must be [name, kind, named]")
            declared.add(str(row[0]).strip().casefold())
        for index, row in enumerate(statements):
            if not isinstance(row, list) or len(row) != 8 or row[0] is not None:
                raise StatementsError("invalid_statement", f"s[{index}] must be an eight-slot unquoted statement")
            if str(row[1]).strip().casefold() not in declared:
                raise StatementsError("unknown_subject", f"s[{index}] subject is not declared in e")
            if row[3] is not None and str(row[3]).strip().casefold() not in declared:
                raise StatementsError("unknown_object", f"s[{index}] object is not declared in e")
            if (row[3] is None) == (row[4] is None):
                raise StatementsError("invalid_object", f"s[{index}] requires exactly one object or literal")
            if row[5] is not None and (not isinstance(row[5], dict) or not all(isinstance(v, str) for v in row[5].values())):
                raise StatementsError("invalid_qualifiers", f"s[{index}] qualifiers must contain strings")
        for index, row in enumerate(names):
            if not isinstance(row, list) or len(row) != 3 or row[2] is not None:
                raise StatementsError("invalid_alias", f"n[{index}] must be [entity, alias, null]")
            if str(row[0]).strip().casefold() not in declared:
                raise StatementsError("unknown_alias_subject", f"n[{index}] subject is not declared in e")
        raw = self.dumps(payload).encode("utf-8")
        if len(raw) > self.max_bytes:
            raise StatementsError("payload_too_large", f"payload is {len(raw)} bytes; limit is {self.max_bytes}")

    @staticmethod
    def dumps(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _literal(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


Transport = Callable[[urllib.request.Request, float], Mapping[str, Any]]


@dataclass(slots=True)
class StatementsClient:
    base_url: str
    source_id: str
    ingest_token: str
    timeout_seconds: float = 15.0
    transport: Transport | None = None

    def push(self, payload: Mapping[str, Any]) -> str:
        StatementsAdapter().validate(payload)
        url = f"{self.base_url.rstrip('/')}/api/v1/sources/{self.source_id}/statements"
        request = urllib.request.Request(
            url,
            StatementsAdapter.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.ingest_token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self.transport(request, self.timeout_seconds) if self.transport else _urlopen_json(request, self.timeout_seconds)
        except TimeoutError as exc:
            raise StatementsError("api_timeout", str(exc)) from exc
        except urllib.error.HTTPError as exc:
            body = exc.read(2048).decode("utf-8", errors="replace")
            code = "authentication_failed" if exc.code in {401, 403} else "api_error"
            raise StatementsError(code, f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise StatementsError("api_unavailable", str(exc.reason)) from exc
        if not isinstance(response, Mapping):
            raise StatementsError("malformed_api_response", "response is not an object")
        action = response.get("action")
        if action not in ALLOWED_RESPONSE_ACTIONS:
            raise StatementsError("malformed_api_response", f"unexpected action {action!r}")
        return str(action)


def _urlopen_json(request: urllib.request.Request, timeout: float) -> Mapping[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise StatementsError("malformed_api_response", "response is not an object")
    return decoded
