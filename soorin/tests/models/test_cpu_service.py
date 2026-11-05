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
