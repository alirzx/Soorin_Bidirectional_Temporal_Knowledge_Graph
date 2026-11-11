from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch
import urllib.error

from soorin.models.configuration import RerankerConfig
from soorin.retrieval.reranker import Candidate, DeterministicReranker, HttpReranker, RerankerError, _post_json, rerank_with_fallback


CANDIDATES = [
    Candidate("a", "ordinary login", base_rank=0),
    Candidate("b", "password spray authentication failures", base_rank=1),
    Candidate("c", "suspicious process", base_rank=2),
]


class RerankerTests(unittest.TestCase):
    def test_tei_scores_every_candidate_before_selecting_top_n(self):
        provider = HttpReranker(
            RerankerConfig(True, "tei", "http://rerank", "m", endpoint_trust="local_trusted"),
            lambda *args: [{"index": 0, "score": 0.1}, {"index": 1, "score": 0.9}, {"index": 2, "score": 0.3}],
        )
        self.assertEqual(provider.rerank("q", CANDIDATES, 1), [("b", 0.9)])

    def test_disabled_preserves_original_order(self):
        out = rerank_with_fallback("password spray", CANDIDATES, None, top_n=3)
        self.assertEqual([row.candidate.candidate_id for row in out.results], ["a", "b", "c"])
        self.assertEqual(out.status, "disabled")

    def test_deterministic_reranking(self):
        out = rerank_with_fallback("password spray", CANDIDATES, DeterministicReranker(), top_n=3)
        self.assertEqual(out.results[0].candidate.candidate_id, "b")
        self.assertEqual(out.status, "complete")

    def test_cohere_and_tei_provider_adapters(self):
        cfg = RerankerConfig(True, "cohere_v2", "http://rerank", "m", top_n=2, endpoint_trust="local_trusted")
        provider = HttpReranker(cfg, lambda *args: {"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]})
        self.assertEqual(provider.rerank("q", CANDIDATES, 2)[0][0], "b")
        tei = HttpReranker(RerankerConfig(True, "tei", "http://rerank", "m", top_n=2, endpoint_trust="local_trusted"), lambda *args: [{"index":2,"score":0.8},{"index":1,"score":0.7},{"index":0,"score":0.1}])
        self.assertEqual(tei.rerank("q", CANDIDATES, 2)[0][0], "c")

    def test_timeout_malformed_missing_and_incorrect_outputs_fallback(self):
        cases = [
            lambda *args: (_ for _ in ()).throw(TimeoutError("slow")),
            lambda *args: {"wrong": []},
            lambda *args: {"results":[{"index":0,"relevance_score":0.1}]},
            lambda *args: {"results":[{"index":0,"relevance_score":"bad"},{"index":1,"relevance_score":0.1}]},
        ]
        for transport in cases:
            provider = HttpReranker(RerankerConfig(True, "cohere_v2", "http://rerank", "m", endpoint_trust="local_trusted"), transport)
            out = rerank_with_fallback("q", CANDIDATES, provider, top_n=2)
            self.assertEqual(out.status, "fallback")
            self.assertEqual([row.candidate.candidate_id for row in out.results], ["a", "b"])

    def test_duplicate_candidates_are_deduplicated_and_equal_scores_stable(self):
        rows = [Candidate("b", "x", base_rank=1), Candidate("a", "x", base_rank=0), Candidate("a", "duplicate", base_rank=9)]
        class Equal:
            provider = "fake"
            model = "equal"
            def rerank(self, query, candidates, top_n):
                return [(candidate.candidate_id, 0.5) for candidate in candidates[:top_n]]
        out = rerank_with_fallback("q", rows, Equal(), top_n=2)
        self.assertEqual(out.duplicate_count, 1)
        self.assertEqual([row.candidate.candidate_id for row in out.results], ["b", "a"])

    def test_empty_and_large_candidate_sets(self):
        self.assertEqual(rerank_with_fallback("q", [], DeterministicReranker(), top_n=10).results, ())
        large = [Candidate(str(index), f"document {index}", base_rank=index) for index in range(500)]
        out = rerank_with_fallback("document 499", large, DeterministicReranker(), top_n=10)
        self.assertEqual(len(out.results), 10)
        self.assertEqual(out.results[0].candidate.candidate_id, "499")

    def test_no_fallback_raises(self):
        provider = HttpReranker(RerankerConfig(True, "cohere_v2", "http://rerank", "m", endpoint_trust="local_trusted"), lambda *args: {"results":[]})
        with self.assertRaises(RerankerError):
            rerank_with_fallback("q", CANDIDATES, provider, top_n=2, fallback_enabled=False)

    def test_sensitive_external_rerank_is_blocked_before_transport(self):
        calls = []
        provider = HttpReranker(
            RerankerConfig(True, "cohere_v2", "http://rerank", "m", fallback_enabled=False),
            lambda *args: calls.append(args) or {},
        )
        with self.assertRaisesRegex(RerankerError, "privacy_blocked"):
            rerank_with_fallback(
                "SOC alert", CANDIDATES, provider, top_n=2, fallback_enabled=False,
            )
        self.assertEqual(calls, [])

    def test_authentication_failure_does_not_echo_provider_body(self):
        error = urllib.error.HTTPError(
            "http://rerank", 403, "forbidden", {}, BytesIO(b"echoed candidate secret"),
        )
        with patch("soorin.retrieval.reranker.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RerankerError) as caught:
                _post_json("http://rerank", {}, {"query": "secret"}, 1)
        self.assertEqual(caught.exception.code, "authentication_failed")
        self.assertNotIn("echoed candidate secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
