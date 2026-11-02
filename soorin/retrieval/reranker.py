"""Optional second-stage reranking with provider-specific adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request

from soorin.models.configuration import RerankerConfig
from soorin.privacy import OutboundDataPolicy, OutboundPolicyError


class RerankerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    base_rank: int = 0


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: Candidate
    score: float | None
    reranked_position: int


@dataclass(frozen=True, slots=True)
class RerankOutcome:
    results: tuple[ScoredCandidate, ...]
    status: str
    provider: str
    model: str | None
    latency_ms: float
    duplicate_count: int = 0
    error_code: str | None = None


class DeterministicReranker:
    provider = "deterministic_fake"
    model = "token-overlap-v1"

    def rerank(self, query: str, candidates: Sequence[Candidate], top_n: int) -> list[tuple[str, float]]:
        query_tokens = set(_tokens(query))
        scored = []
        for candidate in candidates:
            tokens = set(_tokens(candidate.text))
            union = query_tokens | tokens
            score = len(query_tokens & tokens) / len(union) if union else 0.0
            scored.append((candidate.candidate_id, score, candidate.base_rank))
        scored.sort(key=lambda item: (-item[1], item[2], item[0]))
        return [(item[0], item[1]) for item in scored[:top_n]]


PostJson = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Any]


@dataclass(slots=True)
class HttpReranker:
    config: RerankerConfig
    post_json: PostJson | None = None
    provider: str = field(init=False)
    model: str | None = field(init=False)
    privacy_policy: OutboundDataPolicy | None = None

    def __post_init__(self) -> None:
        self.config.validate()
        self.provider = self.config.provider
        self.model = self.config.model
        if self.privacy_policy is None:
            self.privacy_policy = OutboundDataPolicy(
                self.config.privacy_mode, self.config.endpoint_trust, self.config.test_mode,
            )

    def rerank(self, query: str, candidates: Sequence[Candidate], top_n: int) -> list[tuple[str, float]]:
        if not self.config.enabled:
            raise RerankerError("disabled", "reranker is disabled")
        if not candidates:
            return []
        documents = [candidate.text[:self.config.max_document_chars] for candidate in candidates]
        try:
            assert self.privacy_policy is not None
            self.privacy_policy.require_allowed(
                [query, *documents], purpose="reranker", synthetic=self.config.synthetic_mode,
            )
        except OutboundPolicyError as exc:
            raise RerankerError(exc.code, str(exc)) from exc
        if self.config.provider in {"cohere_v2", "jina_v1"}:
            path = "/v2/rerank" if self.config.provider == "cohere_v2" else "/v1/rerank"
            body = {"model": self.config.model, "query": query, "documents": documents, "top_n": top_n}
            response = (self.post_json or _post_json)(f"{self.config.base_url}{path}", _headers(self.config.api_key), body, self.config.timeout_seconds)
            rows = response.get("results") if isinstance(response, Mapping) else None
            if not isinstance(rows, list):
                raise RerankerError("malformed_response", "results must be an array")
            parsed = [(row.get("index"), row.get("relevance_score", row.get("score"))) for row in rows if isinstance(row, Mapping)]
        elif self.config.provider == "tei":
            body = {"query": query, "texts": documents, "truncate": True, "raw_scores": False}
            response = (self.post_json or _post_json)(f"{self.config.base_url}/rerank", _headers(self.config.api_key), body, self.config.timeout_seconds)
            rows = response if isinstance(response, list) else response.get("results") if isinstance(response, Mapping) else None
            if not isinstance(rows, list):
                raise RerankerError("malformed_response", "TEI response must be an array")
            parsed = [(row.get("index"), row.get("score")) for row in rows if isinstance(row, Mapping)]
        else:
            raise RerankerError("unsupported_provider", self.config.provider)
        expected = min(top_n, len(candidates))
        if len(parsed) != expected:
            raise RerankerError("missing_candidate", f"expected {expected} scored candidates, received {len(parsed)}")
        seen: set[int] = set()
        result: list[tuple[str, float]] = []
        for index, score in parsed:
            if not isinstance(index, int) or not 0 <= index < len(candidates) or index in seen:
                raise RerankerError("invalid_index", f"invalid or duplicate candidate index {index!r}")
            if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise RerankerError("invalid_score", f"invalid score {score!r}")
            seen.add(index)
            result.append((candidates[index].candidate_id, float(score)))
        return result


def rerank_with_fallback(
    query: str, candidates: Sequence[Candidate], provider: Any | None,
    *, top_n: int, fallback_enabled: bool = True,
) -> RerankOutcome:
    started = time.perf_counter()
    unique: list[Candidate] = []
    seen: set[str] = set()
    duplicates = 0
    for rank, candidate in enumerate(candidates):
        if candidate.candidate_id in seen:
            duplicates += 1
            continue
        seen.add(candidate.candidate_id)
        unique.append(Candidate(candidate.candidate_id, candidate.text, candidate.metadata, candidate.base_rank or rank))
    if not unique:
        return RerankOutcome((), "complete", "disabled" if provider is None else provider.provider, getattr(provider, "model", None), 0.0, duplicates)
    if provider is None:
        rows = tuple(ScoredCandidate(candidate, None, index) for index, candidate in enumerate(unique[:top_n]))
        return RerankOutcome(rows, "disabled", "disabled", None, (time.perf_counter() - started) * 1000, duplicates)
    try:
        scores = provider.rerank(query, unique, min(top_n, len(unique)))
        by_id = {candidate.candidate_id: candidate for candidate in unique}
        base = {candidate.candidate_id: index for index, candidate in enumerate(unique)}
        ordered = sorted(scores, key=lambda item: (-item[1], base[item[0]], item[0]))
        rows = tuple(ScoredCandidate(by_id[candidate_id], score, index) for index, (candidate_id, score) in enumerate(ordered))
        return RerankOutcome(rows, "complete", provider.provider, getattr(provider, "model", None), (time.perf_counter() - started) * 1000, duplicates)
    except (RerankerError, TimeoutError, urllib.error.URLError) as exc:
        code = exc.code if isinstance(exc, RerankerError) else "timeout" if isinstance(exc, TimeoutError) else "unavailable"
        if not fallback_enabled:
            raise RerankerError(code, "reranker request failed") from exc
        rows = tuple(ScoredCandidate(candidate, None, index) for index, candidate in enumerate(unique[:top_n]))
        return RerankOutcome(rows, "fallback", provider.provider, getattr(provider, "model", None), (time.perf_counter() - started) * 1000, duplicates, code)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w.-]+", text.casefold(), flags=re.UNICODE)


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _post_json(url: str, headers: Mapping[str, str], body: Mapping[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(url, json.dumps(body).encode("utf-8"), headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = "rate_limited" if exc.code == 429 else "authentication_failed" if exc.code in {401, 403} else "provider_error"
        raise RerankerError(code, f"HTTP {exc.code}") from exc
