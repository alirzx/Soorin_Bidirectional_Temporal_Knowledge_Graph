import json
from pathlib import Path
import unittest
from soorin.contracts import KnowledgeQuery
from soorin.retrieval import RetrievalFoundation, SearchDocument


class RetrievalAcceptanceFixtureTests(unittest.TestCase):
    def test_versioned_bilingual_identity_time_and_evidence_contracts(self):
        fixture = json.loads((Path(__file__).parents[1]/'fixtures/soc_retrieval_acceptance_v1.json').read_text())
        self.assertTrue(fixture['synthetic'])
        tenants = {row['document_id']:row['tenant_id'] for row in fixture['documents']}
        engine = RetrievalFoundation([SearchDocument(**row) for row in fixture['documents']])
        for row in fixture['queries']:
            with self.subTest(case=row['name']):
                query = KnowledgeQuery(**row['query'])
                result = engine.search(query)
                self.assertEqual([r['document_id'] for r in result.items],row['expected'])
                self.assertTrue(all(tenants[r['document_id']]==query.tenant_id for r in result.items))
                self.assertTrue(all(r['evidence_references'] for r in result.items))
                if not row['expected']:
                    self.assertEqual(result.status,'unavailable')

    def test_half_open_knowledge_boundary_uses_normalized_timestamps(self):
        old = SearchDocument('old','blue','synthetic',('ID',),('e',),
            recorded_at='2026-01-01T00:00:00Z',invalidated_at='2026-03-01T03:30:00+03:30')
        new = SearchDocument('new','blue','synthetic',('ID',),('e2',),recorded_at='2026-03-01T00:00:00Z')
        result = RetrievalFoundation([old,new]).search(KnowledgeQuery('blue','',exact_identifiers=('ID',),
            known_as_of='2026-03-01T00:00:00Z'))
        self.assertEqual([r['document_id'] for r in result.items],['new'])
