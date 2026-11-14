import unittest
from unittest.mock import patch
from soorin.services.cpu_models import Engine, texts, serve_all, InferenceGate


class Scores:
    def predict(self, pairs, **kwargs):
        self.pairs = pairs
        return self

    def tolist(self):
        return [0.2, 0.9]


class CpuServiceTests(unittest.TestCase):
    def test_backpressure_wait_is_bounded_and_timeout_releases_capacity(self):
        gate = InferenceGate(capacity=2, wait_seconds=0.001)
        self.assertTrue(gate.acquire())
        self.assertFalse(gate.acquire())
        gate.release()
        self.assertTrue(gate.acquire())
        gate.release()

    def test_capacity_overflow_does_not_wait(self):
        gate = InferenceGate(capacity=1, wait_seconds=10)
        self.assertTrue(gate.acquire())
        self.assertFalse(gate.acquire())
        gate.release()

    def test_reranker_preserves_all_indexes_and_model_revision(self):
        engine = Engine("reranker", "/missing", model=Scores())
        rows = engine.infer("/rerank", {"query": "q", "texts": ["one", "two"]})
        self.assertEqual(rows, [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.2}])
        self.assertEqual(engine.calls, 1)
        self.assertIn("@953dc", engine.name)

    def test_batch_and_model_confusion_rejected_without_loading_weights(self):
        for value in ([], ["x"] * 17, [""], ["x" * 16001]):
            with self.assertRaises(ValueError):
                texts(value)
        with self.assertRaises(ValueError):
            Engine("embedding", "/missing", model=object()).infer("/v1/embeddings", {"model": "wrong"})


    def test_ner_metadata_uses_pinned_identity_not_local_cache_path(self):
        from soorin.extraction.ner import NerProposal
        class Ner:
            def extract(self, text):
                return [NerProposal('Indicator', 'example', .9, '/private/cache/snapshot', 'MALWARE')]
        engine = Engine('ner', '/missing', model=Ner())
        result = engine.infer('/ner', {'text':'synthetic'})
        self.assertEqual(result['proposals'][0]['model_version'], engine.name)
        self.assertTrue(result['proposals'][0]['review_required'])
        self.assertEqual(result['proposals'][0]['source_label'], 'MALWARE')

    def test_unified_model_service_maps_three_ports_and_isolates_caches(self):
        calls = []
        loads = []
        def verify(role, cache, *, hashes=False):
            calls.append(("verify", role, cache, hashes))
            return {"status": "PASS"}
        def load(engine):
            loads.append((engine.role, engine.cache))
            engine.model = object()
        def serve(engine, host, port, gate=None):
            calls.append(("serve", engine.role, host, port, gate))
        with patch("soorin.services.artifacts.verify", side_effect=verify), \
             patch.object(Engine, "load", autospec=True, side_effect=load), \
             patch("soorin.services.cpu_models.serve", side_effect=serve):
            serve_all("/models", "127.0.0.1")
        self.assertEqual([v[0] for v in loads], ["embedding", "reranker", "ner"])
        self.assertEqual([v[1] for v in loads],
                         ["/models/embedding", "/models/reranker", "/models/ner"])
        serving = [v for v in calls if v[0] == "serve"]
        self.assertEqual({(v[1], v[3]) for v in serving},
                         {("embedding", 8080), ("reranker", 8081), ("ner", 8082)})
        self.assertEqual(len({id(v[4]) for v in serving}), 1)
        self.assertTrue(all(v[-1] is True for v in calls if v[0] == "verify"))

    def test_unified_startup_fails_closed_on_missing_model(self):
        def verify(role, cache, *, hashes=False):
            return {"status": "PASS" if role == "embedding"
                    else "MODEL_ARTIFACT_DOWNLOAD_INCOMPLETE"}
        with patch("soorin.services.artifacts.verify", side_effect=verify), \
             patch.object(Engine, "load", autospec=True, return_value=None), \
             patch("soorin.services.cpu_models.serve") as serve:
            with self.assertRaisesRegex(RuntimeError, "reranker.*verification failed"):
                serve_all("/models", "127.0.0.1")
            serve.assert_not_called()
