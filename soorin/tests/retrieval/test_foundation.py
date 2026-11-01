from __future__ import annotations

import unittest

from soorin.contracts import KnowledgeQuery
from soorin.models import DeterministicFakeEmbeddingClient
from soorin.retrieval import DeterministicReranker, RetrievalFoundation, SearchDocument


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


if __name__ == "__main__":
    unittest.main()
