from dataclasses import replace
import unittest
from soorin.e2e.native_validation import acceptance_events, assert_receipt_graph

class NativeAcceptanceTests(unittest.TestCase):
    def test_requires_exact_relation_multiset_and_evidence(self):
        event = acceptance_events()[0][1]
        diagnostic = {'status':'bound', 'document':{'status':'ready','graph_status':'done'},
            'relations':[{'expected_relation_key':r.relation_type.lower(), 'binding':{
                'type_binding_status':'bound','phrase_binding_status':'bound','evidence_link_status':True}}
                for r in event.relations]}
        self.assertEqual(assert_receipt_graph(event, diagnostic), len(event.relations))
        diagnostic['relations'][0]['binding']['evidence_link_status'] = False
        with self.assertRaisesRegex(AssertionError,'evidence_missing'):
            assert_receipt_graph(event, diagnostic)
        diagnostic['relations'] = []
        with self.assertRaisesRegex(AssertionError,'set_mismatch'):
            assert_receipt_graph(event, diagnostic)
        diagnostic['status'] = 'submitted'
        with self.assertRaisesRegex(AssertionError,'not_bound'):
            assert_receipt_graph(event, diagnostic)
