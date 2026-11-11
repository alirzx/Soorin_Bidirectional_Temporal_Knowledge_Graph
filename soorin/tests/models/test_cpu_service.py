import unittest
from soorin.services.cpu_models import Engine, texts


class Scores:
    def predict(self, pairs, **kwargs):
        self.pairs = pairs
        return self

    def tolist(self):
        return [0.2, 0.9]


class CpuServiceTests(unittest.TestCase):
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
