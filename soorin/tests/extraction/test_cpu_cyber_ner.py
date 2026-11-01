from __future__ import annotations
import unittest
from soorin.extraction.cpu_cyber_ner import CpuCyberNer, DisabledNer, DEFAULT_NER_MODEL

class CpuCyberNerTests(unittest.TestCase):
    def test_optional_default_and_no_eager_inference(self):
        model = CpuCyberNer()
        self.assertEqual(model.model, DEFAULT_NER_MODEL)
        self.assertIsNone(model.classifier)
        self.assertEqual(DisabledNer().extract("test"), [])

    def test_cpu_pipeline_injectable_and_filters_non_authoritative(self):
        captured = []
        def fake(text, **kwargs):
            captured.append((text, kwargs))
            return [
                {"entity_group": "MALWARE", "word": "ExampleThreat", "score": 0.91},
                {"entity_group": "SYSTEM", "word": "testhost", "score": 0.86},
                {"entity_group": "ORGANIZATION", "word": "Example Co", "score": 0.70},
                {"entity_group": "O", "word": "ignored", "score": 0.99},
            ]
        m = CpuCyberNer(classifier=fake)
        result = m.extract("A synthetic security report")
        self.assertEqual([(x.entity_type, x.value) for x in result],
                         [("Indicator", "ExampleThreat"), ("Host", "testhost")])
        self.assertEqual(captured[0][1]["truncation"], True)

    def test_input_limit_and_bad_configuration(self):
        with self.assertRaises(ValueError):
            CpuCyberNer(min_score=1.5)
        m = CpuCyberNer(max_chars=8, classifier=lambda text, **k: [])
        m.extract("a longer text")
        self.assertIsNotNone(m.classifier)

if __name__ == "__main__":
    unittest.main()
