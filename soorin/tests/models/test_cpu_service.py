import unittest
from unittest.mock import patch
from soorin.services.cpu_models import Engine, texts, serve_all, load_role, InferenceGate, BoundedHTTPServer


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

    def test_queue_configuration_reports_effective_capacity(self):
        with patch.dict('os.environ', {'SOORIN_MODEL_QUEUE_CAPACITY': '0'}):
            gate = InferenceGate.configured()
            self.assertEqual(gate.queue_capacity, 0)
            self.assertTrue(gate.acquire())
            self.assertFalse(gate.acquire())
            gate.release()
        with patch.dict('os.environ', {'SOORIN_MODEL_QUEUE_CAPACITY': '8'}):
            with self.assertRaises(ValueError):
                InferenceGate.configured()

    def test_capacity_overflow_does_not_wait(self):
        gate = InferenceGate(capacity=1, wait_seconds=10)
        self.assertTrue(gate.acquire())
        self.assertFalse(gate.acquire())
        gate.release()

    def test_interrupted_wait_restores_capacity(self):
        gate = InferenceGate(capacity=1)
        with patch.object(gate.active, 'acquire', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): gate.acquire()
        self.assertTrue(gate.acquire())
        gate.release()

    def test_invalid_requests_are_rejected_before_model_loading(self):
        with patch.object(Engine, 'load', side_effect=AssertionError('weights forbidden')):
            for role, path, body in [('ner', '/ner', {'text':['a','b']}),
                ('reranker','/rerank',{'query':['a','b'],'texts':['a']}),
                ('embedding','/v1/embeddings',{'input':['x']*17})]:
                with self.assertRaises(ValueError): Engine(role,'missing').infer(path,body)

    def test_request_thread_overflow_is_bounded_without_starting_server(self):
        import threading
        from unittest.mock import Mock
        server = object.__new__(BoundedHTTPServer)
        server.handlers = threading.BoundedSemaphore(1)
        self.assertTrue(server.handlers.acquire())
        request = Mock()
        server.shutdown_request = Mock()
        server.process_request(request, ('127.0.0.1', 1))
        self.assertIn(b'429', request.sendall.call_args.args[0])
        server.shutdown_request.assert_called_once_with(request)
        server.handlers.release()

    def test_invalid_model_types_are_validation_failures_without_loading(self):
        with patch.object(Engine,'load',side_effect=AssertionError('weights forbidden')):
            for value in [[],{},None,True,123]:
                with self.subTest(value=value),self.assertRaises(ValueError):
                    Engine('embedding','missing').infer('/v1/embeddings',{'model':value,'input':['synthetic']})

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


    def test_independent_admission_and_queue_failure_reasons(self):
        embedding = InferenceGate(capacity=1)
        reranker = InferenceGate(capacity=2, wait_seconds=0.001)
        self.assertIsNone(embedding.admit())
        self.assertIsNone(reranker.admit())
        self.assertEqual(embedding.admit(), "queue_full")
        self.assertEqual(reranker.admit(), "queue_timeout")
        self.assertEqual(reranker.snapshot(), {"active_requests": 1, "waiting_requests": 0, "queue_rejections": 1})
        embedding.release()
        self.assertEqual(reranker.snapshot()["active_requests"], 1)
        reranker.release()

    def test_role_startup_verifies_only_the_requested_pinned_cache(self):
        with patch("soorin.services.artifacts.verify", return_value={"status": "PASS"}) as verify, \
             patch.object(Engine, "load", autospec=True) as load:
            engine = load_role("reranker", "/models/reranker")
        verify.assert_called_once_with("reranker", "/models/reranker", hashes=True)
        load.assert_called_once_with(engine)
        self.assertEqual(engine.role, "reranker")
        self.assertIn("@953dc", engine.name)
