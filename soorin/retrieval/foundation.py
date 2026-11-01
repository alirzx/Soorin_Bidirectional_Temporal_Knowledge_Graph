"""Reusable exact, BM25, dense, hybrid, and reranked SOC retrieval."""

from __future__ import annotations

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


@dataclass(slots=True)
class RetrievalFoundation:
    documents: Sequence[SearchDocument]
    embedder: Any | None = None
    reranker: Any | None = None

    def search(self, query: KnowledgeQuery) -> KnowledgeContext:
        started = time.perf_counter()
        query_id = hashlib.sha256(repr(query).encode("utf-8")).hexdigest()[:24]
        eligible = [document for document in self.documents if self._eligible(document, query)]
        exact = self._exact(eligible, query.exact_identifiers)
        if exact:
            items = [self._item(document, 1.0, "exact_identifier") for document in exact[:query.top_k]]
            return KnowledgeContext(query_id, query.tenant_id, "complete", tuple(items), {
                "query_id": query_id, "retrieval_method": "exact_identifier", "score_type": "exact_match",
                "candidate_count": len(exact), "returned_count": len(items), "reranked": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "temporal_filters": {"valid_at": query.valid_at, "known_as_of": query.known_as_of},
            })
        if not query.text.strip():
            return KnowledgeContext(query_id, query.tenant_id, "unavailable", (), {
                "query_id": query_id, "retrieval_method": "exact_identifier", "candidate_count": 0,
                "returned_count": 0, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            })
        bm25 = self._bm25(eligible, query.text, max(query.top_k * 3, 24))
        dense: list[tuple[SearchDocument, float]] = []
        dense_error: str | None = None
        if self.embedder is not None and eligible:
            try:
                dense = self._dense(eligible, query.text, max(query.top_k * 3, 24))
            except Exception as exc:  # provider errors are surfaced in metadata
                dense_error = getattr(exc, "code", type(exc).__name__)
        fused = _rrf([bm25, dense])
        by_id = {document.document_id: document for document in eligible}
        candidates = [Candidate(doc_id, by_id[doc_id].text, by_id[doc_id].metadata, rank) for rank, (doc_id, _) in enumerate(fused)]
        reranked = rerank_with_fallback(query.text, candidates, self.reranker, top_n=query.top_k, fallback_enabled=True)
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
            "model_version": getattr(self.embedder, "model", "deterministic-or-none"),
            "reranker_model": reranked.model, "reranker_status": reranked.status,
            "score_type": "reranker_score" if self.reranker and reranked.status == "complete" else "rrf_score",
            "candidate_count": len(candidates), "returned_count": len(items),
            "temporal_filters": {"valid_at": query.valid_at, "known_as_of": query.known_as_of},
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "embedding_error": dense_error, "reranker_error": reranked.error_code,
        }
        return KnowledgeContext(query_id, query.tenant_id, status, tuple(items), metadata)

    @staticmethod
    def _eligible(document: SearchDocument, query: KnowledgeQuery) -> bool:
        if document.tenant_id != query.tenant_id:
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
    def _exact(documents: Sequence[SearchDocument], identifiers: Sequence[str]) -> list[SearchDocument]:
        wanted = {value.casefold() for value in identifiers}
        return [document for document in documents if wanted & {value.casefold() for value in (document.document_id, *document.identifiers)}]

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

    def _dense(self, documents: Sequence[SearchDocument], query: str, limit: int) -> list[tuple[SearchDocument, float]]:
        vectors = self.embedder.embed([query, *[document.text for document in documents]])
        if len(vectors) != len(documents) + 1:
            raise ValueError("embedding provider returned wrong vector count")
        query_vector = vectors[0]
        scores = [(document, _cosine(query_vector, vector)) for document, vector in zip(documents, vectors[1:])]
        scores.sort(key=lambda item: (-item[1], item[0].document_id))
        return scores[:limit]

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
