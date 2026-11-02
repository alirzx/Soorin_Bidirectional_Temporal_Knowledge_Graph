from __future__ import annotations
import unittest
from soorin.extraction import NerProposal, enrich_entities
from soorin.extraction.cpu_cyber_ner import (
    CpuCyberNer, DisabledNer, DEFAULT_NER_MODEL, DEFAULT_NER_REVISION,
)

class CpuCyberNerTests(unittest.TestCase):
    def test_optional_default_and_no_eager_inference(self):
        model = CpuCyberNer()
        self.assertEqual(model.model, DEFAULT_NER_MODEL)
        self.assertEqual(model.model_revision, DEFAULT_NER_REVISION)
        self.assertEqual(len(DEFAULT_NER_REVISION), 40)
        self.assertIsNone(model.classifier)
        self.assertEqual(DisabledNer().extract("test"), [])

    def test_cpu_pipeline_injectable_and_filters_non_authoritative(self):
        captured = []
        def fake(text, **kwargs):
            captured.append((text, kwargs))
            return [
                {"entity_group": "MALWARE", "word": "ExampleThreat", "score": 0.91},
                {"entity_group": "SYSTEM", "word": "testhost", "score": 0.86},
                {"entity_group": "ORGANIZATION", "word": "Example Co", "score": 0.95},
                {"entity_group": "O", "word": "ignored", "score": 0.99},
            ]
        m = CpuCyberNer(classifier=fake)
        result = m.extract("A synthetic security report")
        self.assertEqual([(x.entity_type, x.value) for x in result],
                         [("Indicator", "ExampleThreat")])
        self.assertEqual(result[0].source_label, "MALWARE")
        self.assertTrue(result[0].review_required)
        self.assertEqual(captured[0][1]["truncation"], True)

    def test_input_limit_and_bad_configuration(self):
        with self.assertRaises(ValueError):
            CpuCyberNer(min_score=1.5)
        captured = []
        m = CpuCyberNer(max_chars=8, classifier=lambda text, **k: captured.append(text) or [])
        m.extract("a longer text")
        self.assertEqual(captured, ["a longer"])
        self.assertIsNotNone(m.classifier)

    def test_duplicate_keeps_highest_score_and_malformed_output_fails_closed(self):
        rows = [
            {"entity_group": "INDICATOR", "word": "evil.example", "score": 0.81},
            {"entity_group": "B-INDICATOR", "word": "EVIL.EXAMPLE", "score": 0.97},
        ]
        result = CpuCyberNer(classifier=lambda text, **kwargs: rows).extract("synthetic")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].score, 0.97)
        with self.assertRaisesRegex(ValueError, "invalid result"):
            CpuCyberNer(classifier=lambda text, **kwargs: {"not": "a list"}).extract("synthetic")
        with self.assertRaisesRegex(ValueError, "not an object"):
            CpuCyberNer(classifier=lambda text, **kwargs: ["bad"]).extract("synthetic")
        with self.assertRaisesRegex(ValueError, "invalid score"):
            CpuCyberNer(classifier=lambda text, **kwargs: [
                {"entity_group": "INDICATOR", "word": "x", "score": True},
            ]).extract("synthetic")

    def test_unsupported_script_does_not_initialize_model(self):
        called = []
        model = CpuCyberNer(classifier=lambda text, **kwargs: called.append(text) or [])
        self.assertEqual(model.extract("گزارش امنیتی آزمایشی"), [])
        self.assertEqual(called, [])

    def test_enrichment_keeps_deterministic_results_authoritative(self):
        class FakeProvider:
            def __init__(self):
                self.texts = []

            def extract(self, text):
                self.texts.append(text)
                return [
                    NerProposal("Host", "dc01.example", 0.99, "fake@1", "SYSTEM"),
                    NerProposal("Indicator", "ExampleThreat", 0.91, "fake@1", "MALWARE"),
                ]

        provider = FakeProvider()
        batch = enrich_entities(
            {"host": "dc01.example", "message": "ExampleThreat was observed", "search": "index=security"},
            source_record_reference="synthetic-1", ner=provider,
        )
        self.assertTrue(any(row.entity_type == "Host" for row in batch.deterministic.entities))
        self.assertEqual([(row.entity_type, row.value) for row in batch.ner_proposals],
                         [("Indicator", "ExampleThreat")])
        self.assertEqual(provider.texts, ["ExampleThreat was observed"])
        self.assertEqual(batch.errors, ())

    def test_enrichment_contains_provider_failure_without_losing_deterministic_data(self):
        class BrokenProvider:
            def extract(self, text):
                raise ValueError("provider echoed sensitive text")

        batch = enrich_entities(
            {"host": "dc01.example", "message": "synthetic text"},
            source_record_reference="synthetic-2", ner=BrokenProvider(),
        )
        self.assertTrue(batch.deterministic.entities)
        self.assertEqual(batch.ner_proposals, ())
        self.assertEqual(batch.errors, ("ner_provider_error:ValueError",))

if __name__ == "__main__":
    unittest.main()
