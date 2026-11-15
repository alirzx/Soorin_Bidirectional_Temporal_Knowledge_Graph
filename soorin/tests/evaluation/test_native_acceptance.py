from copy import deepcopy
import unittest
import uuid
from soorin.e2e.native_validation import acceptance_events, assert_receipt_graph

class NativeAcceptanceTests(unittest.TestCase):
    def fixture(self):
        event = acceptance_events()[0][1]
        document = {'document_id':str(uuid.uuid4()),'document_version':2,'status':'ready','graph_status':'done'}
        diagnostic = {'status':'bound', 'source_id':'synthetic-source', 'source_scope':{
            k:getattr(event,k) for k in ('tenant_id','source_system','source_instance')},'document':document,
            'entities':[{'canonical_key':e.entity_id,'entity_id':str(uuid.uuid4()),'expected_type':e.entity_type,
                'type_matches':True,'authority_linked':True} for e in event.entities],
            'relations':[{'expected_relation_key':r.relation_type.lower(), 'binding':{
                'subject_canonical_key':r.subject_entity_id,'object_canonical_key':r.object_entity_id,
                'document_id':document['document_id'],'document_version':2,
                'binding_relation_key':r.relation_type.lower(),'direction':'forward',
                'type_binding_status':'bound','phrase_binding_status':'bound','evidence_link_status':True}}
                for r in event.relations]}
        return event,diagnostic

    def test_requires_exact_relation_endpoints_version_and_evidence(self):
        event, diagnostic = self.fixture()
        self.assertEqual(assert_receipt_graph(event, diagnostic,source_id='synthetic-source'), len(event.relations))
        for key,value,reason in [('evidence_link_status',False,'evidence_missing'),
            ('subject_canonical_key','unrelated','set_mismatch'),('object_canonical_key','unrelated','set_mismatch'),
            ('document_version',1,'current_version'),('document_id','unrelated','current_version'),
            ('binding_relation_key','unrelated','evidence_missing')]:
            altered = deepcopy(diagnostic)
            altered['relations'][0]['binding'][key] = value
            with self.subTest(key=key),self.assertRaisesRegex(AssertionError,reason):
                assert_receipt_graph(event,altered)
        diagnostic['relations'] = []
        with self.assertRaisesRegex(AssertionError,'set_mismatch'):
            assert_receipt_graph(event, diagnostic)
        diagnostic['status'] = 'submitted'
        with self.assertRaisesRegex(AssertionError,'not_bound'):
            assert_receipt_graph(event, diagnostic)

    def test_wrong_source_authority_or_entity_cannot_pass(self):
        event,diagnostic = self.fixture()
        with self.assertRaisesRegex(AssertionError,'source_mismatch'):
            assert_receipt_graph(event,diagnostic,source_id='other-source')
        diagnostic['source_scope']['tenant_id'] = 'other-tenant'
        with self.assertRaisesRegex(AssertionError,'authority_mismatch'):
            assert_receipt_graph(event,diagnostic)
        event,diagnostic = self.fixture()
        diagnostic['entities'][0]['authority_linked'] = False
        with self.assertRaisesRegex(AssertionError,'authority_missing'):
            assert_receipt_graph(event,diagnostic)

    def test_existing_session_creates_only_a_new_synthetic_workspace(self):
        from soorin.e2e.native_validation import bootstrap_synthetic_workspace
        calls = []
        def request(base,path,**kwargs):
            calls.append((path,kwargs))
            return {'id':'synthetic-workspace'} if path.endswith('/workspaces') else {'user':{'id':'synthetic'}}
        token,workspace=bootstrap_synthetic_workspace('http://127.0.0.1:2526',token='synthetic-session',request=request)
        self.assertEqual(workspace,'synthetic-workspace')
        self.assertEqual(token,'synthetic-session')
        self.assertEqual([path for path,_ in calls],['/api/v1/auth/me','/api/v1/workspaces'])
        self.assertNotIn('/api/v1/auth/register',[path for path,_ in calls])
