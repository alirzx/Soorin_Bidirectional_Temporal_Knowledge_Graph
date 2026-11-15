"""Opt-in synthetic API/worker acceptance in an explicitly disposable runtime.

Creates new synthetic accounts/KBs/sources; never deletes or converts lab data.
Run only in the documented private Docker network with a NEW database.
"""
import argparse
from dataclasses import replace
from datetime import UTC,datetime
import json,os,secrets,time,uuid
from pathlib import Path
from soorin.e2e.local_validation import (_request_json,select_isolated_api,DEFAULT_FIXTURE,normalize_fixture,_load_fixture,ValidationError)
from soorin.ontology.importer import OntologyImporter,load_and_validate
from soorin.ops.ingest import submit
from soorin.e2e.qa_target import verify_qa_target
from soorin.contracts.grounded_context import extractive_answer

def acceptance_events():
    """Explicit source clocks for synthetic revision acceptance, not delivery clocks."""
    rows = _load_fixture(DEFAULT_FIXTURE)
    clocks = {'changed_status':'2026-10-20T10:30:00Z', 'corrected_source_event':'2026-10-20T11:00:00Z'}
    for row in rows:
        if row['scenario'] in clocks:
            row['raw_record']['source_updated_at'] = clocks[row['scenario']]
    return [(name,event) for name,event in normalize_fixture(rows) if event.tenant_id=='tenant-blue']


def assert_receipt_graph(event, diagnostics, *, source_id=None):
    if diagnostics.get('status') != 'bound':
        raise AssertionError('receipt_not_bound')
    if source_id is not None and diagnostics.get('source_id') != source_id:
        raise AssertionError('receipt_source_mismatch')
    scope = diagnostics.get('source_scope') or {}
    if scope != {key:getattr(event,key) for key in ('tenant_id','source_system','source_instance')}:
        raise AssertionError('receipt_authority_mismatch')
    document = diagnostics.get('document') or {}
    if document.get('status') != 'ready' or document.get('graph_status') != 'done':
        raise AssertionError('document_not_complete')
    if not document.get('document_id') or type(document.get('document_version')) is not int:
        raise AssertionError('document_provenance_missing')
    expected_entities = {e.entity_id:e for e in event.entities}
    actual_entities = diagnostics.get('entities', [])
    if {e['canonical_key'] for e in actual_entities} != set(expected_entities):
        raise AssertionError('expected_entity_set_mismatch')
    for entity in actual_entities:
        if (entity.get('type_matches') is not True or entity.get('authority_linked') is not True or
            entity.get('expected_type') != expected_entities[entity['canonical_key']].entity_type):
            raise AssertionError('entity_type_or_authority_missing')
        uuid.UUID(entity['entity_id'])
    expected = sorted((r.relation_type.lower(), r.subject_entity_id, r.object_entity_id) for r in event.relations)
    actual = diagnostics.get('relations', [])
    observed = sorted((r['expected_relation_key'],r['binding'].get('subject_canonical_key'),
                       r['binding'].get('object_canonical_key')) for r in actual)
    if observed != expected or diagnostics.get('unsupported_relation_count', 0):
        raise AssertionError('expected_relation_set_mismatch')
    for relation in actual:
        binding = relation['binding']
        if (binding.get('type_binding_status') != 'bound' or
            binding.get('phrase_binding_status') != 'bound' or
            binding.get('binding_relation_key') != relation['expected_relation_key'] or
            binding.get('direction') != 'forward' or
            binding.get('evidence_link_status') is not True):
            raise AssertionError('typed_relation_or_evidence_missing')
        if (binding.get('document_id') != document['document_id'] or
            binding.get('document_version') != document['document_version']):
            raise AssertionError('current_version_evidence_missing')
    return len(actual)


def bootstrap_synthetic_workspace(base, *, token='', request=_request_json):
    if token:
        # Validate the credential before creating anything, then isolate settings
        # in a new workspace instead of modifying the operator's existing one.
        request(base,'/api/v1/auth/me',token=token)
        workspace=request(base,'/api/v1/workspaces',token=token,method='POST',
            body={'name':'Synthetic SOC acceptance '+str(uuid.uuid4())[:8]})
        return token,workspace['id']
    registered=request(base,'/api/v1/auth/register',method='POST',body={
        'email':f'{uuid.uuid4()}@synthetic.example','password':secrets.token_urlsafe(24),
        'display_name':'Synthetic acceptance','org_name':'Disposable SOC acceptance'})
    return registered['token'],registered['workspace']['id']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true');p.add_argument('--base-url',default='http://127.0.0.1:2516');p.add_argument('--report',type=Path,required=True)
    p.add_argument('--deadline',type=float,default=300)
    p.add_argument('--with-cpu-models',action='store_true')
    p.add_argument('--qa-project');p.add_argument('--approved-port',type=int)
    args=p.parse_args();base=select_isolated_api(args.base_url,qa_project=args.qa_project,approved_port=args.approved_port)
    report={'schema_version':'soorin.native-acceptance.v1','synthetic':True,'checks':[]}
    def save(name,status,**evidence):
        report['checks'].append({'name':name,'status':status,'evidence':evidence})
        args.report.parent.mkdir(parents=True,exist_ok=True)
        temporary=args.report.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2));temporary.replace(args.report)
        print(json.dumps({'stage':name,'status':status}),flush=True)
    if not args.execute:save('live_execution','NOT RUN');return
    if os.environ.get('SOORIN_DISPOSABLE_ACCEPTANCE')!='1':p.error('requires SOORIN_DISPOSABLE_ACCEPTANCE=1 in a private disposable runtime')
    try:
        verify_qa_target(base,args.qa_project)
        token,workspace=bootstrap_synthetic_workspace(base,token=os.environ.get('UTOPIA_SESSION_TOKEN',''))
        def api(path,body=None,method=None):return _request_json(base,path,token=token,body=body,method=method or ('POST' if body is not None else 'GET'))
        kb=api(f'/api/v1/workspaces/{workspace}/kbs',{'name':'Native SOC synthetic acceptance','visibility':'restricted'})['id']
        other=api(f'/api/v1/workspaces/{workspace}/kbs',{'name':'Other synthetic tenant','visibility':'restricted'})['id']
        save('isolated_bootstrap','PASS',knowledge_base_id=kb,other_kb_id=other)
        if args.with_cpu_models:
            from soorin.services.cpu_models import MODELS
            api(f'/api/v1/workspaces/{workspace}/settings', {'embed_base_url':'http://models:8080/v1',
                'embed_model':'@'.join(MODELS['embedding']), 'embed_dim':1024}, 'PUT')
            api(f'/api/v1/workspaces/{workspace}/settings/reranker', {'enabled':True,
                'base_url':'http://models:8081', 'model':'@'.join(MODELS['reranker']), 'fallback':False}, 'PUT')
        importer=OntologyImporter(base,kb,token,request=lambda method,path,body:api(f'/api/v1/kbs/{kb}'+path,body,method))
        ontology=load_and_validate(Path(__file__).parents[1]/'ontology/soc_ontology_v1.yaml')
        importer.apply(ontology)
        api(f'/api/v1/kbs/{kb}/knowledge/binding',{'tenant_id':'tenant-blue','source_system':'splunk','source_instance':'splunk-e2e'},'PUT')
        created=api(f'/api/v1/kbs/{kb}/sources',{'kind':'statements','name':'Native synthetic receipts','config':{}})
        source=created['source']['id'];ingest=created['ingest_token']
        save('ontology_source_binding','PASS',entity_types=17,relation_types=15,source_id=source)
        def wait_receipt(receipt,wanted='bound'):
            end=time.monotonic()+args.deadline
            while time.monotonic()<end:
                data=api(f'/api/v1/kbs/{kb}/knowledge/receipts')
                row=next((r for r in data['receipts'] if r['receipt_id']==receipt['receipt_id']),None)
                if row and row['status']==wanted:return row
                if row and (row['status']=='quarantined' or row.get('job_status')=='failed'):
                    raise AssertionError('receipt_terminal_before_expected_state')
                time.sleep(1)
            raise TimeoutError('receipt_materialization_deadline')
        events=acceptance_events()
        initial=events[0][1];initial_context=None;snapshot=None;entity_uuid=None
        for name,event in events:
            receipt=submit(base,source,ingest,event)
            row=wait_receipt(receipt)
            diagnostic=api(f'/api/v1/kbs/{kb}/knowledge/receipts/{receipt["receipt_id"]}')
            relation_count=assert_receipt_graph(event,diagnostic,source_id=source)
            save('evidence_'+name,'PASS',expected_relations=relation_count,document_id=diagnostic['document']['document_id'])
            replay=submit(base,source,ingest,event)
            assert replay['receipt_id']==receipt['receipt_id'] and replay['job_id']==row['job_id']
            save('ingest_'+name,'PASS',receipt_id=receipt['receipt_id'],status=row['status'],replay_deduplicated=True)
            if initial_context is None:
                alert = next(e for e in event.entities if e.entity_type=='SecurityAlert')
                authority,identifier = next(iter(alert.source_identifiers.items()))
                resolution=api(f'/api/v1/kbs/{kb}/knowledge/resolve',{'tenant_id':'tenant-blue',
                    'source_system':'splunk','source_instance':'splunk-e2e','entity_type':'SecurityAlert',
                    'authority_name':authority,'source_identifier':identifier})
                assert resolution['status']=='resolved' and resolution['automatic']
                entity_uuid=resolution['candidates'][0]['entity_id']
                initial_context=api(f'/api/v1/kbs/{kb}/knowledge/context',{'tenant_id':'tenant-blue','entity':entity_uuid,'limit':100})
                assert initial_context['resolved_entities']
                snapshot=datetime.now(UTC).isoformat()
        late=replace(initial, observed_at='2026-10-20T09:00:00Z', source_revision_id='synthetic-late-revision', content_checksum=None)
        late_receipt=submit(base,source,ingest,late)
        late_status=wait_receipt(late_receipt,'quarantined')
        assert late_status['failure_code']=='late_or_ambiguous_revision_retained_for_review'
        save('late_revision_quarantine','PASS',receipt_id=late_receipt['receipt_id'])
        end=time.monotonic()+args.deadline
        while True:
            graph=api(f'/api/v1/kbs/{kb}/graph/overview?limit=1000')
            typed=[e for e in graph.get('edges',[]) if e.get('predicate')=='observed_on' and e.get('inferred') is False and not e.get('derived')]
            if typed:break
            if time.monotonic()>=end:raise TimeoutError('typed_materialization_deadline')
            time.sleep(1)
        save('typed_graph','PASS',total_nodes=graph.get('total_nodes'),total_edges=graph.get('total_edges'),observed_on_typed=len(typed))
        historical=api(f'/api/v1/kbs/{kb}/knowledge/context',{'tenant_id':'tenant-blue','entity':entity_uuid,'as_of':snapshot,'limit':100})
        assert initial.content_checksum in json.dumps(historical['facts'])
        save('historical_checksum_and_citations','PASS',fact_count=len(historical['facts']),citation_count=len(historical['evidence_references']))
        current=api(f'/api/v1/kbs/{kb}/knowledge/context',{'tenant_id':'tenant-blue','entity':'SOC-E2E-ALERT-001','limit':100})
        answer=extractive_answer(current);assert answer['claims']
        save('grounded_context','PASS',facts=len(current['facts']),citations=len(current['evidence_references']),extractive_claims=len(answer['claims']),generated=False)
        search=api(f'/api/v1/kbs/{kb}/search',{'q':'SOC-E2E-ALERT-001','top_k':20});assert search['results']
        save('native_search','PASS',result_count=len(search['results']),retrieval=search['retrieval'])
        if args.with_cpu_models:
            assert search['retrieval']['dense_executed'] is True
            assert search['retrieval']['lexical_method']=='tantivy_bm25'
            assert search['retrieval']['reranker_status']=='complete'
            save('cpu_retrieval_execution','PASS',quality='NOT MEASURED')
        else:
            save('cpu_retrieval_execution','NOT RUN',reason='requires --with-cpu-models')
        for target,tenant in [(kb,'tenant-red'),(other,'tenant-blue')]:
            try:api(f'/api/v1/kbs/{target}/knowledge/context',{'tenant_id':tenant,'entity':'SOC-E2E-ALERT-001'})
            except ValidationError as error:assert 'HTTP 404' in str(error)
            else:raise AssertionError('tenant_isolation_failed')
        save('tenant_binding_isolation','PASS')
        failed=api(f'/api/v1/kbs/{kb}/jobs/failed');assert failed.get('failed',0)==0
        save('failed_jobs','PASS',diagnostics=failed)
    except (Exception,KeyboardInterrupt) as error:
        save('execution','BLOCKED' if isinstance(error,(KeyboardInterrupt,ValidationError)) else 'FAIL',category=type(error).__name__,reason=str(error) if isinstance(error,(AssertionError,TimeoutError)) else 'request_or_runtime_failure' )
        save('dependent_checks','BLOCKED',reason='prerequisite_failed; subsequent API calls were not made')
        raise SystemExit(1)

if __name__=='__main__':main()
