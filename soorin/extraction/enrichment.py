"""Deterministic-first extraction with optional, non-authoritative NER."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .deterministic import ExtractionBatch, extract_entities
from .ner import DisabledNer, NerProposal, NerProvider
from .soc_entities import SKIP_REGEX_FIELDS, UNSTRUCTURED_FIELDS


@dataclass(frozen=True, slots=True)
class EnrichmentBatch:
    deterministic: ExtractionBatch
    ner_proposals: tuple[NerProposal, ...]
    errors: tuple[str, ...] = ()


def _unstructured_text(data: Mapping[str, Any]) -> Iterable[str]:
    for key, value in data.items():
        if isinstance(value, Mapping):
            yield from _unstructured_text(value)
            continue
        leaf = str(key).casefold()
        if leaf in SKIP_REGEX_FIELDS or leaf not in UNSTRUCTURED_FIELDS:
            continue
        values = value if isinstance(value, (list, tuple, set)) else (value,)
        for item in values:
            if isinstance(item, str) and item.strip():
                yield item.strip()


def enrich_entities(
    data: Mapping[str, Any], *, source_record_reference: str,
    timestamp_context: str | None = None, ner: NerProvider | None = None,
) -> EnrichmentBatch:
    """Return trusted deterministic results and review-only proposals separately."""

    deterministic = extract_entities(
        data, source_record_reference=source_record_reference,
        timestamp_context=timestamp_context, include_unstructured=True,
    )
    provider = ner or DisabledNer()
    proposals: dict[tuple[str, str, str], NerProposal] = {}
    errors: list[str] = []
    deterministic_keys = {
        (item.entity_type, item.normalized_value.casefold()) for item in deterministic.entities
    }
    for text in _unstructured_text(data):
        try:
            rows = provider.extract(text)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"ner_provider_error:{type(exc).__name__}")
            continue
        for row in rows:
            if not isinstance(row, NerProposal) or not row.review_required:
                errors.append("ner_provider_error:invalid_proposal")
                continue
            if (row.entity_type, row.value.casefold()) in deterministic_keys:
                continue
            key = row.entity_type, row.value.casefold(), row.source_label or ""
            if key not in proposals or row.score > proposals[key].score:
                proposals[key] = row
    ordered = tuple(sorted(
        proposals.values(), key=lambda item: (item.entity_type, item.value.casefold(), item.source_label or ""),
    ))
    return EnrichmentBatch(deterministic, ordered, tuple(errors))
