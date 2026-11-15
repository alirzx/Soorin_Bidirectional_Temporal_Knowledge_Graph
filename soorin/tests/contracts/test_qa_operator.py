"""Offline regression tests for QA login and deterministic Splunk fixture."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from soorin.ops import qa_login, qa_existing_kb
from soorin.tests.mock_splunk.scripts.curated_qa_dataset import generate, make_record


class QaOperatorTests(unittest.TestCase):
    def test_login_uses_no_tty_capture_and_restricts_base(self):
        with self.assertRaises(ValueError):
            qa_login.authenticate("http://example.invalid", "qa@example.invalid", "x")
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(SystemExit) as raised:
                qa_login.main([])
        self.assertNotEqual(raised.exception.code, 0)

    def test_private_session_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            qa_login.save_token(path, "dummy-qa-token")
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertEqual(qa_login.load_token(path), "dummy-qa-token")
            with patch.dict(os.environ, {"UTOPIA_SESSION_TOKEN": ""}):
                with patch.object(qa_login, "load_token", return_value=qa_login.load_token(path)):
                    self.assertEqual(qa_existing_kb.session_token(), "dummy-qa-token")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                qa_login.load_token(path)

    def test_existing_kb_only_does_not_create(self):
        with patch.object(qa_existing_kb, "api", side_effect=[
            [{"id": "ws-a", "name": "Existing Workspace"}],
            [{"id": "kb-b", "name": "Soorin SOC Synthetic Lab"}]
        ]):
            workspace, kb = qa_existing_kb.find_existing_kb("dummy", "Soorin SOC Synthetic Lab")
            self.assertEqual(workspace["id"], "ws-a")
            self.assertEqual(kb["id"], "kb-b")

    def test_partial_receipt_coverage_must_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipts.jsonl"
            path.write_text(json.dumps({"kb_id": "kb", "dataset": "alerts.jsonl",
                                        "index": 0, "receipt_id": "id"}) + "\n")
            with patch.object(qa_existing_kb, "state_file", return_value=path):
                with self.assertRaises(SystemExit):
                    qa_existing_kb.tracked_receipts("kb", "alerts.jsonl", 0, 10)

    def test_fixture_stable_and_distinct_revision(self):
        first = make_record(0)
        self.assertEqual(first["alert_row_id"], "soc-alert-synthetic-00000")
        self.assertEqual(first["llm_payload"]["_meta"]["mode"], "enriched_from_api")
        second = make_record(0, revision=2)
        self.assertEqual(first["alert_row_id"], second["alert_row_id"])
        self.assertNotEqual(first["source_revision_id"], second["source_revision_id"])
        self.assertNotEqual(first["source_updated_at"], second["source_updated_at"])

    def test_dataset_generation_counts_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixtures"
            manifest = generate(root, 12, 2)
            self.assertEqual(manifest["alerts"], 12)
            self.assertEqual(manifest["separate_revisions"], 2)
            self.assertEqual(len((root / "alerts.jsonl").read_text().splitlines()), 12)
            self.assertEqual(len((root / "revisions.jsonl").read_text().splitlines()), 2)
            with self.assertRaises(FileExistsError):
                generate(root, 12, 2)

    def test_ten_alert_gate_requires_specific_graph_identity_and_title_citations(self):
        import copy
        import uuid
        from soorin.ops.preview import preview
        rows=[(i,{'profile':qa_existing_kb.PROFILE,'record':make_record(i)}) for i in [0,6]]
        tracked={i:{'receipt_id':f'receipt-{i}'} for i,_ in rows}
        diagnostics={}
        alert_ids={}
        for i,record in rows:
            event,_=preview(json.dumps(record['record']),tenant_id='tenant-blue',source_instance='splunk-e2e')
            doc=f'document-{i}'
            identities={e.entity_id:str(uuid.uuid5(uuid.NAMESPACE_URL,e.entity_id)) for e in event.entities}
            alert=next(e for e in event.entities if e.entity_type=='SecurityAlert')
            alert_ids[record['record']['alert_row_id']]=identities[alert.entity_id]
            diagnostics[f'receipt-{i}']={'status':'bound','source_id':'source','source_scope':{
                k:getattr(event,k) for k in ['tenant_id','source_system','source_instance']},
                'document':{'document_id':doc,'document_version':1,'status':'ready','graph_status':'done'},
                'entities':[{'canonical_key':e.entity_id,'entity_id':identities[e.entity_id],
                    'expected_type':e.entity_type,'type_matches':True,'authority_linked':True} for e in event.entities],
                'relations':[{'expected_relation_key':r.relation_type.lower(),'binding':{
                    'subject_canonical_key':r.subject_entity_id,'object_canonical_key':r.object_entity_id,
                    'type_binding_status':'bound','phrase_binding_status':'bound','binding_relation_key':r.relation_type.lower(),
                    'direction':'forward','evidence_link_status':True,'document_id':doc,'document_version':1}}
                    for r in event.relations]}
        def request(method,path,token,data=None):
            if method=='GET':return diagnostics[path.rsplit('/',1)[-1]]
            if path.endswith('/resolve'):
                return {'status':'resolved','automatic':True,'candidates':[{'entity_id':alert_ids[data['source_identifier']]}]}
            return {'retrieval':{'lexical_method':'tantivy_bm25','dense_executed':False},'results':[
                {'id':f'chunk-{i}','document_id':f'document-{i}','text':'Password Spray Detection'} for i,_ in rows]}
        result=qa_existing_kb.accept_batch('token','kb','source',rows,tracked,request=request)
        self.assertEqual(result['receipts_bound'],2)
        self.assertEqual(result['shared_case_keys'],1)
        def unrelated(method,path,token,data=None):
            if path.endswith('/search'):
                return {'retrieval':{'lexical_method':'tantivy_bm25','dense_executed':False},
                    'results':[{'id':'unrelated-chunk','document_id':'another-document','text':'Password Spray Detection'}]}
            return request(method,path,token,data)
        with self.assertRaisesRegex(ValueError,'citation_not_recalled'):
            qa_existing_kb.accept_batch('token','kb','source',rows,tracked,request=unrelated)
        case=next(e for e in diagnostics['receipt-6']['entities'] if e['expected_type']=='SOCCase')
        case['entity_id']=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'shared_canonical_identity_split'):
            qa_existing_kb.accept_batch('token','kb','source',rows,tracked,request=request)
        diagnostics['receipt-0']['status']='submitted'
        with self.assertRaisesRegex(AssertionError,'not_bound'):
            qa_existing_kb.accept_batch('token','kb','source',rows,tracked,request=request)


if __name__ == "__main__":
    unittest.main()
