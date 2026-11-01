"""Field-aware deterministic SOC extraction.

Structured source fields always win. Regex enrichment is limited to explicitly
unstructured fields and never scans SPL, macro definitions, or timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from soorin.identity.normalization import IdentityNormalizationError, normalize_entity_value, normalize_hostname, normalize_principal, normalize_text
from .soc_entities import FIELD_TYPES, SKIP_REGEX_FIELDS, UNSTRUCTURED_FIELDS

MITRE_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
HASH_RE = re.compile(r"\b(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{40}|[0-9a-fA-F]{32})\b")
IP_TOKEN_RE = re.compile(r"(?<![\w:])(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F]*:[0-9a-fA-F:]+)(?![\w:])")
URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
WINDOWS_PRINCIPAL_RE = re.compile(r"\b[A-Za-z0-9_.-]{1,64}\\[A-Za-z0-9_.@$-]{1,128}\b")
TICKET_RE = re.compile(r"\b(?:INC|CASE|SOC|CHG|JIRA)-[A-Z0-9-]{2,64}\b", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?<!\w)[A-Za-z]:\\(?:[^\s<>:\"/\\|?*]+\\)*[^\s<>:\"/\\|?*]+")
POSIX_PATH_RE = re.compile(r"(?<!\w)/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+")
DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    entity_type: str
    normalized_value: str
    source_field: str
    source_record_reference: str
    confidence_category: str
    extraction_method: str
    timestamp_context: str | None
    provenance: Mapping[str, str]
    original_value: str


@dataclass(frozen=True, slots=True)
class ExtractionBatch:
    entities: tuple[ExtractionResult, ...]
    errors: tuple[str, ...] = ()


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            yield from _flatten(value, path)
        else:
            yield path, value


def _values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield str(value)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _values(item)


def _normalize(entity_type: str, raw: str, field: str) -> str:
    leaf = field.rsplit(".", 1)[-1].casefold()
    if entity_type == "Indicator":
        if leaf in {"domain", "fqdn"}:
            return normalize_hostname(raw)
        if leaf == "url":
            parsed = urlsplit(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise IdentityNormalizationError("invalid URL")
            return raw.strip()
        if leaf in {"sha256", "sha1", "md5", "hash", "file_hash"}:
            value = raw.casefold()
            if not re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64}", value):
                raise IdentityNormalizationError("invalid file hash")
            return value
        return normalize_text(raw)
    return normalize_entity_value(entity_type, raw)


def extract_entities(
    data: Mapping[str, Any], *, source_record_reference: str,
    timestamp_context: str | None = None, include_unstructured: bool = True,
) -> ExtractionBatch:
    found: dict[tuple[str, str], ExtractionResult] = {}
    errors: list[str] = []

    def add(entity_type: str, raw: str, field: str, method: str, confidence: str) -> None:
        try:
            normalized = _normalize(entity_type, raw, field)
        except (IdentityNormalizationError, ValueError) as exc:
            errors.append(f"{field}: {exc}")
            return
        key = entity_type, normalized
        found.setdefault(key, ExtractionResult(
            entity_type=entity_type,
            normalized_value=normalized,
            source_field=field,
            source_record_reference=source_record_reference,
            confidence_category=confidence,
            extraction_method=method,
            timestamp_context=timestamp_context,
            provenance={"source_field": field, "record": source_record_reference},
            original_value=raw,
        ))

    flattened = list(_flatten(data))
    for field, value in flattened:
        leaf = field.rsplit(".", 1)[-1].casefold()
        entity_type = FIELD_TYPES.get(leaf)
        if entity_type:
            for raw in _values(value):
                # ``entity`` and ``risk_object`` types are context sensitive.
                context_type = entity_type
                if leaf == "entity":
                    hinted = str(data.get("entity_type") or "").casefold()
                    context_type = "UserAccount" if "user" in hinted else "IPAddress" if "ip" in hinted else "Host"
                if leaf == "risk_object":
                    hinted = str(data.get("risk_object_type") or "").casefold()
                    context_type = "Host" if hinted in {"system", "host", "device"} else "IPAddress" if "ip" in hinted else "UserAccount"
                add(context_type, raw, field, "structured_field", "observed")

    if include_unstructured:
        for field, value in flattened:
            leaf = field.rsplit(".", 1)[-1].casefold()
            if leaf in SKIP_REGEX_FIELDS or leaf not in UNSTRUCTURED_FIELDS:
                continue
            for text in _values(value):
                for match in MITRE_RE.findall(text):
                    add("MITRETechnique", match, field, "validated_regex", "reported")
                for match in HASH_RE.findall(text):
                    add("Indicator", match, "file_hash", "validated_regex", "reported")
                for match in URL_RE.findall(text):
                    add("Indicator", match.rstrip(".,;)"), "url", "validated_regex", "reported")
                for match in WINDOWS_PRINCIPAL_RE.findall(text):
                    add("UserAccount", match, field, "validated_regex", "reported")
                for match in TICKET_RE.findall(text):
                    add("Ticket", match.upper(), field, "validated_regex", "reported")
                for match in WINDOWS_PATH_RE.findall(text):
                    add("Indicator", match, "file_path", "validated_regex", "reported")
                for match in POSIX_PATH_RE.findall(text):
                    add("Indicator", match, "file_path", "validated_regex", "reported")
                for match in IP_TOKEN_RE.findall(text):
                    try:
                        ipaddress.ip_address(match.strip("[]"))
                    except ValueError:
                        continue
                    add("IPAddress", match, field, "validated_regex", "reported")
                # Domains already inside a URL are harmlessly deduplicated by value.
                for match in DOMAIN_RE.findall(text):
                    add("Indicator", match, "domain", "validated_regex", "reported")
    return ExtractionBatch(tuple(found.values()), tuple(errors))
