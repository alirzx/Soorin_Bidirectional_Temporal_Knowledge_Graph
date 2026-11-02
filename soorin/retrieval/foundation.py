"""Bounded Python retrieval evaluator; Rust Utopia remains production authority."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import math
import re
import time
from typing import Any, Mapping, Sequence

from soorin.contracts import KnowledgeContext, KnowledgeQuery
from .reranker import Candidate, rerank_with_fallback


@dataclass(frozen=True, slots=True)
class SearchDocument:
    document_id: str
    tenant_id: str
    text: str
    identifiers: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    valid_from: str | None = None
    valid_to: str | None = None
    recorded_at: str | None = None
    invalidated_at: str | None = None
    typed_identifiers: tuple[tuple[str, str], ...] = ()
    embedding: tuple[float, ...] | None = None


@dataclass(slots=True)
class RetrievalFoundation:
    """Offline comparison harness, not a second production retrieval runtime."""

    documents: Sequence[SearchDocument]
    embedder: Any | None = None
    reranker: Any | None = None
    candidate_limit: int = 100
    dense_candidate_limit: int = 64
    vector_cache_capacity: int = 4096
    reranker_fallback_enabled: bool | None = None
    _vector_cache: OrderedDict[str, tuple[float, ...]] = field(default_factory=OrderedDict, init=False, repr=False)
    _cache_hits: int = field(default=0, init=False)
    _cache_misses: int = field(default=0, init=False)
    _cache_evictions: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not 1 <= self.candidate_limit <= 10_000:
            raise ValueError("candidate_limit must be 1..10000")
        if not 1 <= self.dense_candidate_limit <= 10_000:
            raise ValueError("dense_candidate_limit must be 1..10000")
        if not 1 <= self.vector_cache_capacity <= 1_000_000:
            raise ValueError("vector_cache_capacity must be 1..1000000")

    def search(self, query: KnowledgeQuery) -> KnowledgeContext:
        started = time.perf_counter()
        query_id = hashlib.sha256(repr(query).encode("utf-8")).hexdigest()[:24]
        eligible = [document for document in self.documents if self._eligible(document, query)]
        exact = self._exact(eligible, query.exact_identifiers, query.entity_types)
        if exact:
            items = [self._item(document, 1.0, "exact_identifier") for document in exact[:query.top_k]]
            return KnowledgeContext(query_id, query.tenant_id, "complete", tuple(items), {
                "query_id": query_id, "retrieval_method": "exact_identifier", "score_type": "exact_match",
                "runtime": "python_evaluation_only",
                "candidate_count": len(exact), "returned_count": len(items), "reranked": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "temporal_filters": {"valid_at": query.valid_at, "known_as_of": query.known_as_of},
            })
        if not query.text.strip():
            return KnowledgeContext(query_id, query.tenant_id, "unavailable", (), {
                "query_id": query_id, "retrieval_method": "exact_identifier", "candidate_count": 0,
                "returned_count": 0, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            })
        channel_limit = min(self.candidate_limit, max(query.top_k * 3, 24))
        bm25 = self._bm25(eligible, query.text, channel_limit)
        dense: list[tuple[SearchDocument, float]] = []
        dense_error: str | None = None
        dense_inputs: list[SearchDocument] = []
        if self.embedder is not None and eligible:
            try:
                dense_inputs = self._dense_candidates(eligible, bm25)
                dense = self._dense(dense_inputs, query.text, channel_limit)
            except Exception as exc:  # provider errors are surfaced in metadata
                dense_error = getattr(exc, "code", type(exc).__name__)
        fused = _rrf([bm25, dense])[:self.candidate_limit]
        by_id = {document.document_id: document for document in eligible}
        candidates = [Candidate(doc_id, by_id[doc_id].text, by_id[doc_id].metadata, rank) for rank, (doc_id, _) in enumerate(fused)]
        fallback_enabled = self.reranker_fallback_enabled
        if fallback_enabled is None:
            fallback_enabled = getattr(getattr(self.reranker, "config", None), "fallback_enabled", True)
        reranked = rerank_with_fallback(
            query.text, candidates, self.reranker, top_n=query.top_k,
            fallback_enabled=fallback_enabled,
        )
        score_by_id = {row.candidate.candidate_id: row.score for row in reranked.results}
        rrf_by_id = dict(fused)
        items = [self._item(by_id[row.candidate.candidate_id], score_by_id[row.candidate.candidate_id] if score_by_id[row.candidate.candidate_id] is not None else rrf_by_id[row.candidate.candidate_id], "reranker" if row.score is not None else "rrf") for row in reranked.results]
        if not bm25 and not dense:
            status = "unavailable"
        elif dense_error or reranked.status == "fallback":
            status = "fallback"
        elif not dense:
            status = "partial"
        else:
            status = "complete"
        methods = ["bm25"] + (["dense"] if dense else []) + (["rrf"] if dense else []) + (["reranker"] if reranked.status == "complete" and self.reranker else [])
        metadata = {
            "query_id": query_id, "retrieval_method": "+".join(methods),
            "runtime": "python_evaluation_only",
            "embedding_provider": getattr(self.embedder, "provider", None),
            "model_version": getattr(self.embedder, "model", "deterministic-or-none"),
            "reranker_provider": reranked.provider,
            "reranker_model": reranked.model, "reranker_status": reranked.status,
            "score_type": "reranker_score" if self.reranker and reranked.status == "complete" else "rrf_score",
            "eligible_count": len(eligible), "keyword_candidate_count": len(bm25),
            "dense_input_count": len(dense_inputs), "dense_candidate_count": len(dense),
            "candidate_count": len(candidates), "candidate_limit": self.candidate_limit,
            "dense_candidate_limit": self.dense_candidate_limit, "returned_count": len(items),
            "temporal_filters": {"valid_at": query.valid_at, "known_as_of": query.known_as_of},
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "embedding_error": dense_error, "reranker_error": reranked.error_code,
            "vector_cache": self.cache_info(),
        }
        return KnowledgeContext(query_id, query.tenant_id, status, tuple(items), metadata)

    @staticmethod
    def _eligible(document: SearchDocument, query: KnowledgeQuery) -> bool:
        if document.tenant_id != query.tenant_id:
            return False
        if query.entity_types:
            document_types = {kind.casefold() for kind, _ in document.typed_identifiers}
            metadata_type = document.metadata.get("entity_type")
            if isinstance(metadata_type, str):
                document_types.add(metadata_type.casefold())
            if not document_types & {kind.casefold() for kind in query.entity_types}:
                return False
        if query.valid_at:
            if document.valid_from and query.valid_at < document.valid_from:
                return False
            if document.valid_to and query.valid_at >= document.valid_to:
                return False
        if query.known_as_of:
            if document.recorded_at and document.recorded_at > query.known_as_of:
                return False
            if document.invalidated_at and document.invalidated_at <= query.known_as_of:
                return False
        return True

    @staticmethod
    def _exact(
        documents: Sequence[SearchDocument], identifiers: Sequence[str],
        entity_types: Sequence[str] = (),
    ) -> list[SearchDocument]:
        wanted = {value.casefold() for value in identifiers}
        wanted_types = {value.casefold() for value in entity_types}
        matches: list[SearchDocument] = []
        for document in documents:
            if wanted_types:
                typed = {
                    identifier.casefold() for kind, identifier in document.typed_identifiers
                    if kind.casefold() in wanted_types
                }
                metadata_type = document.metadata.get("entity_type")
                if isinstance(metadata_type, str) and metadata_type.casefold() in wanted_types:
                    typed.update(value.casefold() for value in (document.document_id, *document.identifiers))
                if wanted & typed:
                    matches.append(document)
            elif wanted & {value.casefold() for value in (document.document_id, *document.identifiers)}:
                matches.append(document)
        return matches

    @staticmethod
    def _bm25(documents: Sequence[SearchDocument], query: str, limit: int) -> list[tuple[SearchDocument, float]]:
        terms = _tokens(query)
        if not terms or not documents:
            return []
        doc_terms = [_tokens(document.text) for document in documents]
        avg_len = sum(map(len, doc_terms)) / len(doc_terms) or 1.0
        scores: list[tuple[SearchDocument, float]] = []
        for document, tokens in zip(documents, doc_terms):
            score = 0.0
            for term in terms:
                frequency = tokens.count(term)
                if not frequency:
                    continue
                containing = sum(1 for row in doc_terms if term in row)
                idf = math.log(1 + (len(documents) - containing + 0.5) / (containing + 0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * len(tokens) / avg_len))
            if score:
                scores.append((document, score))
        scores.sort(key=lambda item: (-item[1], item[0].document_id))
        return scores[:limit]

    def _dense_candidates(
        self, eligible: Sequence[SearchDocument], bm25: Sequence[tuple[SearchDocument, float]],
    ) -> list[SearchDocument]:
        ordered: list[SearchDocument] = []
        seen: set[str] = set()
        for document in [*[row[0] for row in bm25], *sorted(eligible, key=lambda row: row.document_id)]:
            if document.document_id not in seen:
                ordered.append(document)
                seen.add(document.document_id)
            if len(ordered) >= min(self.dense_candidate_limit, self.candidate_limit):
                break
        return ordered

    def _dense(self, documents: Sequence[SearchDocument], query: str, limit: int) -> list[tuple[SearchDocument, float]]:
        resolved: dict[str, Sequence[float]] = {}
        missing: list[SearchDocument] = []
        for document in documents:
            if document.embedding is not None:
                resolved[document.document_id] = document.embedding
                continue
            key = self._vector_cache_key(document)
            cached = self._vector_cache.get(key)
            if cached is None:
                self._cache_misses += 1
                missing.append(document)
            else:
                self._cache_hits += 1
                self._vector_cache.move_to_end(key)
                resolved[document.document_id] = cached
        vectors = self.embedder.embed([query, *[document.text for document in missing]])
        if len(vectors) != len(missing) + 1:
            raise ValueError("embedding provider returned wrong vector count")
        query_vector = vectors[0]
        for document, vector in zip(missing, vectors[1:]):
            checked = tuple(float(value) for value in vector)
            resolved[document.document_id] = checked
            key = self._vector_cache_key(document)
            self._vector_cache[key] = checked
            self._vector_cache.move_to_end(key)
            while len(self._vector_cache) > self.vector_cache_capacity:
                self._vector_cache.popitem(last=False)
                self._cache_evictions += 1
        scores = [(document, _cosine(query_vector, resolved[document.document_id])) for document in documents]
        scores.sort(key=lambda item: (-item[1], item[0].document_id))
        return scores[:limit]

    def _vector_cache_key(self, document: SearchDocument) -> str:
        namespace = "|".join((
            str(getattr(self.embedder, "provider", "")), str(getattr(self.embedder, "model", "")),
            document.document_id,
        ))
        return hashlib.sha256((namespace + "\0" + document.text).encode("utf-8")).hexdigest()

    def cache_info(self) -> dict[str, int]:
        return {
            "size": len(self._vector_cache), "capacity": self.vector_cache_capacity,
            "hits": self._cache_hits, "misses": self._cache_misses,
            "evictions": self._cache_evictions,
        }

    @staticmethod
    def _item(document: SearchDocument, score: float, score_type: str) -> dict[str, Any]:
        return {
            "document_id": document.document_id, "text": document.text, "score": score,
            "score_type": score_type, "metadata": dict(document.metadata),
            "evidence_references": list(document.evidence_references),
        }


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w.-]+", text.casefold(), flags=re.UNICODE)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    ln = math.sqrt(sum(value * value for value in left))
    rn = math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / (ln * rn) if ln and rn else 0.0


def _rrf(channels: Sequence[Sequence[tuple[SearchDocument, float]]], k: float = 60.0) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for channel in channels:
        for rank, (document, _) in enumerate(channel):
            scores[document.document_id] = scores.get(document.document_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
