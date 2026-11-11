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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true');p.add_argument('--base-url',default='http://127.0.0.1:2516');p.add_argument('--report',type=Path,required=True)
    p.add_argument('--deadline',type=float,default=120)
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
        registered=_request_json(base,'/api/v1/auth/register',method='POST',body={'email':f'{uuid.uuid4()}@synthetic.example','password':secrets.token_urlsafe(24),'display_name':'Synthetic acceptance','org_name':'Disposable SOC acceptance'})
        token=registered['token'];workspace=registered['workspace']['id']
        def api(path,body=None,method=None):return _request_json(base,path,token=token,body=body,method=method or ('POST' if body is not None else 'GET'))
        kb=api(f'/api/v1/workspaces/{workspace}/kbs',{'name':'Native SOC synthetic acceptance','visibility':'restricted'})['id']
        other=api(f'/api/v1/workspaces/{workspace}/kbs',{'name':'Other synthetic tenant','visibility':'restricted'})['id']
        save('isolated_bootstrap','PASS',knowledge_base_id=kb,other_kb_id=other)
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
        # Re-run failed import-time jobs through their real handlers, not SQL status edits.
        api(f'/api/v1/kbs/{kb}/jobs/requeue',{})
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
        for target,tenant in [(kb,'tenant-red'),(other,'tenant-blue')]:
            try:api(f'/api/v1/kbs/{target}/knowledge/context',{'tenant_id':tenant,'entity':'SOC-E2E-ALERT-001'})
            except ValidationError as error:assert 'HTTP 404' in str(error)
            else:raise AssertionError('tenant_isolation_failed')
        save('tenant_binding_isolation','PASS')
        failed=api(f'/api/v1/kbs/{kb}/jobs/failed');assert failed.get('failed',0)==0
        save('failed_jobs','PASS',diagnostics=failed)
    except (Exception,KeyboardInterrupt) as error:
        save('execution','FAIL' if not isinstance(error,KeyboardInterrupt) else 'BLOCKED',category=type(error).__name__,reason=str(error) if isinstance(error,(ValidationError,TimeoutError)) else 'assertion_or_runtime_failure')
        raise SystemExit(1)

if __name__=='__main__':main()
