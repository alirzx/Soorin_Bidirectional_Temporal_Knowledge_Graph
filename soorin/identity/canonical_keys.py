"""Canonical-key generation and conservative resolution decisions.

Embedding or alias similarity may propose candidates, but never produces an
automatic merge.  Automatic identity requires a trusted source identifier and
always includes tenant scope.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from .normalization import IdentityNormalizationError, normalize_entity_value, normalize_text

AUTHORITATIVE_TYPES = {
    "Host", "SecurityAlert", "SplunkNotable", "SecurityEvent", "DetectionRule",
    "SOCCase", "InvestigationRun", "Report", "Ticket",
}
NETWORK_SCOPED_TYPES = {"IPAddress", "Network"}


@dataclass(frozen=True, slots=True)
class IdentityInput:
    tenant_id: str
    source_system: str
    source_instance: str
    entity_type: str
    observed_value: str
    authoritative_id: str | None = None
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityDecision:
    canonical_key: str
    normalized_value: str
    status: str
    automatic: bool
    rationale: str
    aliases: tuple[str, ...] = ()
    candidate_keys: tuple[str, ...] = ()


def canonical_key(
    *, tenant_id: str, source_system: str, source_instance: str, entity_type: str,
    authoritative_id: str | None = None, normalized_value: str | None = None,
    scope: str | None = None, provisional: bool = False,
) -> str:
    tenant = normalize_text(tenant_id).casefold()
    source = normalize_text(source_system).casefold()
    instance = normalize_text(source_instance).casefold()
    etype = normalize_text(entity_type)
    authority = normalize_text(authoritative_id).casefold() if authoritative_id else None
    value = normalize_entity_value(etype, normalized_value) if normalized_value else None
    if not authority and not value:
        raise IdentityNormalizationError("authoritative_id or normalized_value is required")
    payload = {
        "tenant_id": tenant,
        "entity_type": etype,
        "source_system": source if authority else None,
        "source_instance": instance if authority else None,
        "authoritative_id": authority,
        "normalized_value": value if not authority else None,
        "scope": normalize_text(scope).casefold() if scope else None,
        "provisional": bool(provisional or not authority),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"soorin:{etype.casefold()}:{digest}"


def resolve_identity(item: IdentityInput, *, known_aliases: Iterable[IdentityDecision] = ()) -> IdentityDecision:
    normalized = normalize_entity_value(item.entity_type, item.observed_value)
    authoritative_id = item.authoritative_id.strip() if isinstance(item.authoritative_id, str) else None
    authoritative_id = authoritative_id or None
    needs_authority = item.entity_type in AUTHORITATIVE_TYPES
    needs_scope = item.entity_type in NETWORK_SCOPED_TYPES
    if needs_scope and not item.scope:
        key = canonical_key(
            tenant_id=item.tenant_id, source_system=item.source_system, source_instance=item.source_instance,
            entity_type=item.entity_type, normalized_value=normalized, provisional=True,
        )
        return IdentityDecision(key, normalized, "ambiguous", False, "network-scoped identity is missing scope")
    if authoritative_id:
        key = canonical_key(
            tenant_id=item.tenant_id, source_system=item.source_system, source_instance=item.source_instance,
            entity_type=item.entity_type, authoritative_id=authoritative_id, scope=item.scope,
        )
        return IdentityDecision(key, normalized, "resolved", True, "trusted tenant- and source-scoped identifier")
    key = canonical_key(
        tenant_id=item.tenant_id, source_system=item.source_system, source_instance=item.source_instance,
        entity_type=item.entity_type, normalized_value=normalized, scope=item.scope, provisional=True,
    )
    candidates = tuple(sorted({decision.canonical_key for decision in known_aliases if decision.normalized_value == normalized}))
    if needs_authority:
        reason = "authoritative identifier missing; alias-only identity requires review"
        status = "ambiguous" if candidates else "provisional"
    else:
        reason = "normalized tenant-scoped value; no automatic cross-source merge"
        status = "provisional"
    return IdentityDecision(key, normalized, status, False, reason, candidate_keys=candidates)
