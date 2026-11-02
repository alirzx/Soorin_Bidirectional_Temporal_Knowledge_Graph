from __future__ import annotations

import unittest
from types import SimpleNamespace

from soorin.contracts import KnowledgeQuery
from soorin.models import DeterministicFakeEmbeddingClient
from soorin.retrieval import DeterministicReranker, RetrievalFoundation, SearchDocument
from soorin.retrieval.reranker import RerankerError


DOCS = (
    SearchDocument("a", "tenant-a", "password spray from 192.0.2.1", ("ALERT-1",), ("evidence-1",), valid_from="2026-01-01T00:00:00Z", recorded_at="2026-01-02T00:00:00Z"),
    SearchDocument("b", "tenant-a", "suspicious powershell process", ("ALERT-2",), ("evidence-2",), valid_from="2026-02-01T00:00:00Z", recorded_at="2026-02-02T00:00:00Z"),
    SearchDocument("secret", "tenant-b", "password spray private", ("SECRET",), ()),
)


class RetrievalTests(unittest.TestCase):
    def test_exact_identifier_bypasses_reranking(self):
        engine = RetrievalFoundation(DOCS, DeterministicFakeEmbeddingClient(), DeterministicReranker())
        out = engine.search(KnowledgeQuery("tenant-a", "ignored", exact_identifiers=("ALERT-2",)))
        self.assertEqual(out.items[0]["document_id"], "b")
        self.assertEqual(out.retrieval_metadata["retrieval_method"], "exact_identifier")
        self.assertFalse(out.retrieval_metadata["reranked"])

    def test_tenant_isolation(self):
        out = RetrievalFoundation(DOCS).search(KnowledgeQuery("tenant-a", "password spray"))
        self.assertEqual([item["document_id"] for item in out.items], ["a"])
        self.assertNotIn("secret", {item["document_id"] for item in out.items})

    def test_world_and_knowledge_time_filters(self):
        engine = RetrievalFoundation(DOCS)
        before_valid = engine.search(KnowledgeQuery("tenant-a", "password", valid_at="2025-12-01T00:00:00Z"))
        self.assertEqual(before_valid.items, ())
        before_known = engine.search(KnowledgeQuery("tenant-a", "password", known_as_of="2026-01-01T12:00:00Z"))
        self.assertEqual(before_known.items, ())

    def test_bm25_dense_rrf_reranker_preserves_provenance(self):
        engine = RetrievalFoundation(DOCS, DeterministicFakeEmbeddingClient(64), DeterministicReranker())
        out = engine.search(KnowledgeQuery("tenant-a", "powershell process", top_k=2))
        self.assertEqual(out.items[0]["document_id"], "b")
        self.assertEqual(out.items[0]["evidence_references"], ["evidence-2"])
        self.assertEqual(out.status, "complete")

    def test_embedding_failure_falls_back_observably(self):
        class Broken:
            model = "broken"
            def embed(self, texts):
                raise TimeoutError("slow")
        out = RetrievalFoundation(DOCS, Broken()).search(KnowledgeQuery("tenant-a", "password spray"))
        self.assertEqual(out.status, "fallback")
        self.assertEqual(out.retrieval_metadata["embedding_error"], "TimeoutError")
        self.assertEqual(out.items[0]["document_id"], "a")

    def test_empty_lookup_is_unavailable(self):
        out = RetrievalFoundation(DOCS).search(KnowledgeQuery("tenant-a", "ignored", exact_identifiers=("MISSING",)))
        self.assertEqual(out.status, "unavailable")

    def test_type_aware_exact_ids_do_not_cross_entity_kinds(self):
        documents = (
            SearchDocument(
                "host-doc", "tenant-a", "host", ("SHARED-1",), (),
                metadata={"entity_type": "Host"}, typed_identifiers=(("Host", "SHARED-1"),),
            ),
            SearchDocument(
                "alert-doc", "tenant-a", "alert", ("SHARED-1",), (),
                metadata={"entity_type": "SecurityAlert"},
                typed_identifiers=(("SecurityAlert", "SHARED-1"),),
            ),
        )
        out = RetrievalFoundation(documents).search(KnowledgeQuery(
            "tenant-a", "ignored", exact_identifiers=("SHARED-1",), entity_types=("Host",),
        ))
        self.assertEqual([item["document_id"] for item in out.items], ["host-doc"])

    def test_dense_embedding_is_bounded_and_document_vectors_are_cached(self):
        class TrackingEmbedder:
            provider = "tracking"
            model = "tracking-v1"

            def __init__(self):
                self.calls = []

            def embed(self, texts):
                self.calls.append(tuple(texts))
                return [[1.0, float(index + 1)] for index, _ in enumerate(texts)]

        documents = tuple(
            SearchDocument(f"doc-{index:03d}", "tenant-a", f"document {index} needle")
            for index in range(200)
        )
        embedder = TrackingEmbedder()
        engine = RetrievalFoundation(
            documents, embedder, candidate_limit=10, dense_candidate_limit=5,
            vector_cache_capacity=5,
        )
        first = engine.search(KnowledgeQuery("tenant-a", "needle", top_k=3))
        second = engine.search(KnowledgeQuery("tenant-a", "needle", top_k=3))
        self.assertEqual([len(call) for call in embedder.calls], [6, 1])
        self.assertEqual(first.retrieval_metadata["dense_input_count"], 5)
        self.assertEqual(first.retrieval_metadata["candidate_limit"], 10)
        self.assertEqual(second.retrieval_metadata["vector_cache"]["hits"], 5)

    def test_precomputed_vectors_avoid_document_embedding_and_cache_is_bounded(self):
        class TrackingEmbedder:
            provider = "tracking"
            model = "tracking-v1"

            def __init__(self):
                self.calls = []

            def embed(self, texts):
                self.calls.append(tuple(texts))
                return [[1.0, 1.0] for _ in texts]

        documents = (
            SearchDocument("precomputed", "tenant-a", "needle one", embedding=(1.0, 1.0)),
            SearchDocument("uncached-1", "tenant-a", "needle two"),
            SearchDocument("uncached-2", "tenant-a", "needle three"),
            SearchDocument("uncached-3", "tenant-a", "needle four"),
        )
        embedder = TrackingEmbedder()
        engine = RetrievalFoundation(
            documents, embedder, candidate_limit=4, dense_candidate_limit=4,
            vector_cache_capacity=2,
        )
        out = engine.search(KnowledgeQuery("tenant-a", "needle", top_k=2))
        self.assertNotIn("needle one", embedder.calls[0])
        self.assertEqual(len(embedder.calls[0]), 4)  # query + three missing document vectors
        self.assertEqual(out.retrieval_metadata["vector_cache"]["size"], 2)
        self.assertEqual(out.retrieval_metadata["vector_cache"]["evictions"], 1)

    def test_reranker_fallback_policy_is_read_from_provider_configuration(self):
        class BrokenReranker:
            provider = "broken"
            model = "broken-v1"
            config = SimpleNamespace(fallback_enabled=False)

            def rerank(self, query, candidates, top_n):
                raise RerankerError("unavailable", "synthetic failure")

        engine = RetrievalFoundation(DOCS, reranker=BrokenReranker())
        with self.assertRaisesRegex(RerankerError, "unavailable"):
            engine.search(KnowledgeQuery("tenant-a", "password spray"))


if __name__ == "__main__":
    unittest.main()
